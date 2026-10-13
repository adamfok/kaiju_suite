"""Guide (.guide): Guide Tool chains saved as data and built again as live
guides.

The saving and building are :mod:`kaiju_suite.datatypes.guides`; this is
the Assembler step. Run leaves the guides live, driving their joints, and
stops if a chain's guides are already in the scene.

Right-click **Mirror** writes the item for the other side (``L_arm`` ->
``R_arm``) right after it, every chain mirrored across X with its joints
Behavior mirrored (see :func:`kaiju_suite.datatypes.guides.mirrored`), as
that item's next version: run again, it updates the other side's item
instead of adding one. It needs no scene.
"""

import os

from kaiju_suite.core.naming import mirrored_name
from kaiju_suite.datatypes import guides
from kaiju_suite.tools.assembler import data, logic, versions
from kaiju_suite.tools.assembler.products import Action, Creator, is_empty


def mirror_path(path):
    """Where Mirror writes ``path``'s other side: ``R_arm.guide`` for
    ``L_arm.guide``, ``body_mirrored.guide`` for ``body.guide`` (and back)."""
    directory, name = os.path.split(path)
    stem, ext = os.path.splitext(name)
    return os.path.join(directory, mirrored_name(stem) + ext)


def mirror_problems(path):
    """Why ``path`` can't be mirrored now, as messages."""
    try:
        data.read(path, guides.KIND)
    except (OSError, ValueError) as e:
        return [f"Can't read {os.path.basename(path)}: {e}"]
    target = mirror_path(path)
    if os.path.exists(target) and not is_empty(target):
        try:
            data.read(target, guides.KIND)
        except (OSError, ValueError):
            name = os.path.basename(target)
            return [f"{name} isn't a Guide item, so Mirror won't overwrite it. Rename or delete it first."]
    return []


def mirror(path):
    """Write ``path``'s other side (see :func:`mirror_path`) as that item's
    next version: a new item right after ``path``, or a new version of the
    one that is there. Returns a message."""
    problems = mirror_problems(path)
    if problems:
        raise ValueError("Can't mirror:\n" + "\n".join(f"- {p}" for p in problems))
    payload = guides.mirrored(data.read(path, guides.KIND))
    target = mirror_path(path)
    description = f"Mirrored from {os.path.basename(path)}"

    def write(t):
        data.write(t, guides.KIND, payload)
        return t

    if os.path.exists(target):
        return versions.export_into(target, write, description)
    directory = os.path.dirname(path)
    index = logic.item_names(directory).index(os.path.basename(path)) + 1
    create = Creator(GuideProduct.name, lambda _directory, _name, _ext: write(target))
    logic.create_item(create, directory, os.path.basename(target), None, index)
    return versions.published_message(target, versions.save_version(target, description=description))


class GuideProduct(data.DataProduct):
    name = "Guide"
    utility = "Guide Tool"
    datatype = guides
    order = 38  # just before Joints: guides come first in a build
    menu_slot = (2, 1)

    def actions(self, path):
        found = super().actions(path)
        if is_empty(path):
            return found
        target = os.path.basename(mirror_path(path))
        return found + [
            Action(
                "Mirror",
                lambda: mirror(path),
                tooltip=f"Writes {target} for the other side: every chain mirrored across X, "
                "its joints Behavior mirrored, as its next version.",
                problems=lambda: mirror_problems(path),
            )
        ]


PRODUCT = GuideProduct()
