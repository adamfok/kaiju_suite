"""Guide Tool: place a joint chain with guide locators. No Qt here.

A chain's guides are a start guide, any number of middle guides and an end
guide, plus an up guide off to the side, like a pole vector. They can only
be moved: rotate and scale are locked. They sit under ``<name>_guides_grp``,
which finds them (and the joints built from them) through message
connections, so renaming them is fine.

Building joints puts them on the plane through the start, end and up
guides: middle guides off that plane are projected onto it. Each joint's
aim axis points at the next joint and its up axis lies in the plane, on the
up guide's side, so the third axis is the plane's normal for every joint
and the chain bends around that one axis. The end joint sits on the end
guide and lines up with its parent.

Every function that changes the scene is one undo step and raises
``ValueError``, changing nothing, when its input is wrong.
"""

import re

from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.core import orient
from kaiju_suite.core.selection import short_name
from kaiju_suite.core.undo import undoable

NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# On the guide group: the chain's name, then message links to its nodes.
_TAG = "kaijuGuides"
_CHAIN = "guideChain"  # start, middle and end guides, in order
_UP = "guideUp"
_JOINTS = "guideJoints"  # the joints built from the guides, top first
_CURVES = "guideCurves"  # the display curves: through the chain, start to up
# Closer than this counts as the same spot.
_TOLERANCE = 1e-4
_UP_COLOR = 17  # yellow


# -- helpers ------------------------------------------------------------------


def _long(node):
    return cmds.ls(node, long=True)[0]


def _by_uuid(uuid):
    return cmds.ls(uuid, long=True)[0]


def _position(node):
    return om.MVector(cmds.xform(node, query=True, worldSpace=True, translation=True))


def _is_group(node):
    return cmds.objExists(node) and cmds.attributeQuery(_TAG, node=node, exists=True)


def _connected(group, attr):
    """The nodes linked to ``group``'s multi message ``attr``, by index."""
    found = []
    for index in cmds.getAttr(f"{group}.{attr}", multiIndices=True) or []:
        source = cmds.listConnections(f"{group}.{attr}[{index}]", source=True, destination=False)
        if source:
            found.append(_long(source[0]))
    return found


def _link(node, group, plug):
    cmds.connectAttr(f"{node}.message", f"{group}.{plug}")


def _plane(points, up):
    """``points`` (start, middles, end) on the plane through start, end and
    ``up``, and that plane's normal (start->end ^ start->up)."""
    points = [om.MVector(p) for p in points]
    start, end, up = points[0], points[-1], om.MVector(up)
    span = end - start
    if span.length() < _TOLERANCE:
        raise ValueError("The start and end guides are on the same spot; move them apart.")
    normal = span ^ (up - start)
    if normal.length() / span.length() < _TOLERANCE:
        raise ValueError("The up guide is in line with the start and end guides; move it to the side.")
    normal.normalize()
    placed = [start] + [p - normal * ((p - start) * normal) for p in points[1:-1]] + [end]
    for i, (a, b) in enumerate(zip(placed, placed[1:]), start=1):
        if (b - a).length() < _TOLERANCE:
            raise ValueError(f"Joints {i} and {i + 1} land on the same spot on the plane; move their guides apart.")
    return placed, normal


def _lock_to_move_only(node):
    for attr in ("rx", "ry", "rz", "sx", "sy", "sz"):
        cmds.setAttr(f"{node}.{attr}", lock=True, keyable=False, channelBox=False)


def _guide(name, group, position, size):
    guide = cmds.spaceLocator(name=name)[0]
    guide = _long(cmds.parent(guide, group)[0])
    cmds.xform(guide, worldSpace=True, translation=(position.x, position.y, position.z))
    shape = cmds.listRelatives(guide, shapes=True, fullPath=True)[0]
    cmds.setAttr(f"{shape}.localScale", size, size, size)
    _lock_to_move_only(guide)
    return guide


def _display_curve(name, group, guides):
    """A template curve through ``guides`` that follows them as they move."""
    curve = cmds.curve(degree=1, point=[(0, 0, 0)] * len(guides), name=name)
    curve = _long(cmds.parent(curve, group)[0])
    # Its points come in world space, so it must not move with the group.
    cmds.setAttr(f"{curve}.inheritsTransform", False)
    cmds.setAttr(f"{curve}.template", True)
    shape = cmds.listRelatives(curve, shapes=True, fullPath=True)[0]
    for i, guide in enumerate(guides):
        guide_shape = cmds.listRelatives(guide, shapes=True, fullPath=True)[0]
        cmds.connectAttr(f"{guide_shape}.worldPosition[0]", f"{shape}.controlPoints[{i}]")
    return curve


# -- finding guides -----------------------------------------------------------


def guide_group(node):
    """The guide group ``node`` belongs to: ``node`` itself, the group above
    a guide, or the group a built joint is linked to."""
    found = cmds.ls(node, long=True) if node else []
    if not found:
        raise ValueError(f"{node!r} isn't in the scene.")
    path = found[0]
    linked = cmds.listConnections(f"{path}.message", source=False, destination=True) or []
    for candidate in [path] + cmds.ls(linked, long=True) + (cmds.listRelatives(path, allParents=True, fullPath=True) or []):
        if _is_group(candidate):
            return _long(candidate)
    raise ValueError(f"{short_name(path)} isn't a guide, a guide group or a joint built from guides.")


def find_group(nodes):
    """The one guide group ``nodes`` (e.g. the selection) belong to, or,
    with no ``nodes``, the only guide group in the scene."""
    if not nodes:
        groups = [n for n in cmds.ls(type="transform", long=True) if _is_group(n)]
        if not groups:
            raise ValueError("No guides in the scene. Create guides first.")
        if len(groups) > 1:
            raise ValueError("There are several guide groups. Select a guide, its group or a joint built from it.")
        return groups[0]
    groups = list(dict.fromkeys(guide_group(node) for node in nodes))
    if len(groups) > 1:
        raise ValueError(f"Select guides of one chain, not {', '.join(short_name(g) for g in groups)}.")
    return groups[0]


def guides(group):
    """``{"chain": [start, middles..., end], "up": up}``, as long names."""
    group = guide_group(group)
    chain, up = _connected(group, _CHAIN), cmds.listConnections(f"{group}.{_UP}", source=True, destination=False)
    if len(chain) < 2 or not up:
        raise ValueError(f"Guides of {short_name(group)} are missing; delete it and create the guides again.")
    return {"chain": chain, "up": _long(up[0])}


def joints(group):
    """The joints built from ``group``'s guides, top first."""
    return _connected(guide_group(group), _JOINTS)


def display_curves(group):
    """``(curve through the chain, curve from start to up)``."""
    return tuple(_connected(guide_group(group), _CURVES))


def planar_positions(points, up):
    """``points`` (start, middle points, end) with each middle point moved
    straight onto the plane through the start, the end and ``up``. Raises
    ``ValueError`` if ``up`` is in line with start and end, or if two
    neighbouring points land on the same spot."""
    return _plane(points, up)[0]


# -- editing ------------------------------------------------------------------


@undoable
def create_guides(name, count, start=(0, 0, 0), end=(10, 0, 0)):
    """Make guides for a chain named ``name``: start and end guides at
    ``start`` and ``end``, ``count`` middle guides evenly between them, and
    an up guide off to the side. Returns the guide group."""
    if not isinstance(name, str) or not NAME.match(name):
        raise ValueError(f"Name {name!r} can't be used in node names: use letters, digits and _, not starting with a digit.")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("The number of middle guides must be 0 or more.")
    start, end = om.MVector(start), om.MVector(end)
    span = end - start
    if span.length() < _TOLERANCE:
        raise ValueError("The start and end guides can't be on the same spot.")

    chain_names = (
        [f"{name}_start_guide"] + [f"{name}_mid_{i:02d}_guide" for i in range(1, count + 1)] + [f"{name}_end_guide"]
    )
    names = [f"{name}_guides_grp", f"{name}_up_guide", f"{name}_guide_crv", f"{name}_up_crv"] + chain_names
    taken = [n for n in names if cmds.objExists(n)]
    if taken:
        raise ValueError(f"These names are already used, rename or delete them first: {', '.join(taken)}")

    group = _long(cmds.createNode("transform", name=f"{name}_guides_grp"))
    cmds.addAttr(group, longName=_TAG, dataType="string")
    cmds.setAttr(f"{group}.{_TAG}", name, type="string")
    for attr, multi in ((_CHAIN, True), (_UP, False), (_JOINTS, True), (_CURVES, True)):
        cmds.addAttr(group, longName=attr, attributeType="message", multi=multi)

    size = span.length() * 0.05
    chain = []
    for i, guide_name in enumerate(chain_names):
        guide = _guide(guide_name, group, start + span * (i / (count + 1)), size)
        _link(guide, group, f"{_CHAIN}[{i}]")
        chain.append(guide)

    side = orient.row(orient.aim_matrix(span, (0, 1), (1, 1), om.MVector(0, 1, 0)), 1)
    up = _guide(f"{name}_up_guide", group, start + span * 0.5 + side * (span.length() * 0.5), size)
    cmds.setAttr(f"{up}.overrideEnabled", True)
    cmds.setAttr(f"{up}.overrideColor", _UP_COLOR)
    _link(up, group, _UP)

    _link(_display_curve(f"{name}_guide_crv", group, chain), group, f"{_CURVES}[0]")
    _link(_display_curve(f"{name}_up_crv", group, [chain[0], up]), group, f"{_CURVES}[1]")
    cmds.select(clear=True)
    return group


@undoable
def build_joints(group, aim="x", up="y"):
    """Build a planar joint chain from ``group``'s guides, or, if one was
    built already, move and re-orient those joints (keeping their names
    and what's attached to them). ``aim`` points at the next joint and
    ``up`` towards the up guide's side, both ``"x"``, ``"-y"``...
    Returns the joints, top first."""
    group = guide_group(group)
    aim_axis, up_axis = orient.axis(aim), orient.axis(up)
    if aim_axis[0] == up_axis[0]:
        raise ValueError("The aim axis and the up axis must be different axes.")
    found = guides(group)
    positions, normal = _plane([_position(g) for g in found["chain"]], _position(found["up"]))

    existing = joints(group)
    if existing and len(existing) != len(positions):
        raise ValueError(
            f"The chain built from these guides has {len(existing)} joints but the guides make {len(positions)}. "
            "Delete the joints to build a new chain."
        )
    if existing:
        uuids = cmds.ls(existing, uuid=True)
    else:
        name = cmds.getAttr(f"{group}.{_TAG}")
        names = [f"{name}_{i:02d}_jnt" for i in range(1, len(positions) + 1)]
        taken = [n for n in names if cmds.objExists(n)]
        if taken:
            raise ValueError(f"These names are already used, rename or delete them first: {', '.join(taken)}")
        uuids, parent = [], None
        for i, joint_name in enumerate(names):
            joint = cmds.createNode("joint", name=joint_name, **({"parent": parent} if parent else {}))
            joint = _long(joint)
            if parent:
                cmds.connectAttr(f"{parent}.scale", f"{joint}.inverseScale", force=True)
            _link(joint, group, f"{_JOINTS}[{i}]")
            uuids.append(cmds.ls(joint, uuid=True)[0])
            parent = joint

    last = len(uuids) - 1
    for i, uuid in enumerate(uuids):
        joint = _by_uuid(uuid)
        position = positions[i]
        cmds.xform(joint, worldSpace=True, translation=(position.x, position.y, position.z))
        if i < last:
            direction = positions[i + 1] - position
            world = orient.aim_matrix(direction, aim_axis, up_axis, normal ^ direction)
            orient.set_world_rotation(joint, world)
        else:
            for attr in ("rotate", "rotateAxis", "jointOrient"):
                cmds.setAttr(f"{joint}.{attr}", 0, 0, 0)
    return [_by_uuid(uuid) for uuid in uuids]


@undoable
def delete_guides(group):
    """Delete ``group`` and its guides. Joints built from them stay."""
    cmds.delete(guide_group(group))
