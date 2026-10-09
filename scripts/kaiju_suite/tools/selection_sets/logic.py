"""Selection Sets: named sets of controls kept in the scene, plus quick
picking, keying and resetting. No Qt here.

Each set is a Maya ``objectSet`` that's a member of one parent set,
:data:`PARENT` (``kaiju_selectionSets``), in the root namespace. The set's
name is kept in its string attribute ``kaijuSetName``; the node itself is
named ``<name>_selSet`` (Maya may add a number if that's taken). Because
members are held by connection, a set saves with the file, follows its
members when they're renamed or reparented, drops them when they're
deleted, and works with namespaced and referenced controls. Sets inside
referenced files aren't listed: save sets in the scene you animate in.

Set names must be valid Maya names (letters, digits and ``_``, not starting
with a digit) so they can be mirrored with
:func:`kaiju_suite.core.naming.opposite_name` (``L_arm`` -> ``R_arm``).
"""

import re
from collections import namedtuple

from maya import cmds

from kaiju_suite.core.log import get_logger
from kaiju_suite.core.naming import opposite_name
from kaiju_suite.core.undo import undoable

log = get_logger(__name__)

PARENT = "kaiju_selectionSets"
NAME_ATTR = "kaijuSetName"
SUFFIX = "_selSet"

Mirrored = namedtuple("Mirrored", "name skipped")
Result = namedtuple("Result", "changed skipped")

_VALID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# -- sets -------------------------------------------------------------------


def _parent(create=False):
    """The parent set, or ``None`` if there's none (made if ``create``)."""
    if cmds.objExists(PARENT):
        if cmds.nodeType(PARENT) != "objectSet":
            raise ValueError(f"{PARENT} exists in the scene but isn't a set. Rename it first.")
        return PARENT
    if not create:
        return None
    return cmds.sets(name=PARENT, empty=True)


def _set_nodes():
    """``{name: set node}`` for every selection set in the scene."""
    parent = _parent()
    children = (cmds.sets(parent, query=True) or []) if parent else []
    found = {}
    for node in children:
        if cmds.nodeType(node) == "objectSet" and cmds.attributeQuery(NAME_ATTR, node=node, exists=True):
            found[cmds.getAttr(f"{node}.{NAME_ATTR}")] = node
    return found


def _node(name):
    node = _set_nodes().get(name)
    if node is None:
        raise ValueError(f"No selection set named {name!r}.")
    return node


def _check_new_name(name):
    if not _VALID.match(name or ""):
        raise ValueError(f"{name!r} isn't a valid set name: use letters, digits and _, not starting with a digit.")
    if name in _set_nodes():
        raise ValueError(f"A selection set named {name!r} already exists.")


def _existing(nodes):
    found = cmds.ls(nodes, long=True) if nodes else []
    if not found:
        raise ValueError("Nothing to save: select some nodes first.")
    return found


def list_sets():
    """The names of the selection sets in the scene, sorted (ignoring case)."""
    return sorted(_set_nodes(), key=lambda name: (name.lower(), name))


def members(name):
    """The long names of the members of the set ``name``."""
    return cmds.ls(cmds.sets(_node(name), query=True) or [], long=True)


def _create(name, nodes):
    node = cmds.sets(name=f"{name}{SUFFIX}", empty=True)
    cmds.addAttr(node, longName=NAME_ATTR, dataType="string")
    cmds.setAttr(f"{node}.{NAME_ATTR}", name, type="string")
    cmds.sets(nodes, add=node)
    cmds.sets(node, add=_parent(create=True))
    return node


def _replace(node, nodes):
    cmds.sets(clear=node)
    if nodes:
        cmds.sets(nodes, add=node)


@undoable
def save_set(name, nodes):
    """Save ``nodes`` as a new set called ``name``. Raises ``ValueError`` if
    the name is invalid or taken, or no node exists."""
    _check_new_name(name)
    _create(name, _existing(nodes))


@undoable
def update_set(name, nodes):
    """Replace the members of the set ``name`` with ``nodes``."""
    node = _node(name)
    _replace(node, _existing(nodes))


@undoable
def rename_set(name, new_name):
    node = _node(name)
    _check_new_name(new_name)
    cmds.setAttr(f"{node}.{NAME_ATTR}", new_name, type="string")
    cmds.rename(node, f"{new_name}{SUFFIX}")


@undoable
def delete_set(name):
    """Delete the set ``name``; its members are left alone."""
    cmds.delete(_node(name))


@undoable
def recall(name, add=False):
    """Select the members of the set ``name``, replacing the selection or
    adding to it; returns the members."""
    found = members(name)
    if found:
        cmds.select(found, add=add, replace=not add)
    elif not add:
        cmds.select(clear=True)
    return found


@undoable
def mirror_set(name):
    """Create (or update) the opposite-side set of ``name`` (``L_arm`` ->
    ``R_arm``), holding each member's opposite; members with no side in
    their name are kept as they are. Returns :data:`Mirrored`: the new set's
    name and the members whose opposite isn't in the scene. Raises
    ``ValueError``, changing nothing, if the set's name has no side or no
    member has an opposite."""
    other = opposite_name(name)
    if other is None:
        raise ValueError(f"{name!r} has no side in its name (L_/R_, left/right, ...), so it can't be mirrored.")
    mirrored, skipped, sided = [], [], 0
    for node in members(name):
        short = cmds.ls(node)[0]
        opposite = opposite_name(short)
        if opposite is None:
            mirrored.append(node)
            continue
        found = cmds.ls(opposite, long=True)
        if len(found) == 1:
            mirrored.append(found[0])
            sided += 1
        else:
            skipped.append(short)
    if not sided:
        raise ValueError(f"None of the members of {name!r} has an opposite in the scene.")
    mirrored = list(dict.fromkeys(mirrored))
    existing = _set_nodes().get(other)
    if existing:
        _replace(existing, mirrored)
    else:
        _create(other, mirrored)
    if skipped:
        log.warning("Mirroring %s: no opposite for %s", name, ", ".join(skipped))
    return Mirrored(other, skipped)


# -- rig controls -----------------------------------------------------------


def _is_control(node):
    shapes = cmds.listRelatives(node, shapes=True, type="nurbsCurve", fullPath=True) or []
    return any(not cmds.getAttr(f"{shape}.intermediateObject") for shape in shapes)


def rig_controls(top_nodes):
    """Long names of the controls (transforms with a visible nurbsCurve
    shape) under ``top_nodes``, the top nodes included, each once."""
    tops = cmds.ls(top_nodes, long=True, type="transform") or []
    found = []
    for top in tops:
        below = cmds.listRelatives(top, allDescendents=True, type="transform", fullPath=True) or []
        found += [node for node in [top] + list(reversed(below)) if _is_control(node)]
    return list(dict.fromkeys(found))


@undoable
def select_rig_controls(top_nodes):
    """Select the controls under ``top_nodes``; returns them."""
    found = rig_controls(top_nodes)
    if found:
        cmds.select(found, replace=True)
    return found


# -- key and reset ----------------------------------------------------------


def _keyable(node):
    """``node``'s keyable, unlocked, scalar attributes (no multis)."""
    attrs = []
    for attr in cmds.listAttr(node, keyable=True, unlocked=True, scalar=True) or []:
        if "." in attr or cmds.attributeQuery(attr, node=node, multi=True):
            continue
        attrs.append(attr)
    return attrs


def _driven(node, attr):
    """Whether ``node.attr`` is driven by a connection other than its keys."""
    sources = cmds.listConnections(f"{node}.{attr}", source=True, destination=False, skipConversionNodes=True) or []
    return any(not cmds.nodeType(source).startswith("animCurve") for source in sources)


@undoable
def key(nodes):
    """Key every keyable, unlocked attribute of ``nodes`` at the current
    time (attributes driven by a connection are skipped); returns how many
    nodes got keys."""
    count = 0
    for node in dict.fromkeys(cmds.ls(nodes, long=True) or []):
        plugs = [f"{node}.{attr}" for attr in _keyable(node) if not _driven(node, attr)]
        if plugs:
            cmds.setKeyframe(plugs)
            count += 1
    return count


@undoable
def reset(nodes):
    """Set every keyable attribute of ``nodes`` to its default (the bind
    pose for controls zeroed under offset groups). Locked attributes are
    left alone; ones driven by a connection other than keys are skipped
    and reported. Returns :data:`Result`."""
    changed, skipped = [], []
    for node in dict.fromkeys(cmds.ls(nodes, long=True) or []):
        for attr in _keyable(node):
            if _driven(node, attr):
                skipped.append(f"{cmds.ls(node)[0]}.{attr} (connected)")
                continue
            default = cmds.attributeQuery(attr, node=node, listDefault=True)
            if default and isinstance(cmds.getAttr(f"{node}.{attr}"), (bool, int, float)):
                cmds.setAttr(f"{node}.{attr}", default[0])
        changed.append(node)
    return Result(changed, skipped)
