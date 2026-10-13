"""Guide Module Editor: one guide module file, and its guides in the scene. No Qt here.

The editor opens an Assembler Guide item (a ``.guide`` file) and tracks the
guides in the scene that it describes. Its unsaved edits are the guides
themselves: **Save** writes their layout back to the file, and **Revert**
puts them back as the file has them. Guide modules and their files are
:mod:`kaiju_suite.rigging.guide_module`; the planar chains a Chain is made of are
:mod:`kaiju_suite.rigging.guide_module.planar_chain`. Each function here that
changes the scene is one undo step.
"""

import os

from maya import cmds

from kaiju_suite.core.undo import undoable
from kaiju_suite.rigging.guide_module import planar_chain as _planar_chain
from kaiju_suite.rigging.guide_module import spec as _spec
from kaiju_suite.rigging.guide_module.guide_module import tag as _tag
from kaiju_suite.rigging.guide_module.modules import chain as _chain
from kaiju_suite.rigging.guide_module.planar_chain import (  # noqa: F401 (re-exported for the editor and its tests)
    NAME,
    display_curves,
    find_group,
    free_joint,
    guide_group,
    guides,
    joints,
    planar_positions,
    plane,
    previews,
)

# The planar chain's own edits, each one undo step.
build_guides = undoable(_planar_chain.build_guides)
guides_from_joints = undoable(_planar_chain.guides_from_joints)
set_axes = undoable(_planar_chain.set_axes)
delete_guides = undoable(_planar_chain.delete_guides)


# -- the file -------------------------------------------------------------------


def load(path):
    """``(guide_module, layout)`` for the Guide item at ``path``. Raises
    ``ValueError`` if it's empty or isn't a guide file, and ``LookupError``
    for a guide module this Kaiju Suite doesn't have."""
    if os.path.getsize(path) == 0:
        raise ValueError(f"{os.path.basename(path)} is empty. Publish guides into it from the Assembler first.")
    return _spec.load(path)


def fields(guide_module, layout):
    """What the editor's form shows for ``layout`` (for a Chain: ``{"name",
    "count", "aim", "up"}``), or ``None`` for a guide module with no form."""
    return guide_module.fields(layout) if hasattr(guide_module, "fields") else None


def save(path, guide_module, group):
    """Write the layout of the guides under ``group``, as they are now, to
    ``path``, and return it."""
    layout = guide_module.layout(group)
    _spec.write(path, guide_module.key, layout)
    return layout


def unsaved(guide_module, group, layout):
    """Whether the guides under ``group`` differ from ``layout``."""
    return guide_module.layout(group) != layout


# -- the guides in the scene ------------------------------------------------------


def find_guides(guide_module, layout):
    """The top group of ``layout``'s guides in the scene, found by its
    name, or ``None``."""
    found = [n for n in guide_module.nodes(layout) if cmds.objExists(n)]
    if not found:
        return None
    try:
        module, group = _spec.find_group(found[:1])
    except ValueError:
        return None
    return group if module is guide_module else None


def pick_guides(guide_module, nodes):
    """The top group of the guides ``nodes`` (e.g. the selection) belong to.
    Raises ``ValueError`` if they belong to no guides, or to another guide
    module's."""
    module, group = _spec.find_group(nodes)
    if module is not guide_module:
        raise ValueError(f"Those are {module.name} guides; this file is a {guide_module.name}.")
    return group


def uuid_of(node):
    """``node``'s UUID, to track it through renames and reparenting."""
    return cmds.ls(node, uuid=True)[0]


def node_of(uuid):
    """The long name of the node with ``uuid``, or ``None`` if it's gone."""
    found = cmds.ls(uuid, long=True) if uuid else []
    return found[0] if found else None


@undoable
def build(guide_module, layout):
    """Build ``layout``'s guides; joints that Delete Guides left of them
    come back live (see :meth:`GuideModule.rebuild`). Returns the top group."""
    return guide_module.rebuild(layout)


@undoable
def revert(guide_module, group, layout):
    """Put the guides under ``group`` back as ``layout`` has them. Returns
    the top group, a new one if the guides had to be made again."""
    return guide_module.restore(group, layout)


@undoable
def set_count(group, count):
    """Make a Chain's middle guides again: ``count`` of them, evenly between
    its start and end guides (see :func:`~.planar_chain.build_guides`).
    Returns the new top group."""
    group = _planar_chain.build_guides(_planar_chain.layout(group)["name"], count)
    _tag(group, _chain.GUIDE_MODULE.key)
    return group
