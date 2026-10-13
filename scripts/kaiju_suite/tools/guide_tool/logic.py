"""Guide Tool: place a joint chain with guide locators. No Qt here.

The guides themselves are :mod:`kaiju_suite.rigging.guides.planar_chain`,
shared with the guide modules (the Chain guide module is one of these
chains); this makes each function that changes the scene one undo step.
"""

import os

from kaiju_suite.core.undo import undoable
from kaiju_suite.rigging.guides import planar_chain as _planar_chain
from kaiju_suite.rigging.guides import spec as _spec
from kaiju_suite.rigging.guides.guide_modules import chain as _chain
from kaiju_suite.rigging.guides.planar_chain import (  # noqa: F401 (re-exported for the window)
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

build_guides = undoable(_planar_chain.build_guides)
guides_from_joints = undoable(_planar_chain.guides_from_joints)
set_axes = undoable(_planar_chain.set_axes)
delete_guides = undoable(_planar_chain.delete_guides)


def item_fields(path):
    """The window's Name, # Mid, Aim and Up for the Assembler Chain Guide
    item at ``path``: ``{"name", "count", "aim", "up"}``. Raises
    ``ValueError`` if the item is empty, isn't a guide file or holds
    another guide module."""
    name = os.path.basename(path)
    if os.path.getsize(path) == 0:
        raise ValueError(f"{name} is empty. Publish guides into it first.")
    key, layout = _spec.read(path)
    if key != _chain.GUIDE_MODULE.key:
        raise ValueError(f"{name} isn't a {_chain.GUIDE_MODULE.name} item; the Guide Tool only opens chains.")
    return _chain.GUIDE_MODULE.fields(layout)
