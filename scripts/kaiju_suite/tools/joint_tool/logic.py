"""Joint Tool: orient, mirror, split and display joints. No Qt here.

Axes are given as ``"x"``, ``"y"``, ``"z"``, optionally signed (``"-x"``,
``"+y"``). Orienting aims each joint's aim axis at its first child joint and
turns its up axis as close to the world up direction as it can, putting
the whole orientation in the joint orient (rotate and rotate axis become
zero). Nothing moves in the world: joints and other children below an
edited joint keep their world position and orientation.

Every function that changes the scene is one undo step and raises
``ValueError``, changing nothing, when its input is wrong.
"""

import math

from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.core.naming import expand_pattern, opposite_name
from kaiju_suite.core.nodes import unique_name
from kaiju_suite.core.selection import short_name
from kaiju_suite.core.undo import undoable

AXES = ("x", "y", "z")
SIGNED_AXES = ("x", "y", "z", "-x", "-y", "-z")
_INDEX = {"x": 0, "y": 1, "z": 2}
# How close to parallel the aim and world up may be before another up is used.
_PARALLEL = 1e-6


# -- helpers ----------------------------------------------------------------


def _axis(axis):
    """``"-y"`` -> ``(1, -1)``: the axis index and its sign."""
    text = str(axis).strip().lower()
    sign = -1 if text.startswith("-") else 1
    letter = text.lstrip("+-")
    if letter not in _INDEX:
        raise ValueError(f"Unknown axis {axis!r}; use x, y or z, optionally with - in front.")
    return _INDEX[letter], sign


def _unique(items):
    return list(dict.fromkeys(items))


def _joints(nodes):
    """The joints among ``nodes``, as long names, each once."""
    return _unique(cmds.ls(nodes, type="joint", long=True) or []) if nodes else []


def _child_joints(joint):
    return cmds.listRelatives(joint, children=True, type="joint", fullPath=True) or []


def _children(node):
    return cmds.listRelatives(node, children=True, type="transform", fullPath=True) or []


def _with_descendants(nodes, node_type="joint"):
    """``nodes`` and everything of ``node_type`` below them, parents first."""
    found = []
    for node in nodes:
        found.append(node)
        below = cmds.listRelatives(node, allDescendents=True, type=node_type, fullPath=True) or []
        found.extend(sorted(below, key=lambda path: path.count("|")))
    return _unique(found)


def _top(nodes):
    """``nodes`` without the ones below another of them."""
    return [n for n in nodes if not any(n.startswith(other + "|") for other in nodes)]


def _by_uuid(uuid):
    return cmds.ls(uuid, long=True)[0]


def _matrix(node, attr="worldMatrix"):
    return om.MMatrix(cmds.getAttr(f"{node}.{attr}[0]"))


def _rotation(matrix):
    """Only the rotation of ``matrix`` (no scale, shear or translation)."""
    return om.MTransformationMatrix(matrix).rotation(asQuaternion=True).asMatrix()


def _euler_matrix(node, attr, order=0):
    values = [math.radians(v) for v in cmds.getAttr(f"{node}.{attr}")[0]]
    return om.MEulerRotation(values, order).asMatrix()


def _set_joint_orient(joint, matrix):
    euler = om.MTransformationMatrix(matrix).rotation()
    cmds.setAttr(f"{joint}.jointOrient", *(math.degrees(a) for a in (euler.x, euler.y, euler.z)))


def _set_world_rotation(joint, world, keep_rotate=False):
    """Turn ``joint`` to the world rotation ``world`` through its joint
    orient. Unless ``keep_rotate``, its rotate and rotate axis become zero."""
    if not keep_rotate:
        cmds.setAttr(f"{joint}.rotate", 0, 0, 0)
        cmds.setAttr(f"{joint}.rotateAxis", 0, 0, 0)
    local = _rotation(_rotation(world) * _rotation(_matrix(joint, "parentMatrix")).inverse())
    order = cmds.getAttr(f"{joint}.rotateOrder")
    rotation = _euler_matrix(joint, "rotateAxis") * _euler_matrix(joint, "rotate", order)
    _set_joint_orient(joint, rotation.inverse() * local)


def _restore(node, world):
    """Put ``node`` back at the world matrix ``world``; a joint through its
    translate and joint orient, keeping its rotate."""
    if cmds.nodeType(node) == "joint":
        cmds.xform(node, worldSpace=True, translation=(world[12], world[13], world[14]))
        _set_world_rotation(node, world, keep_rotate=True)
    else:
        cmds.xform(node, worldSpace=True, matrix=list(world))


def _edit_keeping_children(node, edit):
    """Call ``edit()``, then put ``node``'s children back where they were."""
    kept = [(cmds.ls(child, uuid=True)[0], _matrix(child)) for child in _children(node)]
    edit()
    for uuid, world in kept:
        _restore(_by_uuid(uuid), world)


def _position(node):
    return om.MVector(cmds.xform(node, query=True, worldSpace=True, translation=True))


def _row(matrix, index):
    return om.MVector(matrix[index * 4], matrix[index * 4 + 1], matrix[index * 4 + 2])


def _aim_matrix(direction, aim, up, world_up, fallback_up=None):
    """A rotation whose ``aim`` axis points along ``direction`` and whose
    ``up`` axis is as close to ``world_up`` as it can be."""
    (aim_index, aim_sign), (up_index, up_sign) = aim, up
    direction = om.MVector(direction).normalize()
    candidates = [world_up] + ([fallback_up] if fallback_up is not None else [])
    candidates += [om.MVector(v) for v in ((0, 1, 0), (0, 0, 1), (1, 0, 0))]
    for candidate in candidates:
        upward = candidate - direction * (candidate * direction)
        if upward.length() > _PARALLEL:
            break
    rows = [None, None, None]
    rows[aim_index] = direction * aim_sign
    rows[up_index] = upward.normalize() * up_sign
    third = 3 - aim_index - up_index
    rows[third] = rows[(third + 1) % 3] ^ rows[(third + 2) % 3]
    return om.MMatrix([[r.x, r.y, r.z, 0.0] for r in rows] + [[0.0, 0.0, 0.0, 1.0]])


def _zero(joint):
    cmds.setAttr(f"{joint}.rotate", 0, 0, 0)
    cmds.setAttr(f"{joint}.rotateAxis", 0, 0, 0)
    cmds.setAttr(f"{joint}.jointOrient", 0, 0, 0)


# -- orient -----------------------------------------------------------------


@undoable
def orient(joints, aim="x", up="y", world_up="y", children=True, zero_end=True):
    """Orient ``joints`` (and every joint below them if ``children``): the
    ``aim`` axis points at the first child joint, the ``up`` axis as close
    to the world ``world_up`` axis as it can. A joint with no child joint
    (an end joint) gets a zero joint orient, matching its parent, if
    ``zero_end``, else keeps its orientation. Returns the oriented joints."""
    aim_axis, up_axis = _axis(aim), _axis(up)
    world_index, world_sign = _axis(world_up)
    if aim_axis[0] == up_axis[0]:
        raise ValueError("The aim axis and the up axis must be different axes.")
    joints = _joints(joints)
    if not joints:
        raise ValueError("No joints given.")
    world_up_vector = om.MVector([world_sign if i == world_index else 0 for i in range(3)])

    targets = _with_descendants(joints) if children else joints
    targets = sorted(targets, key=lambda path: path.count("|"))
    uuids = cmds.ls(targets, uuid=True)
    oriented = {}  # uuid -> world rotation given to it
    for uuid in uuids:
        joint = _by_uuid(uuid)
        child_joints = _child_joints(joint)
        if child_joints:
            parent = cmds.listRelatives(joint, parent=True, fullPath=True)
            parent_rotation = oriented.get(cmds.ls(parent, uuid=True)[0]) if parent else None
            fallback = _row(parent_rotation, up_axis[0]) * up_axis[1] if parent_rotation else None
            world = _aim_matrix(
                _position(child_joints[0]) - _position(joint), aim_axis, up_axis, world_up_vector, fallback
            )
            _edit_keeping_children(joint, lambda: _set_world_rotation(joint, world))
            oriented[uuid] = world
        elif zero_end:
            _edit_keeping_children(joint, lambda: _zero(joint))
    return [_by_uuid(uuid) for uuid in uuids]


@undoable
def zero_end_orients(joints):
    """Give every end joint (one with no child joint) in or below
    ``joints`` a zero joint orient, rotate and rotate axis, so it lines up
    with its parent. Returns the end joints changed."""
    joints = _joints(joints)
    if not joints:
        raise ValueError("No joints given.")
    ends = [j for j in _with_descendants(joints) if not _child_joints(j)]
    for joint in ends:
        _edit_keeping_children(joint, lambda: _zero(joint))
    return ends


# -- mirror -----------------------------------------------------------------


def _pairs(source, copy):
    """``(source joint, copied joint)`` for ``source``'s hierarchy and its
    mirrored ``copy``, matched by position in the hierarchy."""
    found = [(source, copy)]
    for a, b in zip(_child_joints(source), _child_joints(copy)):
        found.extend(_pairs(a, b))
    return found


@undoable
def mirror(joints, behavior=True):
    """Mirror ``joints`` and the joints below them across X (the YZ plane),
    naming each copy after the other side (``L_arm`` -> ``R_arm``, see
    :func:`kaiju_suite.core.naming.opposite_name`); a joint with no side in
    its name keeps the name Maya gives it. With ``behavior`` the copies
    rotate the opposite way (Maya's Behavior mirror), else they keep the
    source joints' world orientation (Orientation). Joints below another given joint are mirrored
    with it, once. Returns the new top joints."""
    roots = _top(_joints(joints))
    if not roots:
        raise ValueError("No joints given.")
    taken = []
    for joint in _with_descendants(roots):
        name = opposite_name(short_name(joint))
        if name and cmds.objExists(name):
            taken.append(name)
    if taken:
        raise ValueError(f"These names are already used, rename or delete them first: {', '.join(taken)}")

    created = []
    for root in roots:
        uuid = cmds.ls(root, uuid=True)[0]
        # ls(type=..., uuid=True) gives names, so list the joints first.
        before = set(cmds.ls(cmds.ls(type="joint"), uuid=True))
        cmds.mirrorJoint(root, mirrorYZ=True, mirrorBehavior=behavior)
        new = [j for j in cmds.ls(type="joint", long=True) if cmds.ls(j, uuid=True)[0] not in before]
        copy = next(j for j in new if not any(j.startswith(other + "|") for other in new))
        renames = [
            (cmds.ls(b, uuid=True)[0], opposite_name(short_name(a))) for a, b in _pairs(_by_uuid(uuid), copy)
        ]
        for copy_uuid, name in renames:
            if name:
                cmds.rename(_by_uuid(copy_uuid), name)
        created.append(renames[0][0])
    return [_by_uuid(uuid) for uuid in created]


# -- insert -----------------------------------------------------------------


@undoable
def insert_joints(joint, count, child=None, name=None):
    """Insert ``count`` joints evenly spaced between ``joint`` and ``child``
    (its first child joint if not given), which ends up under the last
    one, where it was. The new joints line up with ``joint``, share its
    radius and are named from ``name`` (``#`` for the number, see
    :func:`kaiju_suite.core.naming.expand_pattern`), by default
    ``<joint>_split_##``. Returns the new joints, top first."""
    joints = _joints([joint])
    if not joints:
        raise ValueError(f"{joint!r} isn't a joint.")
    joint = joints[0]
    if not isinstance(count, int) or count < 1:
        raise ValueError("Insert at least 1 joint.")
    child_joints = _child_joints(joint)
    if child is None:
        if not child_joints:
            raise ValueError(f"{short_name(joint)} has no child joint to insert joints before.")
        child = child_joints[0]
    else:
        found = _joints([child])
        if not found or found[0] not in child_joints:
            raise ValueError(f"{child!r} isn't a joint directly below {short_name(joint)}.")
        child = found[0]

    pattern = name or f"{short_name(joint)}_split_##"
    child_uuid = cmds.ls(child, uuid=True)[0]
    child_world = _matrix(child)
    start, end = _position(joint), _position(child)
    radius = cmds.getAttr(f"{joint}.radius")
    uuids, parent = [], joint
    for i in range(1, count + 1):
        new = cmds.createNode("joint", name=unique_name(expand_pattern(pattern, i)), parent=parent)
        new = cmds.ls(new, long=True)[0]
        cmds.connectAttr(f"{parent}.scale", f"{new}.inverseScale", force=True)
        cmds.setAttr(f"{new}.radius", radius)
        position = start + (end - start) * (i / float(count + 1))
        cmds.xform(new, worldSpace=True, translation=(position.x, position.y, position.z))
        uuids.append(cmds.ls(new, uuid=True)[0])
        parent = new
    cmds.parent(_by_uuid(child_uuid), parent)
    _restore(_by_uuid(child_uuid), child_world)
    return [_by_uuid(uuid) for uuid in uuids]


@undoable
def insert_below(joints, count):
    """:func:`insert_joints` ``count`` joints below each of ``joints``,
    before its first child joint, as one undo step. Every joint is
    checked first; if one has no child joint nothing changes. Returns
    all the new joints."""
    joints = _joints(joints)
    if not joints:
        raise ValueError("No joints given.")
    lonely = [short_name(j) for j in joints if not _child_joints(j)]
    if lonely:
        raise ValueError(f"No child joint to insert joints before: {', '.join(lonely)}")
    if not isinstance(count, int) or count < 1:
        raise ValueError("Insert at least 1 joint.")
    made = []
    # Track by UUID: inserting below one joint changes the paths below it.
    for uuid in cmds.ls(joints, uuid=True):
        made.extend(cmds.ls(insert_joints(_by_uuid(uuid), count), uuid=True))
    return [_by_uuid(uuid) for uuid in made]


# -- display ----------------------------------------------------------------


@undoable
def toggle_local_axis(nodes, hierarchy=False):
    """Show the local axes of ``nodes`` (and of every transform below them
    if ``hierarchy``) if any is hidden, else hide them all. Returns
    whether they're shown now."""
    nodes = _unique(cmds.ls(nodes, type="transform", long=True) or []) if nodes else []
    if not nodes:
        raise ValueError("No joints or transforms given.")
    if hierarchy:
        nodes = _with_descendants(nodes, "transform")
    show = not all(cmds.getAttr(f"{n}.displayLocalAxis") for n in nodes)
    for node in nodes:
        cmds.setAttr(f"{node}.displayLocalAxis", show)
    return show


@undoable
def set_radius(joints, radius, hierarchy=False):
    """Set the radius of ``joints`` (and every joint below them if
    ``hierarchy``). Returns the joints changed."""
    if radius <= 0:
        raise ValueError("The radius must be above 0.")
    joints = _joints(joints)
    if not joints:
        raise ValueError("No joints given.")
    if hierarchy:
        joints = _with_descendants(joints)
    for joint in joints:
        cmds.setAttr(f"{joint}.radius", radius)
    return joints
