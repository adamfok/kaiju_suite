"""Export Scenes (.out): save the built rig to a deliverable file, as a build step.

The counterpart of an Import Scene: the entry holds only a path, here the
file to save to. It's a Kaiju data file (``{"kaiju": "output", "format": 1,
"data": {"path": ...}}``); the format comes from the path's extension
(``.ma``, ``.mb`` or ``.fbx``). Run exports the whole scene there; the open
scene keeps its own name. Usually the last step, so Run All ends with a
file to hand over.

Right-click Publish opens a save-file browser and saves the picked path as
the entry's next version, stored portably with :mod:`kaiju_suite.core.paths`
(relative to the folder holding the entry, or ``$ASSET/...``). Entries
written before this may also hold ``delete_unused`` and ``hide_joints``
clean-up switches; they're ignored. No Qt here.
"""

import os

from maya import cmds

from kaiju_suite.core import datafile, paths
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

_FILE_FILTER = "Maya ASCII (*.ma);;Maya Binary (*.mb);;FBX (*.fbx)"

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
    return found


def settings(path):
    """The entry's settings, ``{"path": ...}``, or ``None`` if it's empty.
    Raises ``ValueError`` if it isn't an output entry. Fields other than
    ``path`` (old clean-up switches) are dropped."""
    if is_empty(path):
        return None
    data = datafile.read(path, KIND)
    found = problems(data)
    if found:
        raise datafile.DataFormatError(f"{os.path.basename(path)}: {'; '.join(found)}")
    return {"path": data["path"]}


def _write(target, data):
    datafile.write(target, KIND, data)


def build_root(path):
    """The folder relative output paths in the entry at ``path`` are
    relative to: the folder holding the entry."""
    return os.path.dirname(os.path.abspath(path))


def target(path):
    """The file the entry at ``path`` saves to, as an absolute path (unless
    it uses a variable that isn't set), or ``None`` if it's empty."""
    current = settings(path)
    return None if current is None else paths.resolve(current["path"], build_root(path))


def set_output(path, out_path, description=None):
    """Make the entry at ``path`` save to ``out_path``, as its next version,
    described as ``description`` (see
    ``versions.save_version``). ``out_path`` is stored portably: relative to the
    entry's folder when under it, else ``$ASSET/...`` when under that, else
    absolute; relative text is taken as relative to the entry's folder.
    Returns a message, e.g. ``Published Export Scene rig.out v002``."""
    data = {"path": out_path}
    found = problems(data)
    if found:
        raise ValueError("; ".join(found))
    root = build_root(path)
    data["path"] = paths.to_portable(paths.resolve(out_path, root), root)
    return versions.export_into(path, lambda target: _write(target, data), description)


# -- the file browser -----------------------------------------------------------


def pick_output_file(start_dir):
    """Ask where to save with a file browser opened in ``start_dir``.
    Returns the path, or ``None`` if cancelled. GUI Maya only."""
    picked = cmds.fileDialog2(
        caption="Publish Export Scene",
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
    folder = os.path.normpath(os.path.dirname(paths.resolve(current["path"], build_root(path)))) if current else ""
    return folder if folder and os.path.isdir(folder) else os.path.dirname(path)


def publish_from_browser(path):
    """Pick where to save. Returns ``None`` (no message) if the browser is
    cancelled."""
    picked = pick_output_file(_start_dir(path))
    if not picked:
        return None
    return set_output(path, picked)


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
    """Save the scene where the entry at ``path`` says."""
    current = settings(path)
    if current is None:
        runlog.warning(f"{os.path.basename(path)} has no output file set: nothing saved. Publish it to pick one.")
        return None
    out_path = paths.resolve(current["path"], build_root(path))
    save_scene(out_path)
    runlog.info(f"Saved {format_name(out_path)} to {out_path}")
    return out_path


# -- the product ------------------------------------------------------------------


class OutputProduct(Product):
    name = "Export Scene"
    extensions = (EXTENSION,)
    order = 150
    menu_slot = (6, 1)  # last, after Check: usually the build's last step
    runnable = True
    versioned = True
    creators = (Creator("Export Scene", lambda directory, name, _ext: create_output(directory, name)),)

    def run(self, path):
        run_output(path)

    def publish(self, path):
        # No question first: the path it replaces is kept as a version.
        return Action("Publish", lambda: publish_from_browser(path))

    def to_plan(self, path):
        current = settings(path)
        return {} if current is None else dict(current)

    def plan_problems(self, item):
        # Old plans may also hold clean-up switches; they're ignored.
        return problems({"path": item["path"]}) if "path" in item else []

    def from_plan(self, path, item):
        if item.get("path"):
            _write(path, {"path": item["path"]})
        else:
            super().from_plan(path, item)

    def panel(self, path):
        try:
            current = settings(path)
        except ValueError as e:
            return Panel([str(e)], [])
        if current is None:
            return Panel(["Not set up: publish it to pick where to save. A build skips it until then."], [])
        saves_to = paths.resolve(current["path"], build_root(path))
        info = [
            f"Saves to: {saves_to}",
            *([f"Stored as: {current['path']}"] if current["path"] != saves_to else []),
            f"Format: {format_name(current['path'])}",
            versions.summary(path),
        ]
        return Panel(info, [])


PRODUCT = OutputProduct()
