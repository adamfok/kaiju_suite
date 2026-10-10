import pytest
from maya import cmds

from kaiju_suite import registry
from kaiju_suite.tools.offset_snap import logic


def _world_matrix(node):
    return cmds.xform(node, query=True, worldSpace=True, matrix=True)


def _assert_matrix(got, want):
    assert got == pytest.approx(want, abs=1e-5)


def _local_is_zero(node):
    assert cmds.getAttr(f"{node}.translate")[0] == pytest.approx((0, 0, 0), abs=1e-5)
    assert cmds.getAttr(f"{node}.rotate")[0] == pytest.approx((0, 0, 0), abs=1e-5)
    assert cmds.getAttr(f"{node}.scale")[0] == pytest.approx((1, 1, 1), abs=1e-5)


def _placed(name="ctrl", parent=None):
    node = cmds.createNode("transform", name=name, parent=parent) if parent else cmds.createNode("transform", name=name)
    cmds.xform(node, translation=(1, 2, 3), rotation=(10, 20, 30), scale=(2, 2, 2))
    return cmds.ls(node, long=True)[0]


def _undo():
    cmds.undo()


# -- registration ---------------------------------------------------------------


def test_tool_is_registered_under_rigging():
    found = {tool["name"]: tool for tool in registry.discover()}

    assert found["Offset & Snap Tool"]["category"] == "Rigging"
    assert callable(found["Offset & Snap Tool"]["launch"])


# -- names ----------------------------------------------------------------------


def test_group_name_fills_in_the_node_name():
    assert logic.group_name("{name}_zero", "|grp|L_arm_ctrl", 1) == "L_arm_ctrl_zero"


def test_group_name_numbers_hashes_by_level():
    assert logic.group_name("{name}_grp##", "ctrl", 2) == "ctrl_grp02"


def test_group_name_without_hashes_gets_no_number():
    assert logic.group_name("{name}_offset", "ctrl", 3) == "ctrl_offset"


def test_group_name_strips_namespaces():
    assert logic.group_name("{name}_zero", "|rig:ctrl", 1) == "ctrl_zero"


# -- offset groups --------------------------------------------------------------


def test_offset_group_takes_the_node_world_transform(new_scene):
    node = _placed()
    before = _world_matrix(node)

    result = logic.add_offset_groups([node], ["{name}_zero"])

    group = result[0][0]
    assert cmds.ls(group)[0].endswith("ctrl_zero")
    node_now = cmds.ls("ctrl", long=True)[0]
    assert node_now == f"{group}|ctrl"
    _assert_matrix(_world_matrix(group), before)
    _assert_matrix(_world_matrix(node_now), before)
    _local_is_zero(node_now)


def test_offset_groups_stack_in_pattern_order(new_scene):
    parent = cmds.createNode("transform", name="rig")
    cmds.xform(parent, translation=(5, 0, 0), rotation=(0, 45, 0))
    node = _placed(parent=parent)
    before = _world_matrix(node)

    result = logic.add_offset_groups([node], ["{name}_zero", "{name}_offset"])

    zero, offset = result[0]
    assert zero == "|rig|ctrl_zero"
    assert offset == "|rig|ctrl_zero|ctrl_offset"
    assert cmds.ls("ctrl", long=True) == ["|rig|ctrl_zero|ctrl_offset|ctrl"]
    _assert_matrix(_world_matrix("ctrl"), before)
    _local_is_zero("ctrl")


def test_offset_groups_track_nodes_when_one_is_under_another(new_scene):
    upper = _placed("upper")
    child = _placed("child", parent=upper)
    before = {n: _world_matrix(n) for n in ("upper", "child")}

    logic.add_offset_groups([upper, child], ["{name}_zero"])

    assert cmds.ls("child", long=True) == ["|upper_zero|upper|child_zero|child"]
    for name, matrix in before.items():
        _assert_matrix(_world_matrix(name), matrix)


def test_offset_group_names_are_unique(new_scene):
    cmds.createNode("transform", name="ctrl_zero")
    node = _placed()

    result = logic.add_offset_groups([node], ["{name}_zero"])

    assert result[0][0] == "|ctrl_zero1"


def test_offset_group_on_a_joint_keeps_it_in_place(new_scene):
    cmds.select(clear=True)
    root = cmds.joint(name="root_jnt", position=(0, 0, 0))
    elbow = cmds.joint(name="elbow_jnt", position=(3, 1, 0))
    cmds.joint(root, edit=True, orientJoint="xyz", children=True)
    cmds.setAttr(f"{elbow}.rotate", 0, 0, 25)
    before = _world_matrix(elbow)

    logic.add_offset_groups([elbow], ["{name}_zero"])

    elbow = cmds.ls("elbow_jnt", long=True)[0]
    assert elbow == "|root_jnt|elbow_jnt_zero|elbow_jnt"
    _assert_matrix(_world_matrix(elbow), before)
    _local_is_zero(elbow)
    assert cmds.getAttr(f"{elbow}.jointOrient")[0] == pytest.approx((0, 0, 0), abs=1e-5)


def test_offset_group_unlocks_and_relocks_locked_channels(new_scene):
    node = _placed()
    cmds.setAttr(f"{node}.scale", lock=True)
    cmds.setAttr(f"{node}.translateX", lock=True)
    before = _world_matrix(node)

    logic.add_offset_groups([node], ["{name}_zero"])

    node = cmds.ls("ctrl", long=True)[0]
    _assert_matrix(_world_matrix(node), before)
    _local_is_zero(node)
    assert cmds.getAttr(f"{node}.scale", lock=True)
    assert cmds.getAttr(f"{node}.translateX", lock=True)
    assert not cmds.getAttr(f"{node}.translateY", lock=True)


def test_offset_groups_need_a_pattern(new_scene):
    node = _placed()

    with pytest.raises(ValueError):
        logic.add_offset_groups([node], ["  "])


def test_offset_groups_are_one_undo_step(new_scene):
    node = _placed()
    before = _world_matrix(node)

    logic.add_offset_groups([node], ["{name}_zero", "{name}_offset"])
    _undo()

    assert cmds.ls("ctrl", long=True) == ["|ctrl"]
    assert not cmds.objExists("ctrl_zero")
    assert not cmds.objExists("ctrl_offset")
    _assert_matrix(_world_matrix("ctrl"), before)


# -- matching -------------------------------------------------------------------


def test_match_position_moves_only_translation(new_scene):
    target = _placed("target")
    node = cmds.createNode("transform", name="node")

    logic.match_transforms([node], target, translate=True, rotate=False)

    assert cmds.xform(node, q=True, ws=True, t=True) == pytest.approx([1, 2, 3], abs=1e-5)
    assert cmds.getAttr(f"{node}.rotate")[0] == pytest.approx((0, 0, 0), abs=1e-5)


def test_match_rotation_moves_only_rotation(new_scene):
    target = _placed("target")
    node = cmds.createNode("transform", name="node")

    logic.match_transforms([node], target, translate=False, rotate=True)

    assert cmds.xform(node, q=True, ws=True, t=True) == pytest.approx([0, 0, 0], abs=1e-5)
    assert cmds.xform(node, q=True, ws=True, ro=True) == pytest.approx([10, 20, 30], abs=1e-4)
    assert cmds.getAttr(f"{node}.scale")[0] == pytest.approx((1, 1, 1), abs=1e-5)


def test_match_all_with_scale_matches_the_world_matrix(new_scene):
    target = _placed("target")
    parent = cmds.createNode("transform", name="parent")
    cmds.xform(parent, translation=(-4, 1, 0), rotation=(0, 0, 90))
    node = cmds.createNode("transform", name="node", parent=parent)

    logic.match_transforms([node], target, translate=True, rotate=True, scale=True)

    _assert_matrix(_world_matrix(node), _world_matrix(target))


def test_match_rotation_works_on_oriented_joints(new_scene):
    target = _placed("target")
    cmds.select(clear=True)
    joint = cmds.joint(name="jnt")
    cmds.setAttr(f"{joint}.jointOrient", 0, 90, 0)

    logic.match_transforms([joint], target, translate=True, rotate=True)

    assert cmds.xform(joint, q=True, ws=True, t=True) == pytest.approx([1, 2, 3], abs=1e-5)
    assert cmds.xform(joint, q=True, ws=True, ro=True) == pytest.approx([10, 20, 30], abs=1e-4)


def test_match_pivot_moves_the_pivot_not_the_node(new_scene):
    target = _placed("target")
    node = cmds.createNode("transform", name="node")

    logic.match_transforms([node], target, translate=False, rotate=False, pivot=True)

    assert cmds.xform(node, q=True, ws=True, rotatePivot=True) == pytest.approx([1, 2, 3], abs=1e-5)
    assert cmds.xform(node, q=True, ws=True, scalePivot=True) == pytest.approx([1, 2, 3], abs=1e-5)
    assert cmds.getAttr(f"{node}.translate")[0] == pytest.approx((0, 0, 0), abs=1e-5)


def test_match_skips_the_target_itself(new_scene):
    target = _placed("target")
    before = _world_matrix(target)

    logic.match_transforms([target], target)

    _assert_matrix(_world_matrix(target), before)


def test_match_is_one_undo_step(new_scene):
    target = _placed("target")
    a = cmds.createNode("transform", name="a")
    b = cmds.createNode("transform", name="b")

    logic.match_transforms([a, b], target, translate=True, rotate=True, scale=True)
    _undo()

    for node in (a, b):
        assert cmds.xform(node, q=True, ws=True, t=True) == pytest.approx([0, 0, 0], abs=1e-5)
        assert cmds.getAttr(f"{node}.rotate")[0] == pytest.approx((0, 0, 0), abs=1e-5)


# -- centroid -------------------------------------------------------------------


def test_centroid_of_vertices(new_scene):
    cube = cmds.polyCube(name="cube", width=2, height=2, depth=2)[0]
    cmds.move(10, 0, 0, cube)

    position = logic.centroid([f"{cube}.vtx[1]", f"{cube}.vtx[3]"])  # (1,-1,1) and (1,1,1)

    assert position == pytest.approx([11, 0, 1], abs=1e-5)


def test_centroid_of_a_face_uses_its_vertices(new_scene):
    cube = cmds.polyCube(name="cube", width=2, height=2, depth=2)[0]

    assert logic.centroid([f"{cube}.f[0]"]) == pytest.approx([0, 0, 1], abs=1e-5)


def test_centroid_counts_shared_vertices_once(new_scene):
    cube = cmds.polyCube(name="cube", width=2, height=2, depth=2)[0]

    # The same edge twice still averages just its two vertices, (-1,-1,1) and (1,-1,1).
    assert logic.centroid([f"{cube}.e[0]", f"{cube}.e[0]"]) == pytest.approx([0, -1, 1], abs=1e-5)


def test_centroid_of_objects_uses_their_pivots(new_scene):
    a = cmds.createNode("transform", name="a")
    b = cmds.createNode("transform", name="b")
    cmds.move(2, 0, 0, a)
    cmds.move(0, 4, 0, b)

    assert logic.centroid([a, b]) == pytest.approx([1, 2, 0], abs=1e-5)


def test_centroid_of_nothing_raises(new_scene):
    with pytest.raises(ValueError):
        logic.centroid([])


def test_place_locator_at_centroid(new_scene):
    a = cmds.createNode("transform", name="a")
    cmds.move(2, 4, 6, a)

    node = logic.place_at_centroid([a], kind="locator")

    assert cmds.listRelatives(node, shapes=True, type="locator")
    assert cmds.xform(node, q=True, ws=True, t=True) == pytest.approx([2, 4, 6], abs=1e-5)
    assert cmds.listRelatives(node, parent=True) is None


def test_place_joint_at_centroid_lands_in_the_world(new_scene):
    cube = cmds.polyCube(name="cube", width=2, height=2, depth=2)[0]
    cmds.select(f"{cube}.vtx[1]")  # a selected component must not affect where the joint goes

    node = logic.place_at_centroid([f"{cube}.vtx[1]", f"{cube}.vtx[3]"], kind="joint", name="mid_jnt")

    assert cmds.nodeType(node) == "joint"
    assert node == "|mid_jnt"
    assert cmds.xform(node, q=True, ws=True, t=True) == pytest.approx([1, 0, 1], abs=1e-5)


def test_place_rejects_unknown_kinds(new_scene):
    a = cmds.createNode("transform", name="a")

    with pytest.raises(ValueError):
        logic.place_at_centroid([a], kind="camera")


def test_place_at_centroid_is_one_undo_step(new_scene):
    a = cmds.createNode("transform", name="a")

    logic.place_at_centroid([a], kind="locator", name="pin")
    _undo()

    assert not cmds.objExists("pin")


# -- zero out -------------------------------------------------------------------


def test_zero_out_resets_transform_channels(new_scene):
    node = _placed()
    cmds.addAttr(node, longName="extra", keyable=True, defaultValue=0)
    cmds.setAttr(f"{node}.extra", 5)

    result = logic.zero_out([node])

    _local_is_zero(node)
    assert cmds.getAttr(f"{node}.extra") == 5  # only translate / rotate / scale
    assert result.changed == [node]
    assert result.skipped == []


def test_zero_out_skips_locked_and_connected_channels(new_scene):
    node = _placed()
    driver = cmds.createNode("transform", name="driver")
    cmds.setAttr(f"{driver}.translateX", 7)
    cmds.connectAttr(f"{driver}.translateX", f"{node}.translateY")
    cmds.setAttr(f"{node}.translateZ", lock=True)

    result = logic.zero_out([node])

    assert cmds.getAttr(f"{node}.translate")[0] == pytest.approx((0, 7, 3), abs=1e-5)
    assert cmds.getAttr(f"{node}.rotate")[0] == pytest.approx((0, 0, 0), abs=1e-5)
    assert sorted(result.skipped) == ["ctrl.translateY (connected)", "ctrl.translateZ (locked)"]


def test_zero_out_sets_keyed_channels(new_scene):
    node = _placed()
    cmds.setKeyframe(f"{node}.translateX")

    result = logic.zero_out([node])

    assert cmds.getAttr(f"{node}.translateX") == pytest.approx(0)
    assert result.skipped == []


def test_zero_out_ignores_non_keyable_channels(new_scene):
    node = _placed()
    cmds.setAttr(f"{node}.rotateX", keyable=False, channelBox=True)

    logic.zero_out([node])

    assert cmds.getAttr(f"{node}.rotateX") == pytest.approx(10)


def test_zero_out_is_one_undo_step(new_scene):
    a = _placed("a")
    b = _placed("b")

    logic.zero_out([a, b])
    _undo()

    for node in (a, b):
        assert cmds.getAttr(f"{node}.translate")[0] == pytest.approx((1, 2, 3), abs=1e-5)
        assert cmds.getAttr(f"{node}.scale")[0] == pytest.approx((2, 2, 2), abs=1e-5)
