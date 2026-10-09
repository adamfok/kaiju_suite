"""Scenes (.ma, .mb): imported as a build step, filled by exporting the selection.

Double-clicking a scene opens its panel, which holds Export Selected.
"""

import os
import time

from maya import cmds

from kaiju_suite.core.undo import undoable
from kaiju_suite.tools.assembler import versions
from kaiju_suite.tools.assembler.products import Action, Creator, Panel, Product, new_path

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
    """Replace the scene at ``path`` with the current selection and save
    the result as its next version.

    Old content not yet in the history (a scene from before versioning) is
    saved as a version first, so nothing is lost.
    """
    if cmds.ls(selection=True):
        versions.save_version(path)
    export_selection(path, overwrite=True)
    versions.save_version(path)
    return f"Exported selection to {os.path.basename(path)}"


class SceneProduct(Product):
    name = "Scene"
    extensions = EXTENSIONS
    order = 30
    runnable = True
    versioned = True
    creators = (Creator("Scene", create_scene, [("Maya Binary (.mb)", ".mb"), ("Maya Ascii (.ma)", ".ma")]),)

    def run(self, path):
        # An empty entry hasn't been exported into yet: nothing to import.
        if not is_empty(path):
            import_scene(path)

    def panel(self, path):
        if is_empty(path):
            info = ["Empty. Select something in Maya, then Export Selected.", "Run All skips it until then."]
            confirm = None
        else:
            saved = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(path)))
            info = [f"{os.path.getsize(path) / 1024:.1f} KB, saved {saved}", versions.summary(path)]
            confirm = (
                f"Replace {os.path.basename(path)} with the current selection?"
                " Its current content stays in Versions."
            )
        return Panel(info, [Action("Export Selected", lambda: export_into(path), confirm)])


PRODUCT = SceneProduct()
