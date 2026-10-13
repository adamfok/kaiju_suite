import pytest
from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite import registry
from kaiju_suite.tools.guide_tool import logic

_AXES = {"x": 0, "y": 1, "z": 2}


def _pos(node):
    return om.MVector(cmds.xform(node, query=True, worldSpace=True, translation=True))


def _move(node, *xyz):
    cmds.xform(node, worldSpace=True, translation=xyz)


def _axis(node, axis):
    """``node``'s local ``axis`` ("x", "-y", ...) in world space, normalized."""
    sign = -1 if axis.startswith("-") else 1
    m = om.MMatrix(cmds.xform(node, query=True, worldSpace=True, matrix=True))
    row = _AXES[axis[-1]]
    return om.MVector(m[row * 4], m[row * 4 + 1], m[row * 4 + 2]).normalize() * sign


def _uuid(node):
    return cmds.ls(node, uuid=True)[0]


def _normal(group):
    found = logic.guides(group)
    start, end, up = _pos(found["chain"][0]), _pos(found["chain"][-1]), _pos(found["up"])
    return ((end - start) ^ (up - start)).normalize()


def _bent_arm():
    """Guides for an arm with three middle guides dragged off the plane,
    one of them so far that its segment points back towards the up guide."""
    group = logic.create_guides("arm", 3, start=(0, 0, 0), end=(12, 0, 0))
    found = logic.guides(group)
    _move(found["up"], 6, 5, 0)
    mids = found["chain"][1:-1]
    _move(mids[0], 3, -2, 1.5)
    _move(mids[1], 6, -3, -4)
    _move(mids[2], 7, 4, 2)
    return group


# -- planar_positions ---------------------------------------------------------


def test_planar_positions_keep_start_and_end():
    points = [(0, 0, 0), (5, 1, 3), (10, 0, 0)]

    result = logic.planar_positions(points, (5, 5, 0))

    assert (result[0] - om.MVector(0, 0, 0)).length() < 1e-6
    assert (result[-1] - om.MVector(10, 0, 0)).length() < 1e-6


def test_planar_positions_project_middle_points_onto_the_plane():
    # Start, end and up lie in the XY plane, so Z is dropped.
    points = [(0, 0, 0), (3, 1, 4), (6, -1, -2), (10, 0, 0)]

    result = logic.planar_positions(points, (5, 5, 0))

    assert (result[1] - om.MVector(3, 1, 0)).length() < 1e-6
    assert (result[2] - om.MVector(6, -1, 0)).length() < 1e-6


def test_planar_positions_in_a_tilted_plane():
    start, end, up = om.MVector(1, 2, 3), om.MVector(4, 8, -1), om.MVector(0, 5, 5)
    normal = ((end - start) ^ (up - start)).normalize()

    result = logic.planar_positions([start, (7, -3, 2), (2, 2, 9), end], up)

    for point in result:
        assert abs((point - start) * normal) < 1e-6


def test_planar_positions_reject_an_up_in_line_with_the_chain():
    with pytest.raises(ValueError, match="in line"):
        logic.planar_positions([(0, 0, 0), (5, 1, 0), (10, 0, 0)], (20, 0, 0))


def test_planar_positions_reject_start_on_end():
    with pytest.raises(ValueError):
        logic.planar_positions([(1, 1, 1), (1, 1, 1)], (0, 5, 0))


def test_planar_positions_reject_two_joints_on_the_same_spot():
    # Straight above the start guide: it lands on the start.
    with pytest.raises(ValueError, match="same spot"):
        logic.planar_positions([(0, 0, 0), (0, 0, 5), (10, 0, 0)], (5, 5, 0))


# -- create_guides ------------------------------------------------------------


def test_create_guides_names_them_and_lines_them_up(new_scene):
    group = logic.create_guides("arm", 2, start=(0, 0, 0), end=(9, 0, 0))

    assert cmds.ls(group)[0] == "arm_guides_grp"
    found = logic.guides(group)
    assert [cmds.ls(n)[0] for n in found["chain"]] == [
        "arm_start_guide",
        "arm_mid_01_guide",
        "arm_mid_02_guide",
        "arm_end_guide",
    ]
    assert cmds.ls(found["up"])[0] == "arm_up_guide"
    for node, x in zip(found["chain"], (0, 3, 6, 9)):
        assert (_pos(node) - om.MVector(x, 0, 0)).length() < 1e-6


def test_create_guides_puts_the_up_guide_off_the_chain(new_scene):
    group = logic.create_guides("arm", 1, start=(0, 0, 0), end=(10, 0, 0))

    up = _pos(logic.guides(group)["up"])
    assert ((om.MVector(10, 0, 0)) ^ up).length() > 1.0


def test_create_guides_with_no_middle_guides(new_scene):
    group = logic.create_guides("spine", 0)

    assert len(logic.guides(group)["chain"]) == 2


def test_guides_can_only_be_moved(new_scene):
    group = logic.create_guides("arm", 1)

    found = logic.guides(group)
    for node in found["chain"] + [found["up"]]:
        for attr in ("rx", "ry", "rz", "sx", "sy", "sz"):
            assert cmds.getAttr(f"{node}.{attr}", lock=True), (node, attr)
            assert not cmds.getAttr(f"{node}.{attr}", keyable=True), (node, attr)
            assert not cmds.getAttr(f"{node}.{attr}", channelBox=True), (node, attr)
        for attr in ("tx", "ty", "tz"):
            assert not cmds.getAttr(f"{node}.{attr}", lock=True)
            assert cmds.getAttr(f"{node}.{attr}", keyable=True)


def test_display_curve_follows_the_guides(new_scene):
    group = logic.create_guides("arm", 1, start=(0, 0, 0), end=(10, 0, 0))
    found = logic.guides(group)

    _move(found["chain"][1], 4, 3, 2)
    cmds.move(1, 1, 1, group, relative=True)

    chain_curve, up_curve = logic.display_curves(group)
    assert cmds.getAttr(f"{chain_curve}.template")
    for i, node in enumerate(found["chain"]):
        assert (om.MVector(cmds.pointPosition(f"{chain_curve}.cv[{i}]")) - _pos(node)).length() < 1e-5
    assert (om.MVector(cmds.pointPosition(f"{up_curve}.cv[1]")) - _pos(found["up"])).length() < 1e-5


def test_guides_are_found_after_renaming(new_scene):
    group = logic.create_guides("arm", 1)
    mid = logic.guides(group)["chain"][1]

    cmds.rename(mid, "elbow_guide")

    assert cmds.ls(logic.guides(group)["chain"][1])[0] == "elbow_guide"


def test_guide_group_from_a_guide_the_group_or_a_built_joint(new_scene):
    group = logic.create_guides("arm", 1)
    joints = logic.build_joints(group)

    for node in (group, logic.guides(group)["chain"][1], logic.guides(group)["up"], joints[1]):
        assert logic.guide_group(node) == group


def test_guide_group_rejects_other_nodes(new_scene):
    cube = cmds.polyCube()[0]

    with pytest.raises(ValueError):
        logic.guide_group(cube)


def test_find_group_uses_the_selection(new_scene):
    arm = logic.create_guides("arm", 1)
    leg = logic.create_guides("leg", 1)

    assert logic.find_group([logic.guides(leg)["up"]]) == leg
    assert logic.find_group([arm]) == arm


def test_find_group_with_nothing_selected_uses_the_only_group(new_scene):
    arm = logic.create_guides("arm", 1)

    assert logic.find_group([]) == arm


def test_find_group_with_nothing_selected_and_several_groups(new_scene):
    logic.create_guides("arm", 1)
    logic.create_guides("leg", 1)

    with pytest.raises(ValueError, match="Select"):
        logic.find_group([])


def test_find_group_with_no_guides_in_the_scene(new_scene):
    with pytest.raises(ValueError, match="No guides"):
        logic.find_group([])


def test_find_group_rejects_guides_of_two_chains(new_scene):
    arm = logic.create_guides("arm", 1)
    leg = logic.create_guides("leg", 1)

    with pytest.raises(ValueError, match="one chain"):
        logic.find_group([arm, leg])


@pytest.mark.parametrize("name", ["", "1arm", "my arm"])
def test_create_guides_rejects_bad_names(new_scene, name):
    with pytest.raises(ValueError):
        logic.create_guides(name, 1)


def test_create_guides_rejects_a_negative_count(new_scene):
    with pytest.raises(ValueError):
        logic.create_guides("arm", -1)


def test_create_guides_rejects_start_on_end(new_scene):
    with pytest.raises(ValueError):
        logic.create_guides("arm", 1, start=(1, 1, 1), end=(1, 1, 1))


def test_create_guides_refuses_a_taken_name_and_changes_nothing(new_scene):
    cmds.createNode("transform", name="arm_mid_01_guide")
    before = set(cmds.ls())

    with pytest.raises(ValueError, match="arm_mid_01_guide"):
        logic.create_guides("arm", 1)

    assert set(cmds.ls()) == before


def test_create_guides_is_one_undo_step(new_scene):
    before = set(cmds.ls())
    logic.create_guides("arm", 2)

    cmds.undo()

    assert set(cmds.ls()) == before


# -- build_joints -------------------------------------------------------------


def test_build_joints_makes_a_named_chain(new_scene):
    group = logic.create_guides("arm", 2)

    joints = logic.build_joints(group)

    assert [cmds.ls(j)[0] for j in joints] == ["arm_01_jnt", "arm_02_jnt", "arm_03_jnt", "arm_04_jnt"]
    assert cmds.listRelatives(joints[0], parent=True) is None
    for parent, child in zip(joints, joints[1:]):
        assert cmds.listRelatives(child, parent=True, fullPath=True)[0] == parent
    assert logic.joints(group) == joints


def test_built_chain_is_planar_and_ends_on_the_end_guide(new_scene):
    group = _bent_arm()
    found = logic.guides(group)
    start = _pos(found["chain"][0])
    normal = _normal(group)

    joints = logic.build_joints(group)

    for joint in joints:
        assert abs((_pos(joint) - start) * normal) < 1e-5
    assert (_pos(joints[0]) - start).length() < 1e-5
    assert (_pos(joints[-1]) - _pos(found["chain"][-1])).length() < 1e-5


def test_built_joints_aim_down_the_chain_and_bend_around_the_plane_normal(new_scene):
    group = _bent_arm()
    normal = _normal(group)

    joints = logic.build_joints(group, aim="x", up="y")

    for joint, child in zip(joints, joints[1:]):
        assert (_axis(joint, "x") - (_pos(child) - _pos(joint)).normalize()).length() < 1e-4
        assert (_axis(joint, "z") - normal).length() < 1e-4
        assert cmds.getAttr(f"{joint}.rotate")[0] == pytest.approx((0, 0, 0))


def test_built_joints_up_axis_points_towards_the_up_guide(new_scene):
    group = logic.create_guides("arm", 1, start=(0, 0, 0), end=(10, 0, 0))
    found = logic.guides(group)
    _move(found["up"], 5, 0, -6)

    joints = logic.build_joints(group, aim="x", up="y")

    assert (_axis(joints[0], "y") - om.MVector(0, 0, -1)).length() < 1e-4


def test_built_joints_with_other_axes(new_scene):
    group = _bent_arm()
    normal = _normal(group)

    joints = logic.build_joints(group, aim="-y", up="z")

    for joint, child in zip(joints, joints[1:]):
        assert (_axis(joint, "-y") - (_pos(child) - _pos(joint)).normalize()).length() < 1e-4
        # The third axis (x here) is the same plane normal for every joint.
        assert (_axis(joint, "-x") - normal).length() < 1e-4


def test_end_joint_lines_up_with_its_parent(new_scene):
    joints = logic.build_joints(_bent_arm())

    end = joints[-1]
    assert cmds.getAttr(f"{end}.jointOrient")[0] == pytest.approx((0, 0, 0), abs=1e-6)
    assert cmds.getAttr(f"{end}.rotate")[0] == pytest.approx((0, 0, 0))
    for axis in ("x", "y", "z"):
        assert (_axis(end, axis) - _axis(joints[-2], axis)).length() < 1e-5


def test_build_joints_rejects_the_same_aim_and_up_axis(new_scene):
    group = logic.create_guides("arm", 1)

    with pytest.raises(ValueError):
        logic.build_joints(group, aim="x", up="-x")
    assert not cmds.ls(type="joint")


def test_build_joints_with_up_in_line_changes_nothing(new_scene):
    group = logic.create_guides("arm", 1, start=(0, 0, 0), end=(10, 0, 0))
    _move(logic.guides(group)["up"], 20, 0, 0)

    with pytest.raises(ValueError, match="in line"):
        logic.build_joints(group)
    assert not cmds.ls(type="joint")


def test_build_joints_refuses_names_taken_by_other_joints(new_scene):
    group = logic.create_guides("arm", 1)
    cmds.createNode("joint", name="arm_02_jnt")

    with pytest.raises(ValueError, match="arm_02_jnt"):
        logic.build_joints(group)
    assert len(cmds.ls(type="joint")) == 1


def test_build_joints_is_one_undo_step(new_scene):
    group = logic.create_guides("arm", 2)
    before = set(cmds.ls())

    logic.build_joints(group)
    cmds.undo()

    assert set(cmds.ls()) == before
    assert logic.joints(group) == []


# -- building again updates the chain -----------------------------------------


def test_building_again_moves_the_same_joints(new_scene):
    group = logic.create_guides("arm", 2, start=(0, 0, 0), end=(9, 0, 0))
    joints = logic.build_joints(group)
    uuids = [_uuid(j) for j in joints]
    cmds.rename(joints[1], "elbow_jnt")
    child = cmds.spaceLocator(name="extra")[0]
    cmds.parent(child, cmds.ls(uuids[2], long=True)[0])
    found = logic.guides(group)
    _move(found["chain"][1], 3, 2, 1)
    _move(found["chain"][-1], 9, 0, 4)
    normal = _normal(group)

    rebuilt = logic.build_joints(group)

    assert [_uuid(j) for j in rebuilt] == uuids
    assert cmds.ls(rebuilt[1])[0] == "elbow_jnt"
    assert "extra" in cmds.listRelatives(rebuilt[2], children=True)
    assert len(cmds.ls(type="joint")) == 4
    assert (_pos(rebuilt[-1]) - om.MVector(9, 0, 4)).length() < 1e-5
    for joint, nxt in zip(rebuilt, rebuilt[1:]):
        assert abs((_pos(joint) - _pos(rebuilt[0])) * normal) < 1e-5
        assert (_axis(joint, "x") - (_pos(nxt) - _pos(joint)).normalize()).length() < 1e-4
        assert (_axis(joint, "z") - normal).length() < 1e-4


def test_undo_puts_an_updated_chain_back(new_scene):
    group = logic.create_guides("arm", 1, start=(0, 0, 0), end=(10, 0, 0))
    joints = logic.build_joints(group)
    before = [_pos(j) for j in joints]
    _move(logic.guides(group)["chain"][-1], 10, 5, 0)

    logic.build_joints(group)
    cmds.undo()

    for joint, position in zip(joints, before):
        assert (_pos(joint) - position).length() < 1e-5


def test_building_again_with_a_different_guide_count_changes_nothing(new_scene):
    group = logic.create_guides("arm", 1)
    joints = logic.build_joints(group)
    cmds.delete(joints[-1])
    before = [_pos(j) for j in logic.joints(group)]

    with pytest.raises(ValueError, match="2 joints"):
        logic.build_joints(group)

    assert [_pos(j) for j in logic.joints(group)] == before
    assert len(cmds.ls(type="joint")) == 2


# -- live preview: a disc per joint, and the plane ----------------------------


def _rows(node):
    return [_axis(node, axis) for axis in ("x", "y", "z")]


def _same_frame(a, b):
    assert (_pos(a) - _pos(b)).length() < 1e-4, (a, b)
    for row_a, row_b in zip(_rows(a), _rows(b)):
        assert (row_a - row_b).length() < 1e-4, (a, b)


def _planar(group):
    found = logic.guides(group)
    return logic.planar_positions([_pos(g) for g in found["chain"]], _pos(found["up"]))


def test_previews_sit_where_the_joints_will_land(new_scene):
    group = _bent_arm()

    previews = logic.previews(group)

    assert len(previews) == 5
    for preview, position in zip(previews, _planar(group)):
        assert (_pos(preview) - position).length() < 1e-4


def test_previews_match_the_built_joints(new_scene):
    group = _bent_arm()

    joints = logic.build_joints(group)

    for preview, joint in zip(logic.previews(group), joints):
        _same_frame(preview, joint)


def test_previews_follow_the_guides(new_scene):
    group = _bent_arm()
    previews = logic.previews(group)
    found = logic.guides(group)

    _move(found["chain"][2], 5, 6, 7)
    _move(found["chain"][-1], 11, 3, -2)
    _move(found["up"], 4, 2, 8)
    cmds.move(1, 2, 3, group, relative=True)
    joints = logic.build_joints(group)

    for preview, joint in zip(previews, joints):
        _same_frame(preview, joint)


def test_previews_follow_the_axes(new_scene):
    group = _bent_arm()

    logic.set_axes(group, aim="-y", up="z")
    other = logic.create_guides("copy", 3)
    for source, target in zip(logic.guides(group)["chain"] + [logic.guides(group)["up"]],
                              logic.guides(other)["chain"] + [logic.guides(other)["up"]]):
        _move(target, *_pos(source))
    joints = logic.build_joints(other, aim="-y", up="z")

    for preview, joint in zip(logic.previews(group), joints):
        _same_frame(preview, joint)


def test_building_joints_sets_the_preview_axes(new_scene):
    group = _bent_arm()

    joints = logic.build_joints(group, aim="z", up="-x")

    for preview, joint in zip(logic.previews(group), joints):
        _same_frame(preview, joint)


def test_set_axes_rejects_the_same_aim_and_up_axis(new_scene):
    group = logic.create_guides("arm", 1)

    with pytest.raises(ValueError):
        logic.set_axes(group, aim="y", up="-y")


def test_set_axes_is_one_undo_step(new_scene):
    group = _bent_arm()
    before = [_rows(p) for p in logic.previews(group)]

    logic.set_axes(group, aim="z", up="x")
    cmds.undo()

    for preview, rows in zip(logic.previews(group), before):
        for row, old in zip(_rows(preview), rows):
            assert (row - old).length() < 1e-4


def test_previews_show_their_local_axis_and_cannot_be_selected(new_scene):
    group = logic.create_guides("arm", 1)

    for preview in logic.previews(group):
        assert cmds.getAttr(f"{preview}.displayLocalAxis")
        disc = cmds.listRelatives(preview, children=True, type="transform", fullPath=True)[0]
        assert cmds.getAttr(f"{disc}.overrideEnabled")
        assert cmds.getAttr(f"{disc}.overrideDisplayType") == 2  # reference
        assert cmds.listRelatives(disc, shapes=True, type="nurbsSurface")


@pytest.mark.parametrize("aim, up", [("x", "y"), ("-y", "z"), ("z", "x")])
def test_preview_discs_ring_the_bone(new_scene, aim, up):
    group = _bent_arm()
    logic.set_axes(group, aim=aim, up=up)

    for preview in logic.previews(group):
        disc = cmds.listRelatives(preview, children=True, type="transform", fullPath=True)[0]
        # The disc is a circle around its local X.
        assert abs(_axis(disc, "x") * _axis(preview, aim)) == pytest.approx(1.0, abs=1e-4)


def test_plane_lies_on_the_guides_plane_and_follows_them(new_scene):
    group = _bent_arm()
    found = logic.guides(group)
    _move(found["up"], 3, 4, 5)
    _move(found["chain"][-1], 10, 2, -1)
    start, end = _pos(found["chain"][0]), _pos(found["chain"][-1])

    plane = logic.plane(group)

    assert (_pos(plane) - (start + end) * 0.5).length() < 1e-4
    assert (_axis(plane, "x") - (end - start).normalize()).length() < 1e-4
    assert (_axis(plane, "z") - _normal(group)).length() < 1e-4
    assert cmds.getAttr(f"{plane}.overrideDisplayType") == 2
    assert cmds.listRelatives(plane, shapes=True, type="nurbsSurface")


# -- delete_guides ------------------------------------------------------------


def test_delete_guides_leaves_nothing_behind_but_the_joints(new_scene):
    before = set(cmds.ls())
    group = _bent_arm()
    joints = logic.build_joints(group)

    logic.delete_guides(group)

    assert set(cmds.ls()) - before == {cmds.ls(j)[0] for j in joints}


def test_delete_guides_keeps_the_joints(new_scene):
    group = logic.create_guides("arm", 1)
    joints = logic.build_joints(group)
    uuids = [_uuid(j) for j in joints]

    logic.delete_guides(group)

    assert not cmds.ls("arm_*_guide")
    assert not cmds.objExists("arm_guides_grp")
    assert all(cmds.ls(u) for u in uuids)


def test_delete_guides_is_one_undo_step(new_scene):
    group = logic.create_guides("arm", 1)

    logic.delete_guides(group)
    cmds.undo()

    assert len(logic.guides("arm_guides_grp")["chain"]) == 3


# -- menu -----------------------------------------------------------------------


def test_guide_tool_is_a_top_level_menu_entry():
    tool = registry.find("Guide Tool")

    assert tool is not None
    assert "category" not in tool
    assert "Guide Tool" in [t["name"] for t in registry.menu_tools()]
