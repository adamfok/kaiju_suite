"""Guides to Joints (.guidestojoints): empty files that, when run, delete
every guide in the scene and extract their joints.

Put one after the Guide items, before the steps that need plain joints.
Their joints stay where they are, cut loose and unlocked, with plain
translate and joint orient values, as the Guide Module Editor's Delete
leaves them (see
:func:`~kaiju_suite.rigging.guide_module.delete_all_guides`).
If any guides are broken, it fails before deleting anything. Like
a New Scene item, it holds nothing, so it isn't versioned.
"""

from kaiju_suite.rigging.guide_module import delete_all_guides
from kaiju_suite.tools.assembler import data, runlog
from kaiju_suite.tools.assembler.products import Creator, Product, new_path

EXTENSION = ".guidestojoints"


def create_guides_to_joints(directory, name):
    """Create an empty Guides to Joints item named ``name`` and return its path."""
    path = new_path(directory, name, EXTENSION)
    with open(path, "w", encoding="utf-8"):
        pass
    return path


class GuidesToJointsProduct(Product):
    name = "Guides to Joints"
    extensions = (EXTENSION,)
    order = 39  # between Guide and Joints
    menu_slot = (2, 1)  # with Guide and Joints
    runnable = True
    creators = (
        Creator("Guides to Joints", lambda directory, name, _ext: create_guides_to_joints(directory, name)),
    )

    def run(self, path):
        extracted = delete_all_guides()
        if not extracted:
            runlog.warning("No guides in the scene: nothing to extract.")
            return None
        for name, joints in extracted.items():
            runlog.info(f"{name}: {data.plural(len(joints), 'joint')} extracted")
        return f"Guides deleted; joints of {data.plural(len(extracted), 'guide module')} extracted."


PRODUCT = GuidesToJointsProduct()
