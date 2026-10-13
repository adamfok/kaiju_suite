"""Guide (.guide): a guide module's layout, saved as data and built again as
live guides.

The file format and the building are :mod:`kaiju_suite.rigging.guides`;
this is the Assembler step. **New** lists one entry per guide module (e.g.
``Chain Guide``) and writes its default layout. The Type column shows the
guide module's name. Run leaves the guides live, driving their joints, and
stops if they're already in the scene.

Right-click **Mirror** writes the item for the other side (``L_arm`` ->
``R_arm``) right after it, with its layout mirrored by its guide module
(see :meth:`~kaiju_suite.rigging.guides.guide_module.GuideModule.mirrored`),
as that item's next version: run again, it updates the other side's item
instead of adding one. It needs no scene.
"""

import os

from kaiju_suite.core.naming import mirrored_name
from kaiju_suite.rigging import guides
from kaiju_suite.rigging.guides import spec
from kaiju_suite.tools.assembler import data, logic, versions
from kaiju_suite.tools.assembler.products import Action, Creator, is_empty, new_path


def create_guide_module(directory, name, guide_module_key):
    """Create a guide file for ``guide_module_key`` holding its default
    layout, named after the item."""
    path = new_path(directory, name, spec.EXTENSION)
    default = guides.get_guide_module(guide_module_key).default_layout(os.path.splitext(os.path.basename(path))[0])
    return spec.write(path, guide_module_key, default)


def mirror_path(path):
    """Where Mirror writes ``path``'s other side: ``R_arm.guide`` for
    ``L_arm.guide``, ``body_mirrored.guide`` for ``body.guide`` (and back)."""
    directory, name = os.path.split(path)
    stem, ext = os.path.splitext(name)
    return os.path.join(directory, mirrored_name(stem) + ext)


def mirror_problems(path):
    """Why ``path`` can't be mirrored now, as messages."""
    try:
        spec.load(path)
    except (OSError, ValueError, LookupError) as e:
        return [f"Can't read {os.path.basename(path)}: {e}"]
    target = mirror_path(path)
    if os.path.exists(target) and not is_empty(target):
        try:
            spec.read(target)
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
    payload = spec.mirrored(data.read(path, spec.KIND))
    target = mirror_path(path)
    description = f"Mirrored from {os.path.basename(path)}"

    def write(t):
        data.write(t, spec.KIND, payload)
        return t

    if os.path.exists(target):
        return versions.export_into(target, write, description)
    directory = os.path.dirname(path)
    index = logic.item_names(directory).index(os.path.basename(path)) + 1
    create = Creator(PRODUCT.type_name(path), lambda _directory, _name, _ext: write(target))
    logic.create_item(create, directory, os.path.basename(target), None, index)
    return versions.published_message(target, versions.save_version(target, description=description))


class GuideProduct(data.DataProduct):
    name = "Guide"
    utility = "Guide Tool"
    datatype = spec
    order = 38  # just before Joints: guides come first in a build
    menu_slot = (2, 1)

    @property
    def creators(self):
        return tuple(
            Creator(m.name, lambda directory, name, _ext, key=m.key: create_guide_module(directory, name, key))
            for m in guides.all_guide_modules()
        )

    def type_name(self, path):
        """The guide module's name, e.g. ``Chain Guide``; ``Guide`` if the
        file can't be read or names a guide module this Kaiju Suite doesn't
        have."""
        try:
            return spec.load(path)[0].name
        except (OSError, ValueError, LookupError):
            return self.name

    def actions(self, path):
        found = super().actions(path)
        if is_empty(path):
            return found
        try:
            mirrorable = spec.load(path)[0].mirrorable
        except (OSError, ValueError, LookupError):
            mirrorable = True  # offered, and its problems say why it can't
        if not mirrorable:
            return found
        target = os.path.basename(mirror_path(path))
        return found + [
            Action(
                "Mirror",
                lambda: mirror(path),
                tooltip=f"Writes {target} for the other side, its layout mirrored across X, as its next version.",
                problems=lambda: mirror_problems(path),
            )
        ]


PRODUCT = GuideProduct()
