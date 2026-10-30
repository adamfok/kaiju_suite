"""Orientation math shared by tools that orient joints. No Qt here.

Axes are given as ``"x"``, ``"y"``, ``"z"``, optionally signed (``"-x"``,
``"+y"``); :func:`axis` turns them into ``(index, sign)`` pairs, which
:func:`aim_matrix` takes.
"""

import math

from maya import cmds
from maya.api import OpenMaya as om

_INDEX = {"x": 0, "y": 1, "z": 2}
# How close to parallel the aim and world up may be before another up is used.
_PARALLEL = 1e-6


def axis(text):
    """``"-y"`` -> ``(1, -1)``: the axis index and its sign."""
    text = str(text).strip().lower()
    sign = -1 if text.startswith("-") else 1
    letter = text.lstrip("+-")
    if letter not in _INDEX:
        raise ValueError(f"Unknown axis {text!r}; use x, y or z, optionally with - in front.")
    return _INDEX[letter], sign


def matrix(node, attr="worldMatrix"):
    return om.MMatrix(cmds.getAttr(f"{node}.{attr}[0]"))


def rotation(matrix):
    """Only the rotation of ``matrix`` (no scale, shear or translation)."""
    return om.MTransformationMatrix(matrix).rotation(asQuaternion=True).asMatrix()


def row(matrix, index):
    return om.MVector(matrix[index * 4], matrix[index * 4 + 1], matrix[index * 4 + 2])


def aim_matrix(direction, aim, up, world_up, fallback_up=None):
    """A rotation whose ``aim`` axis points along ``direction`` and whose
    ``up`` axis is as close to ``world_up`` as it can be. ``aim`` and ``up``
    are :func:`axis` pairs. If ``world_up`` is parallel to ``direction``,
    ``fallback_up`` is tried, then world Y, Z and X."""
    (aim_index, aim_sign), (up_index, up_sign) = aim, up
    direction = om.MVector(direction).normalize()
    candidates = [om.MVector(world_up)] + ([om.MVector(fallback_up)] if fallback_up is not None else [])
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


def _euler_matrix(node, attr, order=0):
    values = [math.radians(v) for v in cmds.getAttr(f"{node}.{attr}")[0]]
    return om.MEulerRotation(values, order).asMatrix()


def _set_joint_orient(joint, matrix):
    euler = om.MTransformationMatrix(matrix).rotation()
    cmds.setAttr(f"{joint}.jointOrient", *(math.degrees(a) for a in (euler.x, euler.y, euler.z)))


def set_world_rotation(joint, world, keep_rotate=False):
    """Turn ``joint`` to the world rotation ``world`` through its joint
    orient. Unless ``keep_rotate``, its rotate and rotate axis become zero."""
    if not keep_rotate:
        cmds.setAttr(f"{joint}.rotate", 0, 0, 0)
        cmds.setAttr(f"{joint}.rotateAxis", 0, 0, 0)
    local = rotation(rotation(world) * rotation(matrix(joint, "parentMatrix")).inverse())
    order = cmds.getAttr(f"{joint}.rotateOrder")
    current = _euler_matrix(joint, "rotateAxis") * _euler_matrix(joint, "rotate", order)
    _set_joint_orient(joint, current.inverse() * local)
