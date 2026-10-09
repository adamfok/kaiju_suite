"""Scenes (.ma, .mb): imported as a build step, filled by exporting the selection.

Right-click Publish exports the selection into the scene as its next version.
Double-clicking a scene opens its panel, which is empty for now.
"""

import os

from maya import cmds

from kaiju_suite.core.undo import undoable
from kaiju_suite.tools.assembler import versions
from kaiju_suite.tools.assembler.products import Action, Creator, Product, ext_of, is_empty, new_path

EXTENSIONS = (".ma", ".mb")

_SCENE_TYPES = {".ma": "mayaAscii", ".mb": "mayaBinary"}


@undoable
def import_scene(path):
    """Import a scene into the current one, merging namespaces on clash.

    Maya flushes the undo queue on file import, so this can't be undone;
    the chunk still keeps the undo state consistent afterwards.
    """
    if ext_of(path) not in EXTENSIONS:
        raise ValueError(f"Not a scene: {os.path.basename(path)}")
    return cmds.file(path, i=True, mergeNamespacesOnClash=True, namespace=":", returnNewNodes=True)


def export_selection(path, overwrite=False):
    """Export the current selection to ``path``; type comes from the extension."""
    file_type = _SCENE_TYPES.get(ext_of(path))
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


def export_into(path):
    """Replace the scene at ``path`` with the current selection and save
    the result as its next version.

    Old content not yet in the history (a scene from before versioning) is
    saved as a version first, so nothing is lost.
    """
    if not cmds.ls(selection=True):
        raise RuntimeError("Nothing selected to export.")
    return versions.export_into(path, lambda target: export_selection(target, overwrite=True))


class SceneProduct(Product):
    name = "Scene"
    utility = "Scene Tool"
    extensions = EXTENSIONS
    order = 30
    menu_slot = None  # not in the New menu for now
    runnable = True
    versioned = True
    creators = (Creator("Scene", create_scene, [("Maya Binary (.mb)", ".mb"), ("Maya Ascii (.ma)", ".ma")]),)

    def run(self, path):
        # An empty entry hasn't been exported into yet: nothing to import.
        if not is_empty(path):
            import_scene(path)

    def publish(self, path):
        # No question first: the content it replaces is kept as a version.
        return Action("Publish", lambda: export_into(path))

    def publish_problems(self, path):
        if not cmds.ls(selection=True):
            return [f"Nothing selected. Select what to publish into {os.path.basename(path)}."]
        return []


PRODUCT = SceneProduct()
