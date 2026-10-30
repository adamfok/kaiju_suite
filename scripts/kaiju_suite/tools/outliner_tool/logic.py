"""Outliner Tool logic. No Qt here, so it can be scripted and tested headless."""

import os
import re

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


# -- one-field rename --------------------------------------------------------
# What you type in the Outliner Tool's single field decides the action; see SHORTCUTS.

SHORTCUTS = [
    ("L_arm_##_jnt", "rename and number (## = 01, ### = 001)"),
    ("... @5", "start numbering at 5"),
    ("*_jnt", "add suffix (* = current name)"),
    ("L_*", "add prefix"),
    ("L_*_jnt", "add prefix and suffix"),
    ("old > new", "search and replace"),
    ("old >", "delete text"),
]

_START = re.compile(r"\s*@(\d+)$")
_VALID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _number(template, index):
    return naming.expand_pattern(template, index) if "#" in template else template


def _names(shorts, text):
    if ">" in text:
        search, replace = (part.strip() for part in text.split(">", 1))
        if not search:
            raise ValueError("Nothing to search for before >")
        return [s.replace(search, replace) for s in shorts]

    start = 1
    match = _START.search(text)
    if match:
        start = int(match.group(1))
        text = text[: match.start()].strip()

    stars = text.count("*")
    if stars > 1:
        raise ValueError("Only one * is allowed")
    if stars:
        prefix, suffix = text.split("*")
        return [_number(f"{prefix}{s}{suffix}", start + i) for i, s in enumerate(shorts)]
    if len(shorts) == 1 and "#" not in text:
        return [text]
    return [naming.expand_pattern(text, start + i) for i in range(len(shorts))]


def plan(nodes, text):
    """The new short names ``rename(nodes, text)`` would give, in order.

    Raises ``ValueError`` with a one-line reason if ``text`` can't be used.
    """
    text = text.strip()
    if not text:
        raise ValueError("Type a name")
    names = _names([short_name(n) for n in nodes], text)
    for name in names:
        if not _VALID.match(name):
            raise ValueError(f"{name!r} is not a valid name")
    return names


@undoable
def rename(nodes, text):
    """Rename ``nodes`` from the Outliner Tool's one-field ``text`` (see SHORTCUTS).

    Returns the new long names in the same order as ``nodes``.
    """
    return _rename_all(nodes, plan(nodes, text))


def preview(nodes, text):
    """``(line, problem)``: a one-line preview of ``rename(nodes, text)``.

    ``problem`` is True when the line reports something wrong. With nothing
    selected or nothing typed, the line is the field's title, "Rename".
    """
    if not nodes or not text.strip():
        return "Rename", False
    try:
        names = plan(nodes, text)
    except ValueError as e:
        return str(e), True
    line = names[0] if len(names) == 1 else f"{names[0]} … {names[-1]}"
    line = f"{line}  ({len(names)})"
    clashes = len(names) - len(set(names))
    if clashes:
        line += f", {clashes} name clashes" if clashes == 1 else f", {clashes} names clash"
    return line, bool(clashes)


# -- lock and hide -----------------------------------------------------------

_STANDARD = ("translateX", "translateY", "translateZ", "rotateX", "rotateY", "rotateZ",
             "scaleX", "scaleY", "scaleZ", "visibility")
# Attribute types Unlock brings back; text and compound attributes stay hidden.
_NUMERIC = {"bool", "enum", "long", "short", "byte", "float", "double", "doubleLinear", "doubleAngle"}


def _channel_box(node):
    """The attributes in ``node``'s channel box: keyable ones and shown non-keyable ones."""
    return list(dict.fromkeys((cmds.listAttr(node, keyable=True) or []) + (cmds.listAttr(node, channelBox=True) or [])))


@undoable
def lock_and_hide(nodes):
    """Lock and hide every attribute in the channel box of each of ``nodes``. Returns ``nodes``."""
    if not nodes:
        raise ValueError("Nothing selected")
    for node in nodes:
        for attr in _channel_box(node):
            cmds.setAttr(f"{node}.{attr}", lock=True, keyable=False, channelBox=False)
    return list(nodes)


@undoable
def unlock_and_show(nodes):
    """Unlock and make keyable the standard transform channels and each node's own numeric
    attributes, and show a joint's radius again (not keyable, as Maya has it). Returns ``nodes``.

    A hidden attribute leaves no trace of having been shown, so this restores a fixed set
    rather than exactly what ``lock_and_hide`` hid.
    """
    if not nodes:
        raise ValueError("Nothing selected")
    for node in nodes:
        attrs = [a for a in _STANDARD if cmds.attributeQuery(a, node=node, exists=True)]
        attrs += [a for a in cmds.listAttr(node, userDefined=True) or []
                  if cmds.getAttr(f"{node}.{a}", type=True) in _NUMERIC]
        for attr in attrs:
            # keyable only: channelBox=True means "shown but not keyable" and would win.
            cmds.setAttr(f"{node}.{attr}", lock=False, keyable=True)
        if cmds.nodeType(node) == "joint":
            cmds.setAttr(f"{node}.radius", lock=False, channelBox=True)
    return list(nodes)


# -- group, chain, offset ----------------------------------------------------


def _bare(node):
    """``|grp|ns:L_arm_1`` -> ``L_arm_1``: the short name without namespace."""
    return short_name(node).rsplit(":", 1)[-1]


def _long(uuid):
    return cmds.ls(uuid, long=True)[0]


def common_name(nodes):
    """The start the nodes' names share, less trailing digits and ``_``.

    ``["L_arm_01_jnt", "L_arm_02_jnt"]`` -> ``"L_arm"``; ``""`` if none.
    """
    return os.path.commonprefix([_bare(n) for n in nodes]).rstrip("0123456789_")


@undoable
def group_selected(nodes):
    """Group ``nodes`` under a new group named after them (``L_arm_grp``).

    With no shared start, it's named after the first node (``arm_grp``).
    The group sits at the origin, so nothing moves. Returns its long name.
    """
    name = common_name(nodes) or _bare(nodes[0])
    group = cmds.group(nodes, name=f"{name}_grp")
    return cmds.ls(group, long=True)[0]


@undoable
def chain(nodes):
    """Parent each node under the one before it, keeping world positions.

    Returns the new long names, in order. Raises ``ValueError`` without
    changing anything if a node is above an earlier one in the hierarchy.
    """
    for i, node in enumerate(nodes):
        for earlier in nodes[:i]:
            if earlier.startswith(node + "|"):
                raise ValueError(f"{short_name(node)} is above {short_name(earlier)}; select it first")
    uuids = cmds.ls(nodes, uuid=True)
    for parent, child in zip(uuids, uuids[1:]):
        current = cmds.listRelatives(_long(child), parent=True, fullPath=True) or []
        if current != [_long(parent)]:
            cmds.parent(_long(child), _long(parent))
    return [_long(uuid) for uuid in uuids]


@undoable
def offset(nodes):
    """Put a group named ``<node>_offset`` above each node, lined up with it.

    The node keeps its world position; its own translate and rotate go to
    zero. Returns the offset groups' long names, in order.
    """
    offsets = []
    for uuid in cmds.ls(nodes, uuid=True):
        node = _long(uuid)
        parent = cmds.listRelatives(node, parent=True, fullPath=True)
        kwargs = {"name": f"{_bare(node)}_offset"}
        if parent:
            kwargs["parent"] = parent[0]
        group = cmds.createNode("transform", **kwargs)
        cmds.xform(group, worldSpace=True, matrix=cmds.xform(node, query=True, worldSpace=True, matrix=True))
        cmds.parent(node, group)
        offsets.append(cmds.ls(group, uuid=True)[0])
    return [_long(uuid) for uuid in offsets]


# -- parent, unparent and reparent --------------------------------------------

# The parent a node had before Parent or Unparent moved it, saved on the node so
# it survives saving the scene. The UUID finds the parent after renames; the long
# name is the fallback when the UUID changed (an import). An empty name is the world.
_SAVED_UUID = "kaijuPrevParentUuid"
_SAVED_NAME = "kaijuPrevParentName"


def _has_saved_parent(node):
    return cmds.attributeQuery(_SAVED_UUID, node=node, exists=True)


def _save_parent(node):
    """Save ``node``'s current parent on it, unless one is saved already: Reparent
    goes back to where the node was before its first move."""
    if _has_saved_parent(node):
        return
    parents = cmds.listRelatives(node, parent=True, fullPath=True) or [""]
    uuid = cmds.ls(parents[0], uuid=True)[0] if parents[0] else ""
    for attr, value in ((_SAVED_UUID, uuid), (_SAVED_NAME, parents[0])):
        cmds.addAttr(node, longName=attr, dataType="string", hidden=True)
        cmds.setAttr(f"{node}.{attr}", value, type="string")


def _saved_parent(node):
    """The long name of ``node``'s saved parent, ``""`` for the world, or ``None`` if it's gone."""
    uuid = cmds.getAttr(f"{node}.{_SAVED_UUID}")
    name = cmds.getAttr(f"{node}.{_SAVED_NAME}") or ""
    if not name:
        return ""
    try:
        matches = cmds.ls(uuid, long=True) if uuid else []
    except RuntimeError:
        matches = []  # not a UUID Maya can parse
    if not matches and cmds.objExists(name):
        matches = cmds.ls(name, long=True)
    return matches[0] if matches else None


def _clear_saved_parent(node):
    cmds.deleteAttr(node, attribute=_SAVED_UUID)
    cmds.deleteAttr(node, attribute=_SAVED_NAME)


@undoable
def parent_under_last(nodes):
    """Parent ``nodes`` under the last one (like Maya's P key), keeping world positions
    and saving each node's previous parent for Reparent. Returns the moved nodes' new
    long names. Raises ``ValueError`` without changing anything if the last node is
    under one of the others.
    """
    if len(nodes) < 2:
        raise ValueError("Select the nodes to move, then the new parent last")
    *children, target = nodes
    for node in children:
        if target.startswith(node + "|"):
            raise ValueError(f"{short_name(target)} is under {short_name(node)}")
    uuids = cmds.ls(children, uuid=True)
    target_uuid = cmds.ls(target, uuid=True)[0]
    for uuid in uuids:
        node = _long(uuid)
        if cmds.listRelatives(node, parent=True, fullPath=True) == [_long(target_uuid)]:
            continue
        _save_parent(node)
        cmds.parent(_long(uuid), _long(target_uuid))
    return [_long(uuid) for uuid in uuids]


@undoable
def unparent(nodes):
    """Parent ``nodes`` to the world, saving their previous parent. Returns their new long names."""
    if not nodes:
        raise ValueError("Nothing selected")
    uuids = cmds.ls(nodes, uuid=True)
    for uuid in uuids:
        node = _long(uuid)
        if cmds.listRelatives(node, parent=True):
            _save_parent(node)
            cmds.parent(node, world=True)
    return [_long(uuid) for uuid in uuids]


@undoable
def reparent(nodes):
    """Parent ``nodes`` back under the parent Parent or Unparent saved, wherever they
    are now, and clear it. Returns their new long names.

    Nodes with nothing saved are skipped. Raises ``ValueError`` without changing
    anything if a saved parent is gone or now sits under the node.
    """
    if not nodes:
        raise ValueError("Nothing selected")
    uuids = cmds.ls(nodes, uuid=True)
    moves = []
    for uuid in uuids:
        node = _long(uuid)
        if not _has_saved_parent(node):
            continue
        target = _saved_parent(node)
        if target is None:
            raise ValueError(f"Previous parent for '{short_name(node)}' no longer exists")
        if target.startswith(node + "|"):
            raise ValueError(f"{short_name(target)} is now under {short_name(node)}")
        moves.append((uuid, cmds.ls(target, uuid=True)[0] if target else ""))
    if not moves:
        raise ValueError("No previous parent remembered")

    for uuid, parent_uuid in moves:
        current = cmds.listRelatives(_long(uuid), parent=True, fullPath=True) or [""]
        target = _long(parent_uuid) if parent_uuid else ""
        if current[0] != target:
            if target:
                cmds.parent(_long(uuid), target)
            else:
                cmds.parent(_long(uuid), world=True)
        _clear_saved_parent(_long(uuid))
    return [_long(uuid) for uuid in uuids]
