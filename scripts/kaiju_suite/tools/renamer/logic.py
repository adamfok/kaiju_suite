"""Renamer logic. No Qt here, so it can be scripted and tested headless."""

from maya import cmds

from kaiju_suite.core import naming
from kaiju_suite.core.selection import short_name
from kaiju_suite.core.undo import undoable


def _rename_all(nodes, new_names):
    # Track nodes by UUID: renaming a parent changes its children's long
    # names, so paths captured up front would go stale mid-loop.
    uuids = cmds.ls(nodes, uuid=True)
    for uuid, new in zip(uuids, new_names):
        cmds.rename(cmds.ls(uuid, long=True)[0], new)
    return [cmds.ls(uuid, long=True)[0] for uuid in uuids]


@undoable
def rename_sequential(nodes, pattern, start=1, step=1):
    """Rename ``nodes`` with a numbered pattern, e.g. ``"arm_##_jnt"``.

    Returns the new node names in the same order as ``nodes``.
    """
    names = [naming.expand_pattern(pattern, start + i * step) for i in range(len(nodes))]
    return _rename_all(nodes, names)


@undoable
def search_replace(nodes, search, replace):
    """Replace ``search`` with ``replace`` in each node's short name."""
    if not search:
        return list(nodes)
    names = [short_name(n).replace(search, replace) for n in nodes]
    return _rename_all(nodes, names)


@undoable
def add_prefix_suffix(nodes, prefix="", suffix=""):
    names = [f"{prefix}{short_name(n)}{suffix}" for n in nodes]
    return _rename_all(nodes, names)
