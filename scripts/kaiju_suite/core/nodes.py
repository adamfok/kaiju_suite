"""Scene node helpers shared by tools and rig data. No Qt here."""

import re

from maya import cmds

_TRAILING_DIGITS = re.compile(r"\d+$")


def unique_name(name):
    """``name`` if no node has it, else the next free one, numbered the way
    Maya does it: ``spine_jnt`` → ``spine_jnt1``, a taken ``joint1`` → ``joint2``.

    Checks every node, not just siblings, so names found later by name
    stay unambiguous.
    """
    if not cmds.objExists(name):
        return name
    base = _TRAILING_DIGITS.sub("", name) or name
    number = 1
    while cmds.objExists(f"{base}{number}"):
        number += 1
    return f"{base}{number}"
