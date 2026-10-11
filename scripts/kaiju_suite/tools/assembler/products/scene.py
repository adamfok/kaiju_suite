"""Scenes (.scene): point to a Maya file (.ma, .mb) that a build imports.

The entry holds only the file's path, as JSON (``{"path": ...}``); the
Maya file itself stays where it is. Right-click Publish opens a file
browser and saves the picked file as the entry's next version, so
Versions can point it back to an earlier file. Double-clicking a scene,
or right-click Info, shows the path.

The path is stored portably (see :mod:`kaiju_suite.core.paths`):
relative to the entry's build folder (the folder holding the ``.scene``
file) when the Maya file is inside it, else as ``$ASSET/...`` when it's
under the ``ASSET`` environment variable's folder, else absolute.
Entries written before that hold absolute paths, which still work.
"""

import json
import os

from maya import cmds

from kaiju_suite.core import paths
from kaiju_suite.core.undo import undoable
from kaiju_suite.tools.assembler import versions
from kaiju_suite.tools.assembler.products import Action, Creator, Panel, Product, ext_of, is_empty, new_path

EXTENSION = ".scene"

# What a scene can point to.
MAYA_EXTENSIONS = (".ma", ".mb")

_FILE_FILTER = "Maya Scenes (*.ma *.mb);;Maya ASCII (*.ma);;Maya Binary (*.mb)"


@undoable
def import_scene(path):
    """Import a Maya file into the current scene, merging namespaces on clash.

    Maya flushes the undo queue on file import, so this can't be undone;
    the chunk still keeps the undo state consistent afterwards.
    """
    if ext_of(path) not in MAYA_EXTENSIONS:
        raise ValueError(f"Not a Maya scene: {os.path.basename(path)}")
    return cmds.file(path, i=True, mergeNamespacesOnClash=True, namespace=":", returnNewNodes=True)


def create_scene(directory, name):
    """Create an empty ``.scene`` entry and return its path.

    Point it at a file later with :func:`point_to`; until then a build skips it.
    """
    path = new_path(directory, name, EXTENSION)
    with open(path, "wb"):
        pass
    return path


def build_root(path):
    """The build folder that relative paths in the entry at ``path`` are
    relative to: the folder holding the entry."""
    return os.path.dirname(os.path.abspath(path))


def target(path):
    """The Maya file the entry at ``path`` points to, as an absolute path
    (unless it uses a variable that isn't set), or ``None`` if it's empty."""
    text = stored(path)
    return None if text is None else paths.resolve(text, build_root(path))


def stored(path):
    """The path text as saved in the entry at ``path`` (maybe relative or
    with a variable), or ``None`` if it's empty."""
    if is_empty(path):
        return None
    with open(path, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except ValueError:
            data = None
    if not isinstance(data, dict) or not data.get("path"):
        raise ValueError(f"Not a scene entry: {os.path.basename(path)}")
    return data["path"]


def point_to(path, maya_file):
    """Point the entry at ``path`` to ``maya_file`` and save that as its next
    version. Returns a message, e.g. ``Published Scene hero.scene v002``."""
    if ext_of(maya_file) not in MAYA_EXTENSIONS:
        raise ValueError(f"Not a Maya scene: {os.path.basename(maya_file)}")
    root = build_root(path)
    if not os.path.isfile(paths.resolve(maya_file, root)):
        raise FileNotFoundError(f"File not found: {maya_file}")
    text = paths.to_portable(maya_file, root)

    return versions.export_into(path, lambda entry: _write_entry(entry, text))


def _write_entry(entry, maya_file):
    """Write the entry at ``entry`` pointing to ``maya_file``, stored as given."""
    with open(entry, "w", encoding="utf-8") as f:
        json.dump({"path": maya_file}, f, indent=2)


def pick_scene_file(start_dir):
    """Ask for a Maya file with a file browser opened in ``start_dir``.
    Returns its path, or ``None`` if cancelled. GUI Maya only."""
    picked = cmds.fileDialog2(
        caption="Publish Scene",
        fileMode=1,
        fileFilter=_FILE_FILTER,
        dialogStyle=2,
        startingDirectory=start_dir,
    )
    return picked[0] if picked else None


def _start_dir(path):
    """Where the browser opens: the current file's folder if it still
    exists, else the entry's own folder."""
    try:
        current = target(path)
    except ValueError:
        current = None
    if current and os.path.isdir(os.path.dirname(current)):
        return os.path.dirname(current)
    return os.path.dirname(path)


def publish_from_browser(path):
    """Pick a Maya file and point the entry at it. Returns ``None`` (no
    message) if the browser is cancelled."""
    picked = pick_scene_file(_start_dir(path))
    if not picked:
        return None
    return point_to(path, picked)


class SceneProduct(Product):
    name = "Scene"
    extensions = (EXTENSION,)
    order = 30
    menu_slot = (0, 1)  # with Script, just after it: no divider between them
    runnable = True
    versioned = True
    creators = (Creator("Scene", lambda directory, name, _ext: create_scene(directory, name)),)

    def run(self, path):
        maya_file = target(path)
        # An empty entry hasn't been pointed at a file yet: nothing to import.
        if maya_file is None:
            return
        if not os.path.isfile(maya_file):
            text = stored(path)
            shown = maya_file if text == maya_file else f"{text} ({maya_file})"
            raise FileNotFoundError(f"{os.path.basename(path)} points to a file that doesn't exist: {shown}")
        import_scene(maya_file)

    def publish(self, path):
        # No question first: the path it replaces is kept as a version.
        return Action("Publish", lambda: publish_from_browser(path))

    def to_plan(self, path):
        # The stored text, so a relative path stays relative to the folder
        # the plan is imported into.
        text = stored(path)
        return {} if text is None else {"path": text}

    def plan_problems(self, item):
        if "path" in item and not isinstance(item["path"], str):
            return [f"path must be text, not {item['path']!r}"]
        return []

    def from_plan(self, path, item):
        if item.get("path"):
            _write_entry(path, item["path"])
        else:
            super().from_plan(path, item)

    def panel(self, path):
        try:
            maya_file = target(path)
        except ValueError as e:
            return Panel([str(e)], [])
        if maya_file is None:
            return Panel(["Not published yet: points to no file."], [])
        info = [f"Points to: {maya_file}", versions.summary(path)]
        text = stored(path)
        if text != maya_file:
            info.insert(1, f"Stored as: {text}")
        if not os.path.isfile(maya_file):
            info.insert(1, "File not found: a build will stop here.")
        return Panel(info, [])


PRODUCT = SceneProduct()
