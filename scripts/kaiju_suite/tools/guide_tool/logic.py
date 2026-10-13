"""Guide Tool: place a joint chain with guide locators. No Qt here.

The guides themselves are :mod:`kaiju_suite.core.guides`, shared with the
Assembler's Guide items; this makes each function that changes the scene
one undo step.
"""

import os

from kaiju_suite import datatypes
from kaiju_suite.core import guides as _guides
from kaiju_suite.core.guides import (  # noqa: F401 (re-exported for the window)
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
from kaiju_suite.core.undo import undoable
from kaiju_suite.datatypes import guides as _guide_data

build_guides = undoable(_guides.build_guides)
guides_from_joints = undoable(_guides.guides_from_joints)
set_axes = undoable(_guides.set_axes)
delete_guides = undoable(_guides.delete_guides)


def item_fields(path):
    """The window's Name, # Mid, Aim and Up for the Assembler Guide item at
    ``path``: ``{"name", "count", "aim", "up"}``. Raises ``ValueError`` if
    the item is empty or isn't a guide file."""
    if os.path.getsize(path) == 0:
        raise ValueError(f"{os.path.basename(path)} is empty. Publish guides into it first.")
    return _guide_data.fields(datatypes.read(path, _guide_data.KIND))
