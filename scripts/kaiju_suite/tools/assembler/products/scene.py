"""Scenes (.ma, .mb): imported as a build step, made by exporting the selection."""

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
    """Export the selection to a new ``.ma``/``.mb`` file and return its path."""
    if ext not in EXTENSIONS:
        raise ValueError(f"Not a scene extension: {ext}")
    return export_selection(new_path(directory, name, ext))


def _import(path):
    import_scene(path)
    return f"Imported {os.path.basename(path)}"


class SceneProduct(Product):
    name = "Scene"
    extensions = EXTENSIONS
    color = (255, 230, 100)
    order = 20
    runnable = True
    creators = (Creator("Export Selected...", create_scene, [("Maya Binary (.mb)", ".mb"), ("Maya Ascii (.ma)", ".ma")]),)

    def run(self, path):
        import_scene(path)

    def actions(self, path):
        return [Action("Import Scene", lambda: _import(path))]


PRODUCT = SceneProduct()
