"""Kaiju Scripter item kinds, and how each one runs.

- **Script** (``.py``): run in ``__main__``, like the Script Editor.
- **Folder**, **Separator** (``.sep``) and **Breakpoint** (``.brk``): see
  :mod:`.logic`; they don't run themselves.
- **Joints** (``.jnt``), **Skin** (``.skin``) and **Mesh** (``.mesh``): data
  published from the selection with :mod:`kaiju_suite.datatypes`, and
  applied back when run. Versioned like scripts.
- **Import File** (``.import``) and **Export File** (``.export``): hold one
  path, as ``{"path": ...}``, stored relative to the item's folder when the
  file is inside it (see :mod:`kaiju_suite.core.paths`). Import File imports
  any file Maya can import, into the root namespace; Export File exports
  the selection, overwriting the file. Not versioned.
- **Selection** (``.sel``): a list of entries, as ``{"entries": [...]}``,
  each ``{"type": ..., "value": ...}``: a picked object (its shortest unique
  name, or a component), a name pattern (Maya wildcards, searched on every
  run) or a selection set (its members read on every run). Running it
  replaces the selection with what they find. Not versioned.

No Qt here.
"""

import json
import os

from maya import cmds

from kaiju_suite import datatypes
from kaiju_suite.core import paths
from kaiju_suite.datatypes import joints, mesh, skin
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
}
_KIND_OF_EXT = {ext: kind for kind, ext in EXTENSIONS.items()}

# Data published from the selection, by kind.
DATATYPES = {JOINTS: joints, SKIN: skin, MESH: mesh}
FILE_KINDS = (IMPORT_FILE, EXPORT_FILE)
# What a run runs (breakpoints pause it instead).
RUNNABLE = (SCRIPT, JOINTS, SKIN, MESH, IMPORT_FILE, EXPORT_FILE, SELECTION)

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
    with open(path, encoding="utf-8") as f:
        before = f.read()
    datatypes.write(path, DATATYPES[kind].KIND, payload)
    try:
        return versions.publish(path, description)
    except ValueError:
        with open(path, "w", encoding="utf-8") as f:
            f.write(before)
        raise


def describe(path):
    """Info lines about a data item, e.g. ``["3 joints", "Roots: hip"]``."""
    module = DATATYPES[kind_of(path)]
    return module.describe(datatypes.read(path, module.KIND))


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

PICKED = "picked"
PATTERN = "pattern"
SET = "set"
# How many entries a summary names before "...and N more".
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


def picked_names():
    """The scene selection as picked-entry names: the shortest unique ones."""
    return cmds.ls(selection=True) or []


def add_picked(entries, names):
    """``entries`` with a picked entry added for each of ``names`` not already picked."""
    entries = list(entries)
    taken = {e["value"] for e in entries if e["type"] == PICKED}
    for name in names:
        if name not in taken:
            entries.append({"type": PICKED, "value": name})
            taken.add(name)
    return entries


def entry_label(entry):
    """How an entry reads in a list, e.g. ``body_geo``, ``*_geo``, ``set: render_set``."""
    if entry["type"] == SET:
        return f"set: {entry['value']}"
    return entry["value"]


def summary(entries):
    """One line naming ``entries``, for a tooltip."""
    if not entries:
        return "No entries. Double-click to add some."
    text = ", ".join(entry_label(e) for e in entries[:MAX_SUMMARY])
    if len(entries) > MAX_SUMMARY:
        text += f" ...and {len(entries) - MAX_SUMMARY} more"
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


def find(entry):
    """What ``entry`` finds in the scene now, as shortest unique names.
    Intermediate objects (e.g. a deformed mesh's ``...ShapeOrig``) are left out."""
    kind, value = entry["type"], entry["value"]
    if kind == SET:
        names = _set_members(value, set()) if cmds.objExists(value) else []
    else:
        names = value.split() if kind == PATTERN else [value]
    if not names:
        return []
    try:
        found = cmds.ls(names) or []
    except RuntimeError:
        return []
    nodes = [name for name in found if "." not in name]
    intermediate = set(cmds.ls(nodes, intermediateObjects=True) or []) if nodes else set()
    return [name for name in found if name not in intermediate]


def resolve(entries):
    """``(objects, empty)``: everything ``entries`` find, in entry order and
    without repeats, and the entries that find nothing."""
    objects, empty, seen = [], [], set()
    for entry in entries:
        found = find(entry)
        if not found:
            empty.append(entry)
        for name in found:
            if name not in seen:
                seen.add(name)
                objects.append(name)
    return objects, empty


def select_entries(entries):
    """Replace the selection with what ``entries`` find. Raises, selecting
    nothing new, if there are none or any of them finds nothing."""
    if not entries:
        raise ValueError("This Selection has no entries. Double-click it to add some.")
    objects, empty = resolve(entries)
    if empty:
        raise ValueError("Found nothing for: " + ", ".join(entry_label(e) for e in empty))
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
