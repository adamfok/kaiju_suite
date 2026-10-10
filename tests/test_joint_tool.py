import pytest
from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.tools.joint_tool import logic

_AXES = {"x": 0, "y": 1, "z": 2}


def _long(name):
    return cmds.ls(name, long=True)[0]


def _world(node):
    return om.MVector(cmds.xform(node, query=True, worldSpace=True, translation=True))


def _matrix(node):
    return om.MMatrix(cmds.xform(node, query=True, worldSpace=True, matrix=True))


def _axis(node, axis):
    """``node``'s local ``axis`` ("x", "-y", ...) in world space, normalized."""
    sign = -1 if axis.startswith("-") else 1
    m = _matrix(node)
    row = _AXES[axis[-1]]
    return om.MVector(m[row * 4], m[row * 4 + 1], m[row * 4 + 2]).normalize() * sign


def _get(plug):
    value = cmds.getAttr(plug)
    return list(value[0]) if isinstance(value, list) else value


def _close(a, b, tol=1e-4):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def _arm(side="L"):
    """A bent shoulder-elbow-wrist chain with messy orientation: rotations
    on the joints and joint orients that don't aim anywhere."""
    cmds.select(clear=True)
    shoulder = cmds.joint(name=f"{side}_shoulder", position=(2, 10, 0))
    cmds.joint(name=f"{side}_elbow", position=(5, 10, -1))
    cmds.joint(name=f"{side}_wrist", position=(8, 11, 0))
    cmds.select(clear=True)
    cmds.setAttr(f"{side}_shoulder.rotate", 10, 20, 30)
    cmds.setAttr(f"{side}_elbow.jointOrient", 5, -15, 40)
    cmds.setAttr(f"{side}_wrist.jointOrient", 30, 0, 12)
    return [_long(f"{side}_{n}") for n in ("shoulder", "elbow", "wrist")]


def _state(nodes):
    return [
        (_matrix(n), _get(f"{n}.jointOrient"), _get(f"{n}.rotate"), cmds.listRelatives(n, parent=True))
        for n in nodes
    ]


# -- orient -----------------------------------------------------------------


@pytest.mark.parametrize("aim,up,world_up", [("x", "y", "y"), ("x", "z", "-z"), ("y", "z", "z"), ("-x", "y", "y")])
def test_orient_aims_at_the_child_and_ups_towards_world_up(new_scene, aim, up, world_up):
    joints = _arm()
    positions = [_world(j) for j in joints]

    logic.orient([joints[0]], aim=aim, up=up, world_up=world_up)

    world_up_vector = _axis_vector(world_up)
    for joint, child in zip(joints, joints[1:]):
        to_child = (_world(child) - _world(joint)).normalize()
        assert (_axis(joint, aim) - to_child).length() < 1e-4
        assert abs(_axis(joint, up) * to_child) < 1e-4
        assert _axis(joint, up) * world_up_vector > 0
        assert _close(_get(f"{joint}.rotate"), (0, 0, 0))
    for joint, position in zip(joints, positions):
        assert (_world(joint) - position).length() < 1e-4


def _axis_vector(axis):
    vector = [0.0, 0.0, 0.0]
    vector[_AXES[axis[-1]]] = -1.0 if axis.startswith("-") else 1.0
    return om.MVector(vector)


def test_orient_zeroes_the_end_joint_orient_by_default(new_scene):
    shoulder, elbow, wrist = _arm()

    logic.orient([shoulder])

    assert _close(_get(f"{wrist}.jointOrient"), (0, 0, 0))
    assert _close(_get(f"{wrist}.rotate"), (0, 0, 0))
    assert (_axis(wrist, "x") - _axis(elbow, "x")).length() < 1e-4


def test_orient_can_leave_the_end_joint_as_it_was(new_scene):
    shoulder, elbow, wrist = _arm()
    before = _matrix(wrist)

    logic.orient([shoulder], zero_end=False)

    assert _matrix(wrist).isEquivalent(before, 1e-4)


def test_orient_without_children_leaves_the_children_where_they_were(new_scene):
    shoulder, elbow, wrist = _arm()
    before = {j: _matrix(j) for j in (elbow, wrist)}

    logic.orient([shoulder], children=False)

    to_elbow = (_world(elbow) - _world(shoulder)).normalize()
    assert (_axis(shoulder, "x") - to_elbow).length() < 1e-4
    for joint, matrix in before.items():
        assert _matrix(joint).isEquivalent(matrix, 1e-4)


def test_orient_keeps_non_joint_children_in_place(new_scene):
    shoulder, elbow, wrist = _arm()
    loc = cmds.spaceLocator(name="elbow_loc")[0]
    cmds.parent(loc, elbow)
    cmds.setAttr(f"{loc}.translate", 0, 2, 0)
    loc = _long("elbow_loc")
    before = _matrix(loc)

    logic.orient([shoulder])

    assert _matrix(loc).isEquivalent(before, 1e-4)


def test_orient_rejects_the_same_aim_and_up_axis(new_scene):
    shoulder = _arm()[0]
    before = _state([shoulder])

    with pytest.raises(ValueError):
        logic.orient([shoulder], aim="x", up="-x")
    with pytest.raises(ValueError):
        logic.orient([shoulder], aim="q")

    assert _state([shoulder])[0][1] == before[0][1]


def test_orient_is_one_undo_step(new_scene):
    joints = _arm()
    before = _state(joints)
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    logic.orient([joints[0]])
    cmds.undo()

    for (matrix, orient, rotate, parent), after in zip(before, _state(joints)):
        assert matrix.isEquivalent(after[0], 1e-4)
        assert _close(orient, after[1]) and _close(rotate, after[2])


# -- zero end orients -------------------------------------------------------


def test_zero_end_orients_only_touches_end_joints(new_scene):
    shoulder, elbow, wrist = _arm()
    elbow_orient = _get(f"{elbow}.jointOrient")
    wrist_position = _world(wrist)

    changed = logic.zero_end_orients([shoulder])

    assert changed == [wrist]
    assert _close(_get(f"{wrist}.jointOrient"), (0, 0, 0))
    assert _close(_get(f"{elbow}.jointOrient"), elbow_orient)
    assert (_world(wrist) - wrist_position).length() < 1e-4


def test_zero_end_orients_is_one_undo_step(new_scene):
    shoulder, elbow, wrist = _arm()
    cmds.setAttr(f"{wrist}.rotate", 4, 5, 6)
    before = _state([wrist])
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    logic.zero_end_orients([shoulder])
    cmds.undo()

    after = _state([wrist])
    assert _close(before[0][1], after[0][1]) and _close(before[0][2], after[0][2])


# -- mirror -----------------------------------------------------------------


def test_mirror_makes_the_opposite_side_with_swapped_names(new_scene):
    joints = _arm()
    logic.orient([joints[0]])

    roots = logic.mirror([joints[0]])

    assert roots == [_long("R_shoulder")]
    for name in ("shoulder", "elbow", "wrist"):
        left, right = _world(f"L_{name}"), _world(f"R_{name}")
        assert (right - om.MVector(-left.x, left.y, left.z)).length() < 1e-4
    assert cmds.listRelatives("R_wrist", parent=True) == ["R_elbow"]


def test_mirror_behavior_flips_every_axis(new_scene):
    joints = _arm()
    logic.orient([joints[0]])

    logic.mirror([joints[0]], behavior=True)

    for axis in ("x", "y", "z"):
        left = _axis("L_shoulder", axis)
        assert (_axis("R_shoulder", axis) - om.MVector(left.x, -left.y, -left.z)).length() < 1e-4


def test_mirror_orientation_keeps_the_world_orientation(new_scene):
    joints = _arm()
    logic.orient([joints[0]])

    logic.mirror([joints[0]], behavior=False)

    for axis in ("x", "y", "z"):
        assert (_axis("R_shoulder", axis) - _axis("L_shoulder", axis)).length() < 1e-4


def test_mirror_handles_other_side_styles(new_scene):
    cmds.select(clear=True)
    root = cmds.joint(name="arm_l_jnt", position=(1, 0, 0))
    cmds.joint(name="hand_l_jnt", position=(2, 0, 0))
    cmds.select(clear=True)

    logic.mirror([_long(root)])

    assert cmds.objExists("arm_r_jnt") and cmds.objExists("hand_r_jnt")


def test_mirror_only_mirrors_the_top_of_a_selected_hierarchy(new_scene):
    joints = _arm()

    roots = logic.mirror(joints)

    assert roots == [_long("R_shoulder")]
    assert len(cmds.ls("R_*", type="joint")) == 3


def test_mirror_refuses_when_the_opposite_name_is_taken(new_scene):
    joints = _arm()
    cmds.createNode("transform", name="R_elbow")
    count = len(cmds.ls(type="joint"))

    with pytest.raises(ValueError, match="R_elbow"):
        logic.mirror([joints[0]])

    assert len(cmds.ls(type="joint")) == count


def test_mirror_is_one_undo_step(new_scene):
    joints = _arm()
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    logic.mirror([joints[0]])
    cmds.undo()

    assert cmds.ls("R_*") == []
    assert sorted(cmds.ls(type="joint", long=True)) == sorted(joints)


# -- insert -----------------------------------------------------------------


def test_insert_adds_evenly_spaced_joints_before_the_child(new_scene):
    shoulder, elbow, wrist = _arm()
    logic.orient([shoulder])
    start, end = _world(shoulder), _world(elbow)
    wrist_before = _matrix(wrist)

    new = logic.insert_joints(shoulder, 3)

    assert len(new) == 3
    for i, joint in enumerate(new, 1):
        expected = start + (end - start) * (i / 4.0)
        assert (_world(joint) - expected).length() < 1e-4
        assert (_axis(joint, "x") - _axis(shoulder, "x")).length() < 1e-4
        assert cmds.getAttr(f"{joint}.radius") == cmds.getAttr(f"{shoulder}.radius")
    assert cmds.listRelatives(new[0], parent=True, fullPath=True) == [shoulder]
    for parent, child in zip(new, new[1:]):
        assert cmds.listRelatives(child, parent=True, fullPath=True) == [parent]
    elbow_now = _long("L_elbow")
    assert cmds.listRelatives(elbow_now, parent=True, fullPath=True) == [new[-1]]
    assert (_world(elbow_now) - end).length() < 1e-4
    assert _matrix(_long("L_wrist")).isEquivalent(wrist_before, 1e-4)
    assert [cmds.ls(j)[0] for j in new] == ["L_shoulder_split_01", "L_shoulder_split_02", "L_shoulder_split_03"]
    assert cmds.listConnections(f"{new[1]}.inverseScale", source=True) == ["L_shoulder_split_01"]


def test_insert_into_a_rotated_joint_keeps_the_child_in_place(new_scene):
    shoulder, elbow, wrist = _arm()  # not oriented: shoulder has rotate values
    before = _matrix(elbow)

    logic.insert_joints(shoulder, 2)

    assert _matrix(_long("L_elbow")).isEquivalent(before, 1e-4)


def test_insert_checks_its_input(new_scene):
    shoulder, elbow, wrist = _arm()

    with pytest.raises(ValueError):
        logic.insert_joints(wrist, 2)  # no child joint
    with pytest.raises(ValueError):
        logic.insert_joints(shoulder, 0)
    with pytest.raises(ValueError):
        logic.insert_joints(shoulder, 2, child=wrist)  # not a direct child

    assert len(cmds.ls(type="joint")) == 3


def test_insert_is_one_undo_step(new_scene):
    shoulder, elbow, wrist = _arm()
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    logic.insert_joints(shoulder, 3)
    cmds.undo()

    assert sorted(cmds.ls(type="joint", long=True)) == sorted([shoulder, elbow, wrist])


def test_insert_below_each_joint_is_one_undo_step(new_scene):
    shoulder, elbow, wrist = _arm()
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    new = logic.insert_below([shoulder, elbow], 2)

    assert len(new) == 4
    assert cmds.listRelatives(_long("L_wrist"), parent=True) == ["L_elbow_split_02"]
    assert cmds.listRelatives(_long("L_elbow"), parent=True) == ["L_shoulder_split_02"]
    cmds.undo()
    assert sorted(cmds.ls(type="joint", long=True)) == sorted([shoulder, elbow, wrist])


def test_insert_below_checks_every_joint_first(new_scene):
    shoulder, elbow, wrist = _arm()

    with pytest.raises(ValueError, match="L_wrist"):
        logic.insert_below([shoulder, wrist], 2)

    assert len(cmds.ls(type="joint")) == 3


# -- display ----------------------------------------------------------------


def test_toggle_local_axis_turns_all_on_then_all_off(new_scene):
    joints = _arm()
    cmds.setAttr(f"{joints[1]}.displayLocalAxis", True)

    assert logic.toggle_local_axis(joints) is True
    assert all(cmds.getAttr(f"{j}.displayLocalAxis") for j in joints)
    assert logic.toggle_local_axis(joints) is False
    assert not any(cmds.getAttr(f"{j}.displayLocalAxis") for j in joints)


def test_toggle_local_axis_can_include_the_hierarchy(new_scene):
    joints = _arm()

    logic.toggle_local_axis([joints[0]], hierarchy=True)

    assert all(cmds.getAttr(f"{j}.displayLocalAxis") for j in joints)


def test_toggle_local_axis_is_one_undo_step(new_scene):
    joints = _arm()
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    logic.toggle_local_axis(joints)
    cmds.undo()

    assert not any(cmds.getAttr(f"{j}.displayLocalAxis") for j in joints)


def test_set_radius(new_scene):
    joints = _arm()

    assert logic.set_radius([joints[0]], 2.5) == [joints[0]]
    assert cmds.getAttr(f"{joints[0]}.radius") == 2.5
    assert cmds.getAttr(f"{joints[1]}.radius") == 1.0

    logic.set_radius([joints[0]], 0.5, hierarchy=True)
    assert all(cmds.getAttr(f"{j}.radius") == 0.5 for j in joints)

    with pytest.raises(ValueError):
        logic.set_radius(joints, 0)


def test_set_radius_is_one_undo_step(new_scene):
    joints = _arm()
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    logic.set_radius(joints, 3.0, hierarchy=True)
    cmds.undo()

    assert all(cmds.getAttr(f"{j}.radius") == 1.0 for j in joints)


def test_non_joints_are_ignored(new_scene):
    joints = _arm()
    group = cmds.createNode("transform", name="grp")

    assert logic.set_radius([group, joints[0]], 2.0) == [joints[0]]
