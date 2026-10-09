"""Pure string helpers for node names (no Maya calls)."""

import re

_HASHES = re.compile(r"#+")


def expand_pattern(pattern, index):
    """Replace a run of ``#`` with ``index`` zero-padded to the run's length.

    ``expand_pattern("arm_##_jnt", 3)`` -> ``"arm_03_jnt"``.
    A pattern with no ``#`` gets the number appended.
    """
    match = _HASHES.search(pattern)
    if not match:
        return f"{pattern}{index}"
    number = str(index).zfill(len(match.group()))
    return pattern[: match.start()] + number + pattern[match.end():]


# Side tokens and their opposites. A one-letter side must stand alone between
# separators (``L_arm``, ``arm_L``); a word side may also start a camelCase
# part (``leftEye``, ``eyeLeft``), but not be part of a longer word.
_SIDES = {"L": "R", "R": "L", "l": "r", "r": "l", "left": "right", "right": "left", "Left": "Right", "Right": "Left"}
_SIDE = re.compile(
    r"(?<![A-Za-z0-9])[LRlr](?![A-Za-z0-9])"
    r"|(?<![A-Za-z])(?:left|right)(?![a-z])"
    r"|(?<![A-Z])(?:Left|Right)(?![a-z])"
)


def opposite_name(name):
    """``name`` with its side swapped, or ``None`` if it has no side.

    ``opposite_name("L_arm_ctrl")`` -> ``"R_arm_ctrl"``; works on every
    part of a path or namespace (``"|grp|L_arm"`` -> ``"|grp|R_arm"``).
    """
    swapped, count = _SIDE.subn(lambda m: _SIDES[m.group()], name)
    return swapped if count else None
