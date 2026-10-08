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
