"""Kaiju Scripter item kinds, and how each one runs.

- **Script** (``.py``): run in ``__main__``, like the Script Editor.
- **Folder**, **Separator** (``.sep``) and **Breakpoint** (``.brk``): see
  :mod:`.logic`; they don't run themselves.
- **Joints** (``.jnt``), **Skin** (``.skin``) and **Mesh** (``.mesh``): data
  published from the selection with :mod:`kaiju_suite.datatypes`, and
  applied back when run. Versioned like scripts. A kind with a tool in
  :data:`TOOLS` opens it on double-click, with the item's objects selected
  (:func:`open_in_tool`).
- **Import File** (``.import``) and **Export File** (``.export``): hold one
  path, as ``{"path": ...}``, stored relative to the item's folder when the
  file is inside it (see :mod:`kaiju_suite.core.paths`). Import File imports
  any file Maya can import, into the root namespace; Export File exports
  the selection, overwriting the file. Not versioned.
- **Pose** (``.pose``): the values of the selected nodes' keyable attributes,
  published and run like Joints, set back with ``setAttr`` (no keys);
  opens the Pose Tool on double-click.
- **Selection** (``.sel``): a list of entries, as ``{"entries": [...]}``,
  each ``{"type": ..., "value": ...}``: selected objects (a list of their
  shortest unique names, or components), a name pattern (Maya wildcards, searched on every
  run) or a selection set (its members read on every run). Running it
  replaces the selection with what they find. Not versioned.

No Qt here.
"""

import json
import os
import tempfile

from maya import cmds

from kaiju_suite import datatypes, registry
from kaiju_suite.core import paths
from kaiju_suite.core.undo import undoable
from kaiju_suite.datatypes import joints, mesh, pose, skin
from kaiju_suite.tools.scripter import versions

SCRIPT = "Script"
FOLDER = "Folder"
SEPARATOR = "Separator"
BREAKPOINT = "Breakpoint"
JOINTS = "Joints"
SKIN = "Skin"
MESH = "Mesh"
IMPORT_FILE = "Import File"
EXPORT_FILE = "Export File"
SELECTION = "Selection"
POSE = "Pose"

EXTENSIONS = {
    SCRIPT: ".py",
    SEPARATOR: ".sep",
    BREAKPOINT: ".brk",
    JOINTS: joints.EXTENSION,
    SKIN: skin.EXTENSION,
    MESH: mesh.EXTENSION,
    IMPORT_FILE: ".import",
    EXPORT_FILE: ".export",
    SELECTION: ".sel",
    POSE: pose.EXTENSION,
}
_KIND_OF_EXT = {ext: kind for kind, ext in EXTENSIONS.items()}

# Data published from the selection, by kind.
DATATYPES = {JOINTS: joints, SKIN: skin, MESH: mesh, POSE: pose}
# The tool each data kind opens on double-click, by its registry name.
TOOLS = {SKIN: "SkinCluster Tool", JOINTS: "Joint Tool", MESH: "Mesh Tool", POSE: "Pose Tool"}
FILE_KINDS = (IMPORT_FILE, EXPORT_FILE)
# What a run runs (breakpoints pause it instead).
RUNNABLE = (SCRIPT, JOINTS, SKIN, MESH, IMPORT_FILE, EXPORT_FILE, SELECTION, POSE)

# Export File formats by extension: (plug-in it needs or None, Maya file type).
EXPORT_FORMATS = {
    ".ma": (None, "mayaAscii"),
    ".mb": (None, "mayaBinary"),
    ".fbx": ("fbxmaya", "FBX export"),
    ".obj": ("objExport", "OBJexport"),
}
# Import File formats that need a plug-in loaded first; anything else is up to Maya.
IMPORT_PLUGINS = {".fbx": "fbxmaya", ".obj": "objExport", ".abc": "AbcImport"}


def kind_of(path):
    """The item kind of ``path``, or ``None`` if Kaiju Scripter doesn't show it."""
    if os.path.isdir(path):
        return FOLDER
    return _KIND_OF_EXT.get(os.path.splitext(path)[1].lower())


def run(path):
    """Run the item at ``path`` by its kind."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File not found: {path}")
    kind = kind_of(path)
    if kind == SCRIPT:
        run_script(path)
    elif kind in DATATYPES:
        datatypes.load(DATATYPES[kind], path)
    elif kind == IMPORT_FILE:
        import_file(target(path))
    elif kind == EXPORT_FILE:
        export_selected(target(path))
    elif kind == SELECTION:
        select_entries(read_entries(path))
    else:
        raise ValueError(f"Not something Kaiju Scripter runs: {os.path.basename(path)}")


def run_script(path):
    """Run a script file in ``__main__``, as the Script Editor does, with
    ``__file__`` set to it while it runs."""
    import __main__

    with open(path, encoding="utf-8") as f:
        code = f.read()
    namespace = __main__.__dict__
    missing = object()
    before = namespace.get("__file__", missing)
    namespace["__file__"] = path
    try:
        exec(compile(code, path, "exec"), namespace)
    finally:
        if before is missing:
            namespace.pop("__file__", None)
        else:
            namespace["__file__"] = before


# -- Joints, Skin, Mesh -----------------------------------------------------


def selection_problems(kind, selection):
    """Why ``selection`` (long names) can't be published as a ``kind`` item."""
    return DATATYPES[kind].selection_problems(selection)


def write_data(kind, path, selection):
    """Gather ``selection`` and write it to ``path``. Raises, writing
    nothing, if the selection can't be gathered."""
    problems = selection_problems(kind, selection)
    if problems:
        raise ValueError(" ".join(problems))
    datatypes.save(DATATYPES[kind], path, selection)


def publish_data(path, selection, description=""):
    """Gather ``selection`` into the data item at ``path`` and publish it
    as its next version. Returns the version number. Raises if the
    selection can't be gathered, or if nothing changed."""
    kind = kind_of(path)
    problems = selection_problems(kind, selection)
    if problems:
        raise ValueError(" ".join(problems))
    payload = DATATYPES[kind].gather(selection)
    # As bytes: putting it back must not change its line endings, or it reads as edited.
    with open(path, "rb") as f:
        before = f.read()
    datatypes.write(path, DATATYPES[kind].KIND, payload)
    try:
        return versions.publish(path, description)
    except ValueError:
        with open(path, "wb") as f:
            f.write(before)
        raise


def unchanged_since(path, selection):
    """The number of the version the data item at ``path`` is at, if
    publishing ``selection`` (long names) would save the same data; otherwise
    ``None``. Writes nothing next to the item. Raises if the selection can't
    be gathered."""
    module = DATATYPES[kind_of(path)]
    payload = module.gather(selection)
    with tempfile.TemporaryDirectory() as scratch:
        draft = datatypes.write(os.path.join(scratch, os.path.basename(path)), module.KIND, payload)
        with open(draft, "rb") as f:
            return versions.unchanged_since(path, f.read())


def publish_qc(path, objects):
    """Run the QC checks of the data item at ``path``'s kind on ``objects``
    (long names), with the settings saved in its tool, leaving out checks
    not meant for publishing. ``(check, problems)`` pairs; empty for kinds
    without checks."""
    return datatypes.run_qc(DATATYPES[kind_of(path)], objects, publish=True)


def describe(path):
    """Info lines about a data item, e.g. ``["3 joints", "Roots: hip"]``."""
    module = DATATYPES[kind_of(path)]
    return module.describe(datatypes.read(path, module.KIND))


def saved_objects(path):
    """``(paths, problems)``: the long paths of the objects the data item at
    ``path`` was published from, and messages naming the ones missing from
    the scene or matching several nodes. Publishing ``paths`` updates the
    item from the same objects."""
    module = DATATYPES[kind_of(path)]
    return datatypes.resolve_nodes(module.nodes(datatypes.read(path, module.KIND)))


def select_saved(path):
    """Select the objects the data item at ``path`` was published from.
    Returns a message that names the ones it couldn't find, and warns about them."""
    found, problems = saved_objects(path)
    if found:
        cmds.select(found, replace=True)
    else:
        cmds.select(clear=True)
    message = f"Selected {datatypes.plural(len(found), 'object')} from {os.path.basename(path)}"
    if problems:
        cmds.warning(" ".join(problems))
        message += ". " + " ".join(problems)
    return message


def tool_for(kind):
    """The name of the tool a ``kind`` item opens on double-click, or ``None``."""
    return TOOLS.get(kind)


def open_in_tool(path):
    """Select the objects the data item at ``path`` was published from (see
    :func:`select_saved`), then open its kind's tool, which works on the
    selection. Returns :func:`select_saved`'s message. Raises
    ``LookupError`` if the tool isn't installed."""
    name = tool_for(kind_of(path))
    tool = registry.find(name) if name else None
    if tool is None:
        raise LookupError(f"Can't find the {name or 'tool'} for {os.path.basename(path)}.")
    message = select_saved(path)
    tool["launch"]()
    return message


# -- Import File, Export File -----------------------------------------------


def check_target(kind, target_path):
    """Raise if ``target_path`` can't be the file of a ``kind`` item."""
    if kind == EXPORT_FILE:
        ext = os.path.splitext(target_path)[1].lower()
        if ext not in EXPORT_FORMATS:
            raise ValueError(
                f"Can't export {ext or 'files without an extension'}: use one of {', '.join(EXPORT_FORMATS)}."
            )


def set_target(path, target_path):
    """Point the Import or Export File item at ``path`` to ``target_path``."""
    check_target(kind_of(path), target_path)
    stored = paths.to_portable(target_path, os.path.dirname(os.path.abspath(path)))
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"path": stored}, f, indent=2)


def target(path):
    """The file the Import or Export File item at ``path`` points to."""
    try:
        with open(path, encoding="utf-8") as f:
            stored = json.load(f)["path"]
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError(f"{os.path.basename(path)} has no file set. Double-click it to pick one.") from None
    return os.path.normpath(paths.resolve(stored, os.path.dirname(os.path.abspath(path))))


def _load_plugin(name):
    if cmds.pluginInfo(name, query=True, loaded=True):
        return
    try:
        cmds.loadPlugin(name, quiet=True)
    except RuntimeError as e:
        raise RuntimeError(f"The {name} plug-in didn't load ({e}).") from e


def import_file(file_path):
    """Import ``file_path`` with Maya's importer, into the root namespace."""
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    plugin = IMPORT_PLUGINS.get(os.path.splitext(file_path)[1].lower())
    if plugin:
        _load_plugin(plugin)
    return cmds.file(file_path, i=True, mergeNamespacesOnClash=True, namespace=":", returnNewNodes=True)


def export_selected(file_path):
    """Export the selection to ``file_path`` in the format its extension
    names, creating its folder and overwriting the file."""
    check_target(EXPORT_FILE, file_path)
    if not cmds.ls(selection=True):
        raise RuntimeError("Nothing selected to export.")
    plugin, file_type = EXPORT_FORMATS[os.path.splitext(file_path)[1].lower()]
    if plugin:
        _load_plugin(plugin)
    os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
    cmds.file(file_path, exportSelected=True, type=file_type, force=True)
    return file_path


# -- Selection --------------------------------------------------------------

SELECTED = "selected"
PATTERN = "pattern"
SET = "set"
# What a pattern entry's "node_type" can be; "*" (or none) is any node.
# Geo, Nurbs Curve, Nurbs Surface and Locator find transforms with that shape.
ANY_TYPE = "*"
_SHAPE_TYPES = {"Geo": "mesh", "Nurbs Curve": "nurbsCurve", "Nurbs Surface": "nurbsSurface", "Locator": "locator"}
NODE_TYPES = (ANY_TYPE, "Transform", "Joint", *_SHAPE_TYPES, "Constraint")
# How many names a summary lists before "...and N more".
MAX_SUMMARY = 10


def read_entries(path):
    """The entries of the Selection item at ``path``; ``[]`` for a new, empty file."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if not text.strip():
        return []
    try:
        return list(json.loads(text)["entries"])
    except (ValueError, KeyError, TypeError):
        raise ValueError(f"{os.path.basename(path)} isn't a valid Selection item.") from None


def write_entries(path, entries):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"entries": list(entries)}, f, indent=2)


def selected_names():
    """The scene selection as a Selected entry saves it: the shortest unique names."""
    return cmds.ls(selection=True) or []


def add_selected(entries, names):
    """``entries`` with one Selected entry added holding ``names`` (each
    once); unchanged when there are none."""
    names = list(dict.fromkeys(names))
    return list(entries) + ([{"type": SELECTED, "value": names}] if names else [])


def _names(entry):
    """What an entry lists by name: its objects, patterns or set."""
    if entry["type"] == SELECTED:
        return list(entry["value"])
    if entry["type"] == SET:
        return [f"set: {entry['value']}"]
    node_type = entry.get("node_type", ANY_TYPE)
    return [entry["value"] if node_type == ANY_TYPE else f"{entry['value']} ({node_type})"]


def entry_label(entry):
    """How an entry reads in a list, e.g. ``body_geo, hair_geo``, ``*_geo``, ``set: render_set``."""
    return ", ".join(_names(entry))


def summary(entries):
    """One line naming what ``entries`` hold, for a tooltip."""
    if not entries:
        return "No entries. Double-click to add some."
    names = [name for entry in entries for name in _names(entry)]
    text = ", ".join(names[:MAX_SUMMARY])
    if len(names) > MAX_SUMMARY:
        text += f" ...and {len(names) - MAX_SUMMARY} more"
    return text


def _set_members(name, seen):
    if name in seen or cmds.nodeType(name) not in ("objectSet",):
        return []
    seen.add(name)
    found = []
    for member in cmds.sets(name, query=True) or []:
        if "." not in member and cmds.nodeType(member) == "objectSet":
            found.extend(_set_members(member, seen))
        else:
            found.append(member)
    return found


def _ls(names):
    """``names`` as they are in the scene now, leaving out intermediate objects."""
    if not names:
        return []
    try:
        found = cmds.ls(names) or []
    except RuntimeError:
        return []
    nodes = [name for name in found if "." not in name]
    intermediate = set(cmds.ls(nodes, intermediateObjects=True) or []) if nodes else set()
    return [name for name in found if name not in intermediate]


def lookup(entry):
    """``(found, missing)`` for ``entry``: what it finds in the scene now, and
    what it can't find (a Selected entry's missing objects, or the entry's
    label when it finds nothing)."""
    kind, value = entry["type"], entry["value"]
    if kind == SELECTED:
        found, missing = [], []
        for name in value:
            here = _ls([name])
            found.extend(here)
            if not here:
                missing.append(name)
        return found, missing
    if kind == SET:
        found = _ls(_set_members(value, set()) if cmds.objExists(value) else [])
    else:
        found = _of_type(_ls(value.split()), entry.get("node_type", ANY_TYPE))
    return found, ([] if found else [entry_label(entry)])


def _of_type(found, node_type):
    """The nodes in ``found`` of ``node_type`` (one of :data:`NODE_TYPES`), in order."""
    if node_type == ANY_TYPE:
        return found
    nodes = [name for name in found if "." not in name]
    if not nodes:
        return []
    if node_type == "Transform":
        keep = cmds.ls(nodes, exactType="transform")
    elif node_type == "Joint":
        keep = cmds.ls(nodes, type="joint")
    elif node_type == "Constraint":
        keep = cmds.ls(nodes, type="constraint")
    elif node_type in _SHAPE_TYPES:
        shape = _SHAPE_TYPES[node_type]
        keep = [
            name
            for name in cmds.ls(nodes, type="transform")
            if cmds.listRelatives(name, shapes=True, noIntermediate=True, type=shape)
        ]
    else:
        raise ValueError(f"Unknown node type: {node_type}")
    keep = set(keep or [])
    return [name for name in nodes if name in keep]


def find(entry):
    """What ``entry`` finds in the scene now, as shortest unique names.
    Intermediate objects (e.g. a deformed mesh's ``...ShapeOrig``) are left out."""
    return lookup(entry)[0]


def missing(entry):
    """What ``entry`` can't find in the scene now (see :func:`lookup`)."""
    return lookup(entry)[1]


def resolve(entries):
    """``(objects, missing)``: everything ``entries`` find, in entry order and
    without repeats, and what they can't find."""
    objects, missed = [], []
    for entry in entries:
        found, gone = lookup(entry)
        objects.extend(found)
        missed.extend(gone)
    return list(dict.fromkeys(objects)), missed


def select_entries(entries):
    """Replace the selection with what ``entries`` find. Raises, selecting
    nothing new, if there are none or anything is missing."""
    if not entries:
        raise ValueError("This Selection has no entries. Double-click it to add some.")
    objects, missed = resolve(entries)
    if missed:
        raise ValueError("Found nothing for: " + ", ".join(missed))
    cmds.select(objects, replace=True)
    return objects


def scene_sets():
    """The scene's selection sets, by name: not shading groups, deformer sets
    or Maya's default sets."""
    found = []
    for name in cmds.ls(exactType="objectSet") or []:
        if name in ("defaultLightSet", "defaultObjectSet") or cmds.listConnections(f"{name}.usedBy"):
            continue
        found.append(name)
    return sorted(found)


@undoable
def create_set(name, members):
    """Make a selection set named ``name`` holding ``members``, as one undo
    step. Returns its name, which Maya changes if ``name`` is taken."""
    name = name.strip()
    if not name:
        raise ValueError("Please provide a name for the set.")
    if not members:
        raise ValueError("Nothing selected to make a set from.")
    return cmds.sets(members, name=name)


@undoable
def delete_set(name):
    """Delete the selection set ``name`` (not its members), as one undo step."""
    if name not in scene_sets():
        raise ValueError(f"Not a selection set: {name}")
    cmds.delete(name)
