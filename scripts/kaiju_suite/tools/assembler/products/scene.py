"""Scenes (.ma, .mb): imported as a build step, filled by exporting the selection."""

import os

from maya import cmds

from kaiju_suite.core.undo import undoable
from kaiju_suite.tools.assembler.products import Action, Creator, Product, new_path

EXTENSIONS = (".ma", ".mb")

_SCENE_TYPES = {".ma": "mayaAscii", ".mb": "mayaBinary"}


def _ext(path):
    return os.path.splitext(path)[1].lower()


@undoable
def import_scene(path):
    """Import a scene into the current one, merging namespaces on clash.

    Maya flushes the undo queue on file import, so this can't be undone;
    the chunk still keeps the undo state consistent afterwards.
    """
    if _ext(path) not in EXTENSIONS:
        raise ValueError(f"Not a scene: {os.path.basename(path)}")
    return cmds.file(path, i=True, mergeNamespacesOnClash=True, namespace=":", returnNewNodes=True)


def export_selection(path, overwrite=False):
    """Export the current selection to ``path``; type comes from the extension."""
    file_type = _SCENE_TYPES.get(_ext(path))
    if file_type is None:
        raise ValueError(f"Not a scene: {os.path.basename(path)}")
    if not cmds.ls(selection=True):
        raise RuntimeError("Nothing selected to export.")
    if os.path.exists(path) and not overwrite:
        raise FileExistsError(f"Already exists: {os.path.basename(path)}")
    cmds.file(path, exportSelected=True, type=file_type, force=True)
    return path


def create_scene(directory, name, ext):
    """Create an empty ``.ma``/``.mb`` entry and return its path.

    Fill it later with :func:`export_into`; until then a build skips it.
    """
    if ext not in EXTENSIONS:
        raise ValueError(f"Not a scene extension: {ext}")
    path = new_path(directory, name, ext)
    with open(path, "wb"):
        pass
    return path


def is_empty(path):
    return os.path.getsize(path) == 0


def export_into(path):
    """Replace the scene at ``path`` with the current selection."""
    export_selection(path, overwrite=True)
    return f"Exported selection to {os.path.basename(path)}"


class SceneProduct(Product):
    name = "Scene"
    extensions = EXTENSIONS
    color = (255, 230, 100)
    order = 30
    runnable = True
    creators = (Creator("Scene", create_scene, [("Maya Binary (.mb)", ".mb"), ("Maya Ascii (.ma)", ".ma")]),)

    def run(self, path):
        # An empty entry hasn't been exported into yet: nothing to import.
        if not is_empty(path):
            import_scene(path)

    def actions(self, path):
        confirm = None if is_empty(path) else f"Replace {os.path.basename(path)} with the current selection?"
        return [Action("Export Selected", lambda: export_into(path), confirm)]


PRODUCT = SceneProduct()
