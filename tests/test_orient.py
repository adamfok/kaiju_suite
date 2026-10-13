import pytest
from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.core import orient


def _row(matrix, index):
    return om.MVector(matrix[index * 4], matrix[index * 4 + 1], matrix[index * 4 + 2])


def _world(node):
    return om.MMatrix(cmds.xform(node, query=True, worldSpace=True, matrix=True))


@pytest.mark.parametrize("text, expected", [("x", (0, 1)), ("+y", (1, 1)), ("-z", (2, -1)), (" -X ", (0, -1))])
def test_axis_reads_signed_axes(text, expected):
    assert orient.axis(text) == expected


def test_axis_rejects_unknown_axes():
    with pytest.raises(ValueError):
        orient.axis("w")


def test_aim_matrix_points_the_aim_axis_and_turns_up_towards_world_up():
    matrix = orient.aim_matrix((1, 1, 0), orient.axis("x"), orient.axis("y"), om.MVector(0, 1, 0))

    aim = _row(matrix, 0)
    up = _row(matrix, 1)
    assert (aim - om.MVector(1, 1, 0).normalize()).length() < 1e-6
    assert abs(aim * up) < 1e-6
    assert up * om.MVector(0, 1, 0) > 0
    # Right handed: z = x ^ y.
    assert (_row(matrix, 2) - (aim ^ up)).length() < 1e-6


def test_aim_matrix_with_negative_axes():
    matrix = orient.aim_matrix((0, 0, 1), orient.axis("-y"), orient.axis("z"), om.MVector(1, 0, 0))

    assert (_row(matrix, 1) * -1 - om.MVector(0, 0, 1)).length() < 1e-6
    assert (_row(matrix, 2) - om.MVector(1, 0, 0)).length() < 1e-6


def test_aim_matrix_falls_back_when_aim_is_parallel_to_world_up():
    matrix = orient.aim_matrix((0, 1, 0), orient.axis("x"), orient.axis("y"), om.MVector(0, 1, 0))

    up = _row(matrix, 1)
    assert up.length() == pytest.approx(1.0)
    assert abs(up * om.MVector(0, 1, 0)) < 1e-6


def test_set_world_rotation_puts_it_in_the_joint_orient(new_scene):
    parent = cmds.joint(position=(0, 0, 0))
    cmds.setAttr(f"{parent}.rotate", 10, 20, 30)
    child = cmds.joint(position=(1, 2, 3))
    cmds.setAttr(f"{child}.rotate", 5, 5, 5)
    target = orient.aim_matrix((0, 0, 1), orient.axis("x"), orient.axis("y"), om.MVector(0, 1, 0))

    orient.set_world_rotation(child, target)

    assert cmds.getAttr(f"{child}.rotate")[0] == pytest.approx((0, 0, 0))
    world = _world(child)
    for i in range(3):
        assert (_row(world, i) - _row(target, i)).length() < 1e-5
