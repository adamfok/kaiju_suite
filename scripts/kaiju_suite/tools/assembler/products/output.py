"""Outputs (.out): save the built rig to a deliverable file, as a build step.

The entry is a Kaiju data file (``{"kaiju": "output", "format": 1, "data":
{...}}``) holding where to save, the format coming from that file's
extension (``.ma``, ``.mb`` or ``.fbx``), and two optional clean-ups run
first: delete unused nodes (as Hypershade's Delete Unused Nodes) and hide
joints (draw style None). Run exports the whole scene there; the open
scene keeps its own name. Usually the last step, so Run All ends with a
file to hand over.

Right-click Publish opens a save-file browser and saves the picked path as
the entry's next version; the Info window turns the clean-ups on and off,
each change a version too. No Qt here.
"""

import os

from maya import cmds, mel

from kaiju_suite.core import datafile
from kaiju_suite.core.undo import undoable
from kaiju_suite.tools.assembler import runlog, versions
from kaiju_suite.tools.assembler.products import Action, Creator, Panel, Product, ext_of, is_empty, new_path

EXTENSION = ".out"
KIND = "output"

# Output file extension -> (format name shown to the user, Maya file type).
FORMATS = {
    ".ma": ("Maya ASCII", "mayaAscii"),
    ".mb": ("Maya Binary", "mayaBinary"),
    ".fbx": ("FBX", "FBX export"),
}
FBX_PLUGIN = "fbxmaya"

# Clean-up options, in the order the Info window shows them, with their labels.
OPTIONS = {"delete_unused": "Delete Unused Nodes", "hide_joints": "Hide Joints"}

_FILE_FILTER = "Maya ASCII (*.ma);;Maya Binary (*.mb);;FBX (*.fbx)"

# Joint draw style that hides the joint without hiding what's below it.
_DRAW_STYLE_NONE = 2


# -- the entry ------------------------------------------------------------------


def create_output(directory, name):
    """Create an empty ``.out`` entry and return its path. A build skips it
    (with a warning) until a path is set with :func:`set_output`."""
    path = new_path(directory, name, EXTENSION)
    with open(path, "wb"):
        pass
    return path


def format_name(out_path):
    """The format ``out_path`` is saved in, by its extension, e.g. ``FBX``."""
    ext = ext_of(out_path)
    if ext not in FORMATS:
        raise ValueError(f"Can't save {os.path.basename(out_path) or 'a file with no name'}: use .ma, .mb or .fbx")
    return FORMATS[ext][0]


def problems(data):
    """What's wrong with output settings ``data``, as messages."""
    if not isinstance(data, dict):
        return ["output settings must be an object"]
    found = []
    out_path = data.get("path")
    if not isinstance(out_path, str) or not out_path:
        found.append(f"path must be the file to save, not {out_path!r}")
    elif ext_of(out_path) not in FORMATS:
        found.append(f"path must end in .ma, .mb or .fbx, not {out_path!r}")
    for key in OPTIONS:
        if not isinstance(data.get(key, False), bool):
            found.append(f"{key} must be true or false, not {data[key]!r}")
    return found


def _normalized(out_path, delete_unused, hide_joints):
    return {"path": out_path, "delete_unused": delete_unused, "hide_joints": hide_joints}


def settings(path):
    """The entry's settings, ``{"path", "delete_unused", "hide_joints"}``, or
    ``None`` if it's empty. Raises ``ValueError`` if it isn't an output entry."""
    if is_empty(path):
        return None
    data = datafile.read(path, KIND)
    found = problems(data)
    if found:
        raise datafile.DataFormatError(f"{os.path.basename(path)}: {'; '.join(found)}")
    return _normalized(data["path"], data.get("delete_unused", False), data.get("hide_joints", False))


def _write(target, data):
    datafile.write(target, KIND, data)


def set_output(path, out_path, delete_unused=False, hide_joints=False):
    """Make the entry at ``path`` save to ``out_path`` (stored as given) with
    these clean-ups, as its next version. Returns a message, e.g.
    ``Published Output rig.out v002``."""
    data = _normalized(out_path, delete_unused, hide_joints)
    found = problems(data)
    if found:
        raise ValueError("; ".join(found))
    return versions.export_into(path, lambda target: _write(target, data))


def set_option(path, key, value):
    """Turn clean-up ``key`` (see :data:`OPTIONS`) on or off, as the entry's
    next version. Returns a message."""
    if key not in OPTIONS:
        raise ValueError(f"Not an output option: {key}")
    current = settings(path)
    if current is None:
        raise ValueError(f"{os.path.basename(path)} has no output file yet: publish it first")
    current[key] = bool(value)
    return set_output(path, current["path"], current["delete_unused"], current["hide_joints"])


# -- the file browser -----------------------------------------------------------


def pick_output_file(start_dir):
    """Ask where to save with a file browser opened in ``start_dir``.
    Returns the path, or ``None`` if cancelled. GUI Maya only."""
    picked = cmds.fileDialog2(
        caption="Publish Output",
        fileMode=0,
        fileFilter=_FILE_FILTER,
        dialogStyle=2,
        startingDirectory=start_dir,
    )
    return picked[0] if picked else None


def _start_dir(path):
    """The current output's folder if it exists, else the entry's own."""
    try:
        current = settings(path)
    except ValueError:
        current = None
    folder = os.path.dirname(current["path"]) if current else ""
    return folder if folder and os.path.isdir(folder) else os.path.dirname(path)


def publish_from_browser(path):
    """Pick where to save, keeping the clean-up options. Returns ``None`` (no
    message) if the browser is cancelled."""
    picked = pick_output_file(_start_dir(path))
    if not picked:
        return None
    try:
        current = settings(path) or {}
    except ValueError:
        current = {}
    return set_output(path, picked, current.get("delete_unused", False), current.get("hide_joints", False))


# -- running ----------------------------------------------------------------------


def _plugin_loaded(name):
    return bool(cmds.pluginInfo(name, query=True, loaded=True))


def ensure_fbx_plugin():
    """Load the fbxmaya plug-in if it isn't loaded; raise a clear error if it can't."""
    if _plugin_loaded(FBX_PLUGIN):
        return
    try:
        cmds.loadPlugin(FBX_PLUGIN, quiet=True)
    except RuntimeError as e:
        raise RuntimeError(
            f"Can't save FBX: the {FBX_PLUGIN} plug-in didn't load ({e}). "
            "Check it in Windows > Settings/Preferences > Plug-in Manager."
        ) from e


def hide_joints():
    """Set every joint's draw style to None. Joints whose draw style is locked
    or connected are skipped, with one warning naming them."""
    skipped = []
    for joint in cmds.ls(type="joint", long=True):
        attr = f"{joint}.drawStyle"
        if cmds.getAttr(attr, lock=True) or cmds.connectionInfo(attr, isDestination=True):
            skipped.append(joint.rsplit("|", 1)[-1])
            continue
        cmds.setAttr(attr, _DRAW_STYLE_NONE)
    if skipped:
        runlog.warning(f"Couldn't hide joints with a locked or connected draw style: {', '.join(skipped)}")


def delete_unused_nodes():
    """Delete unused shading nodes, as Hypershade's Delete Unused Nodes."""
    mel.eval("MLdeleteUnused")


@undoable
def clean_up(delete_unused=False, hide=False):
    """Run the chosen clean-ups on the scene, as one undo step."""
    if delete_unused:
        delete_unused_nodes()
    if hide:
        hide_joints()


def save_scene(out_path):
    """Export the whole scene to ``out_path`` in the format its extension
    names, creating its folder if needed. The open scene keeps its name."""
    format_name(out_path)  # raises on an unknown extension
    file_type = FORMATS[ext_of(out_path)][1]
    if file_type == FORMATS[".fbx"][1]:
        ensure_fbx_plugin()
    folder = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(folder, exist_ok=True)
    cmds.file(out_path, exportAll=True, type=file_type, force=True)
    return out_path


def run_output(path):
    """Clean up the scene as the entry at ``path`` says, then save it."""
    current = settings(path)
    if current is None:
        runlog.warning(f"{os.path.basename(path)} has no output file set: nothing saved. Publish it to pick one.")
        return None
    out_path = current["path"]
    format_name(out_path)
    # Check FBX can be written before cleaning anything up.
    if ext_of(out_path) == ".fbx":
        ensure_fbx_plugin()
    clean_up(current["delete_unused"], current["hide_joints"])
    save_scene(out_path)
    runlog.info(f"Saved {format_name(out_path)} to {out_path}")
    return out_path


# -- the product ------------------------------------------------------------------


def _on_off(value):
    return "on" if value else "off"


class OutputProduct(Product):
    name = "Output"
    extensions = (EXTENSION,)
    order = 150
    menu_slot = (6, 1)  # last, after Check: usually the build's last step
    runnable = True
    versioned = True
    creators = (Creator("Output", lambda directory, name, _ext: create_output(directory, name)),)

    def run(self, path):
        run_output(path)

    def publish(self, path):
        # No question first: the settings it replaces are kept as a version.
        return Action("Publish", lambda: publish_from_browser(path))

    def to_plan(self, path):
        current = settings(path)
        return {} if current is None else dict(current)

    def plan_problems(self, item):
        fields = {k: item[k] for k in ("path", *OPTIONS) if k in item}
        if not fields:
            return []
        return problems(fields)

    def from_plan(self, path, item):
        if item.get("path"):
            _write(path, _normalized(item["path"], item.get("delete_unused", False), item.get("hide_joints", False)))
        else:
            super().from_plan(path, item)

    def panel(self, path):
        try:
            current = settings(path)
        except ValueError as e:
            return Panel([str(e)], [])
        if current is None:
            return Panel(["Not set up: publish it to pick where to save. A build skips it until then."], [])
        info = [
            f"Saves to: {current['path']}",
            f"Format: {format_name(current['path'])}",
            f"Delete unused nodes: {_on_off(current['delete_unused'])}",
            f"Hide joints: {_on_off(current['hide_joints'])}",
            versions.summary(path),
        ]
        actions = [
            Action(
                f"Turn {'Off' if current[key] else 'On'} {label}",
                lambda key=key, value=not current[key]: set_option(path, key, value),
            )
            for key, label in OPTIONS.items()
        ]
        return Panel(info, actions)


PRODUCT = OutputProduct()
