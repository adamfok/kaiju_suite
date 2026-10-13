"""New Scenes (.newscene): empty files that start a fresh, empty scene when run.

Put one first in a build so it doesn't build on top of what's open. It
doesn't ask to save the open scene: unsaved changes are lost. Like a
Separator, it holds nothing, so it isn't versioned.
"""

from maya import cmds

from kaiju_suite.tools.assembler.products import Creator, Product, new_path

EXTENSION = ".newscene"


def create_new_scene(directory, name):
    """Create an empty New Scene item named ``name`` and return its path.
    The New menu always names it ``new``."""
    path = new_path(directory, name, EXTENSION)
    with open(path, "w", encoding="utf-8"):
        pass
    return path


class NewSceneProduct(Product):
    name = "New Scene"
    extensions = (EXTENSION,)
    order = 32
    menu_slot = (0, 2)  # with Script and Import Scene
    runnable = True
    creators = (
        Creator("New Scene", lambda directory, name, _ext: create_new_scene(directory, name), fixed_name="new"),
    )

    def run(self, path):
        # Maya flushes undo on a new scene, so the build can't be undone past it.
        cmds.file(new=True, force=True)


PRODUCT = NewSceneProduct()
