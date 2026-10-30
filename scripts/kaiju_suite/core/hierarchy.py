"""Default parents: where a node belongs in the hierarchy, saved on the node so
:func:`reparent` can put it back. Shared by the Outliner Tool and Guide Tool
templates. No Qt here.

The parent is saved as two string attributes, shown under Extra Attributes in
the Attribute Editor, so it survives saving the scene. The UUID finds the parent
after renames; the node name (no path) is the fallback when the UUID changed (an
import). An empty name is the world.
"""

from maya import cmds

from kaiju_suite.core.selection import short_name
from kaiju_suite.core.undo import undoable

_DEFAULT_UUID = "kaijuDefaultParentUuid"
_DEFAULT_NAME = "kaijuDefaultParentName"


def _long(uuid):
    return cmds.ls(uuid, long=True)[0]


def has_default_parent(node):
    return cmds.attributeQuery(_DEFAULT_UUID, node=node, exists=True)


def _default_parents(node):
    """Long names of the nodes that can be ``node``'s default parent: ``[""]`` for the
    world, none if it's gone, several if the UUID is lost and more than one node has its name."""
    uuid = cmds.getAttr(f"{node}.{_DEFAULT_UUID}")
    name = cmds.getAttr(f"{node}.{_DEFAULT_NAME}") or ""
    if not name:
        return [""]
    try:
        matches = cmds.ls(uuid, long=True) if uuid else []
    except RuntimeError:
        matches = []  # not a UUID Maya can parse
    return matches or cmds.ls(name, long=True, type="transform")


@undoable
def set_default_parent(node, parent=None):
    """Save ``parent`` on ``node`` as its default parent, replacing any saved before:
    by default its current parent, ``""`` for the world."""
    if parent is None:
        parent = (cmds.listRelatives(node, parent=True, fullPath=True) or [""])[0]
    uuid = cmds.ls(parent, uuid=True)[0] if parent else ""
    name = short_name(cmds.ls(parent, long=True)[0]) if parent else ""
    for attr, value in ((_DEFAULT_UUID, uuid), (_DEFAULT_NAME, name)):
        if cmds.attributeQuery(attr, node=node, exists=True) and cmds.attributeQuery(attr, node=node, hidden=True):
            cmds.deleteAttr(node, attribute=attr)  # an older version hid it; addAttr can't unhide
        if not cmds.attributeQuery(attr, node=node, exists=True):
            cmds.addAttr(node, longName=attr, dataType="string")
        cmds.setAttr(f"{node}.{attr}", value, type="string")


@undoable
def reparent(nodes, skip_missing=False):
    """Parent ``nodes`` back under their default parent, wherever they are now, keeping
    world positions. Returns their new long names.

    Nodes with no default parent are skipped, and so, with a warning, are nodes whose
    default parent is only found by name and more than one node has that name. Raises
    ``ValueError`` without changing anything if no node has a default parent, or if a
    default parent now sits under the node or is gone (unless ``skip_missing``: then
    that node stays where it is).
    """
    if not nodes:
        raise ValueError("Nothing selected")
    uuids = cmds.ls(nodes, uuid=True)
    if not any(has_default_parent(_long(uuid)) for uuid in uuids):
        raise ValueError("No default parent set")
    moves = []
    for uuid in uuids:
        node = _long(uuid)
        if not has_default_parent(node):
            continue
        targets = _default_parents(node)
        if len(targets) > 1:
            cmds.warning(f"Kaiju: more than one '{short_name(targets[0])}' for "
                         f"'{short_name(node)}' to go back under; skipped it")
            continue
        if not targets:
            if skip_missing:
                continue
            raise ValueError(f"Default parent for '{short_name(node)}' no longer exists")
        target = targets[0]
        if target.startswith(node + "|"):
            raise ValueError(f"{short_name(target)} is now under {short_name(node)}")
        moves.append((uuid, cmds.ls(target, uuid=True)[0] if target else ""))

    for uuid, parent_uuid in moves:
        current = (cmds.listRelatives(_long(uuid), parent=True, fullPath=True) or [""])[0]
        target = _long(parent_uuid) if parent_uuid else ""
        if current == target:
            continue
        if target:
            cmds.parent(_long(uuid), target)
        else:
            cmds.parent(_long(uuid), world=True)
    return [_long(uuid) for uuid in uuids]
