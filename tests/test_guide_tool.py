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


def _bent_arm(**kwargs):
    """Guides for an arm with three middle guides dragged off the plane,
    one of them so far that its segment points back towards the up guide."""
    group = logic.build_guides("arm", 3, start=(0, 0, 0), end=(12, 0, 0), **kwargs)
    found = logic.guides(group)
    _move(found["up"], 6, 5, 0)
    mids = found["chain"][1:-1]
    _move(mids[0], 3, -2, 1.5)
    _move(mids[1], 6, -3, -4)
    _move(mids[2], 7, 4, 2)
    return group


def _rows(node):
    return [_axis(node, axis) for axis in ("x", "y", "z")]


def _same_frame(a, b):
    assert (_pos(a) - _pos(b)).length() < 1e-4, (a, b)
    for row_a, row_b in zip(_rows(a), _rows(b)):
        assert (row_a - row_b).length() < 1e-4, (a, b)


def _planar(group):
    found = logic.guides(group)
    return logic.planar_positions([_pos(g) for g in found["chain"]], _pos(found["up"]))


def _center(node):
    box = cmds.exactWorldBoundingBox(node)
    return om.MVector((box[0] + box[3]) / 2, (box[1] + box[4]) / 2, (box[2] + box[5]) / 2)


def _disc(preview):
    return cmds.listRelatives(preview, children=True, type="transform", fullPath=True)[0]


def _cylinder(preview):
    return cmds.listRelatives(preview, children=True, type="transform", fullPath=True)[1]


def _frames(nodes):
    return [(_pos(n), _rows(n)) for n in nodes]


def _same_frames(before, after):
    for (pos_a, rows_a), (pos_b, rows_b) in zip(before, after):
        assert (pos_a - pos_b).length() < 1e-4
        for a, b in zip(rows_a, rows_b):
            assert (a - b).length() < 1e-4


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


# -- build_guides: new guides -------------------------------------------------


def test_build_guides_names_them_and_lines_them_up(new_scene):
    group = logic.build_guides("arm", 2, start=(0, 0, 0), end=(9, 0, 0))

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


def test_build_guides_puts_the_up_guide_off_the_chain(new_scene):
    group = logic.build_guides("arm", 1, start=(0, 0, 0), end=(10, 0, 0))

    up = _pos(logic.guides(group)["up"])
    assert ((om.MVector(10, 0, 0)) ^ up).length() > 1.0


def test_build_guides_with_no_middle_guides(new_scene):
    group = logic.build_guides("spine", 0)

    assert len(logic.guides(group)["chain"]) == 2
    assert len(logic.joints(group)) == 2


def test_guides_can_only_be_moved(new_scene):
    group = logic.build_guides("arm", 1)

    found = logic.guides(group)
    for node in found["chain"] + [found["up"]]:
        for attr in ("rx", "ry", "rz", "sx", "sy", "sz"):
            assert cmds.getAttr(f"{node}.{attr}", lock=True), (node, attr)
            assert not cmds.getAttr(f"{node}.{attr}", keyable=True), (node, attr)
            assert not cmds.getAttr(f"{node}.{attr}", channelBox=True), (node, attr)
        for attr in ("tx", "ty", "tz"):
            assert not cmds.getAttr(f"{node}.{attr}", lock=True)
            assert cmds.getAttr(f"{node}.{attr}", keyable=True)


def test_guides_show_their_selection_handle(new_scene):
    group = logic.build_guides("arm", 1)

    found = logic.guides(group)
    for node in found["chain"] + [found["up"]]:
        assert cmds.getAttr(f"{node}.displayHandle")


def test_display_curve_follows_the_guides(new_scene):
    group = logic.build_guides("arm", 1, start=(0, 0, 0), end=(10, 0, 0))
    found = logic.guides(group)

    _move(found["chain"][1], 4, 3, 2)
    cmds.move(1, 1, 1, group, relative=True)

    chain_curve, up_curve = logic.display_curves(group)
    assert cmds.getAttr(f"{chain_curve}.template")
    for i, node in enumerate(found["chain"]):
        assert (om.MVector(cmds.pointPosition(f"{chain_curve}.cv[{i}]")) - _pos(node)).length() < 1e-5
    assert (om.MVector(cmds.pointPosition(f"{up_curve}.cv[1]")) - _pos(found["up"])).length() < 1e-5


def test_guides_are_found_after_renaming(new_scene):
    group = logic.build_guides("arm", 1)
    mid = logic.guides(group)["chain"][1]

    cmds.rename(mid, "elbow_guide")

    assert cmds.ls(logic.guides(group)["chain"][1])[0] == "elbow_guide"


def test_guide_group_from_a_guide_the_group_or_a_joint(new_scene):
    group = logic.build_guides("arm", 1)
    joints = logic.joints(group)

    for node in (group, logic.guides(group)["chain"][1], logic.guides(group)["up"], joints[1]):
        assert logic.guide_group(node) == group


def test_guide_group_rejects_other_nodes(new_scene):
    cube = cmds.polyCube()[0]

    with pytest.raises(ValueError):
        logic.guide_group(cube)


def test_find_group_uses_the_selection(new_scene):
    arm = logic.build_guides("arm", 1)
    leg = logic.build_guides("leg", 1)

    assert logic.find_group([logic.guides(leg)["up"]]) == leg
    assert logic.find_group([arm]) == arm


def test_find_group_with_nothing_selected_uses_the_only_group(new_scene):
    arm = logic.build_guides("arm", 1)

    assert logic.find_group([]) == arm


def test_find_group_with_nothing_selected_and_several_groups(new_scene):
    logic.build_guides("arm", 1)
    logic.build_guides("leg", 1)

    with pytest.raises(ValueError, match="Select"):
        logic.find_group([])


def test_find_group_with_no_guides_in_the_scene(new_scene):
    with pytest.raises(ValueError, match="No guides"):
        logic.find_group([])


def test_find_group_rejects_guides_of_two_chains(new_scene):
    arm = logic.build_guides("arm", 1)
    leg = logic.build_guides("leg", 1)

    with pytest.raises(ValueError, match="one chain"):
        logic.find_group([arm, leg])


@pytest.mark.parametrize("name", ["", "1arm", "my arm"])
def test_build_guides_rejects_bad_names(new_scene, name):
    with pytest.raises(ValueError):
        logic.build_guides(name, 1)


def test_build_guides_rejects_a_negative_count(new_scene):
    with pytest.raises(ValueError):
        logic.build_guides("arm", -1)


def test_build_guides_rejects_start_on_end(new_scene):
    with pytest.raises(ValueError):
        logic.build_guides("arm", 1, start=(1, 1, 1), end=(1, 1, 1))


def test_build_guides_rejects_the_same_aim_and_up_axis(new_scene):
    with pytest.raises(ValueError):
        logic.build_guides("arm", 1, aim="x", up="-x")
    assert not cmds.ls(type="joint")


@pytest.mark.parametrize("taken", ["arm_mid_01_guide", "arm_02_jnt"])
def test_build_guides_refuses_a_taken_name_and_changes_nothing(new_scene, taken):
    cmds.createNode("joint" if taken.endswith("_jnt") else "transform", name=taken)
    before = set(cmds.ls())

    with pytest.raises(ValueError, match=taken):
        logic.build_guides("arm", 1)

    assert set(cmds.ls()) == before


def test_build_guides_is_one_undo_step(new_scene):
    before = set(cmds.ls())
    logic.build_guides("arm", 2)

    cmds.undo()

    assert set(cmds.ls()) == before


# -- live joints ----------------------------------------------------------------


def test_build_guides_makes_a_named_joint_chain(new_scene):
    group = logic.build_guides("arm", 2)

    joints = logic.joints(group)
    assert [cmds.ls(j)[0] for j in joints] == ["arm_01_jnt", "arm_02_jnt", "arm_03_jnt", "arm_04_jnt"]
    assert cmds.listRelatives(joints[0], parent=True) is None
    for parent, child in zip(joints, joints[1:]):
        assert cmds.listRelatives(child, parent=True, fullPath=True)[0] == parent


def test_live_joints_follow_the_guides_and_the_group(new_scene):
    group = _bent_arm()
    joints = logic.joints(group)
    found = logic.guides(group)

    for guide, xyz in ((found["chain"][2], (5, 6, 7)), (found["chain"][-1], (11, 3, -2)), (found["up"], (4, 2, 8))):
        _move(guide, *xyz)
        for joint, preview in zip(joints, logic.previews(group)):
            _same_frame(joint, preview)
    # Moving the start turns every parent joint: the ones below must follow.
    _move(found["chain"][0], -2, 1, 1)
    for joint, preview in zip(joints, logic.previews(group)):
        _same_frame(joint, preview)
    cmds.move(1, 2, 3, group, relative=True)

    for joint, preview in zip(joints, logic.previews(group)):
        _same_frame(joint, preview)
    for joint, position in zip(joints, _planar(group)):
        assert (_pos(joint) - position).length() < 1e-4


def test_live_joints_are_planar_and_end_on_the_end_guide(new_scene):
    group = _bent_arm()
    found = logic.guides(group)
    start = _pos(found["chain"][0])
    normal = _normal(group)

    joints = logic.joints(group)

    for joint in joints:
        assert abs((_pos(joint) - start) * normal) < 1e-5
    assert (_pos(joints[0]) - start).length() < 1e-5
    assert (_pos(joints[-1]) - _pos(found["chain"][-1])).length() < 1e-5


def test_live_joints_aim_down_the_chain_and_bend_around_the_plane_normal(new_scene):
    group = _bent_arm()
    normal = _normal(group)

    joints = logic.joints(group)

    for joint, child in zip(joints, joints[1:]):
        assert (_axis(joint, "x") - (_pos(child) - _pos(joint)).normalize()).length() < 1e-4
        assert (_axis(joint, "z") - normal).length() < 1e-4


def test_live_joints_up_axis_points_towards_the_up_guide(new_scene):
    group = logic.build_guides("arm", 1, start=(0, 0, 0), end=(10, 0, 0))
    _move(logic.guides(group)["up"], 5, 0, -6)

    joints = logic.joints(group)

    assert (_axis(joints[0], "y") - om.MVector(0, 0, -1)).length() < 1e-4


@pytest.mark.parametrize("aim, up, third", [("-y", "z", "-x"), ("z", "-x", "-y")])
def test_live_joints_with_other_axes(new_scene, aim, up, third):
    group = _bent_arm(aim=aim, up=up)
    normal = _normal(group)

    joints = logic.joints(group)

    for joint, child in zip(joints, joints[1:]):
        assert (_axis(joint, aim) - (_pos(child) - _pos(joint)).normalize()).length() < 1e-4
        # The third axis is the same plane normal for every joint.
        assert (_axis(joint, third) - normal).length() < 1e-4


def test_live_joints_follow_the_axes(new_scene):
    group = _bent_arm()
    joints = logic.joints(group)

    logic.set_axes(group, aim="-y", up="z")

    for joint, child in zip(joints, joints[1:]):
        assert (_axis(joint, "-y") - (_pos(child) - _pos(joint)).normalize()).length() < 1e-4
        assert (_axis(joint, "-x") - _normal(group)).length() < 1e-4


def test_end_joint_lines_up_with_its_parent(new_scene):
    joints = logic.joints(_bent_arm())

    for axis in ("x", "y", "z"):
        assert (_axis(joints[-1], axis) - _axis(joints[-2], axis)).length() < 1e-5


def test_live_joints_can_only_be_moved_through_the_guides(new_scene):
    group = logic.build_guides("arm", 1)

    for joint in logic.joints(group):
        for attr in ("tx", "ty", "tz", "rx", "ry", "rz"):
            assert cmds.getAttr(f"{joint}.{attr}", lock=True), (joint, attr)


# -- previews: a disc per joint, and the plane ---------------------------------


def test_previews_sit_where_the_joints_land(new_scene):
    group = _bent_arm()

    previews = logic.previews(group)

    assert len(previews) == 5
    for preview, position in zip(previews, _planar(group)):
        assert (_pos(preview) - position).length() < 1e-4


def test_set_axes_rejects_the_same_aim_and_up_axis(new_scene):
    group = logic.build_guides("arm", 1)

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


def test_previews_show_their_local_axis_and_their_discs_can_be_selected(new_scene):
    group = logic.build_guides("arm", 1)

    for preview in logic.previews(group):
        assert cmds.getAttr(f"{preview}.displayLocalAxis")
        disc = _disc(preview)
        assert cmds.getAttr(f"{disc}.overrideEnabled")
        assert cmds.getAttr(f"{disc}.overrideDisplayType") == 0  # normal: selectable
        assert cmds.listRelatives(disc, shapes=True, type="nurbsSurface")


def test_preview_discs_sit_on_their_joint(new_scene):
    group = _bent_arm()
    cmds.move(1, 2, 3, group, relative=True)

    for preview in logic.previews(group):
        disc = _disc(preview)
        assert (_pos(disc) - _pos(preview)).length() < 1e-4
        assert (_center(disc) - _pos(preview)).length() < 1e-3


@pytest.mark.parametrize("aim, up", [("x", "y"), ("-y", "z"), ("z", "x")])
def test_preview_discs_ring_the_bone(new_scene, aim, up):
    group = _bent_arm()
    logic.set_axes(group, aim=aim, up=up)

    for preview in logic.previews(group):
        # The disc is a circle around its local X.
        assert abs(_axis(_disc(preview), "x") * _axis(preview, aim)) == pytest.approx(1.0, abs=1e-4)


def test_preview_discs_and_plane_share_one_solid_shader(new_scene):
    group = logic.build_guides("arm", 1)
    plane = logic.plane(group)

    discs = [_disc(p) for p in logic.previews(group)]
    shapes = [cmds.listRelatives(node, shapes=True, fullPath=True)[0] for node in discs + [plane]]
    assert len({engine for shape in shapes for engine in cmds.listConnections(shape, type="shadingEngine")}) == 1
    for node in discs + [plane]:
        assert cmds.getAttr(f"{node}.overrideShading")
        shape = cmds.listRelatives(node, shapes=True, fullPath=True)[0]
        engines = cmds.listConnections(shape, type="shadingEngine") or []
        material = cmds.listConnections(f"{engines[0]}.surfaceShader")[0]
        assert cmds.nodeType(material) == "lambert"
        assert cmds.getAttr(f"{material}.transparency")[0] == (0, 0, 0)  # solid


def test_plane_is_centered_between_start_and_end(new_scene):
    group = _bent_arm()
    found = logic.guides(group)

    expected = (_pos(found["chain"][0]) + _pos(found["chain"][-1])) * 0.5
    assert (_center(logic.plane(group)) - expected).length() < 1e-3


def test_plane_lies_on_the_guides_plane_and_follows_them(new_scene):
    group = _bent_arm()
    found = logic.guides(group)
    _move(found["up"], 3, 4, 5)
    _move(found["chain"][-1], 10, 2, -1)
    start, end = _pos(found["chain"][0]), _pos(found["chain"][-1])

    plane = logic.plane(group)

    assert (_pos(plane) - start).length() < 1e-4  # pivots at the first joint
    assert (_center(plane) - (start + end) * 0.5).length() < 1e-3
    assert (_axis(plane, "x") - (end - start).normalize()).length() < 1e-4
    assert (_axis(plane, "z") - _normal(group)).length() < 1e-4
    assert cmds.getAttr(f"{plane}.overrideDisplayType") == 0  # normal: selectable
    assert cmds.listRelatives(plane, shapes=True, type="nurbsSurface")


# -- build_guides again: reset the middles --------------------------------------


def test_building_again_keeps_start_end_and_up_and_resets_the_middles(new_scene):
    group = _bent_arm()
    cmds.move(1, 2, 3, group, relative=True)
    old = logic.guides(group)
    start, end, up = _pos(old["chain"][0]), _pos(old["chain"][-1]), _pos(old["up"])

    group = logic.build_guides("arm", 1)

    found = logic.guides(group)
    assert cmds.ls(group)[0] == "arm_guides_grp"
    assert len(cmds.ls("arm_guides_grp")) == 1
    assert [cmds.ls(n)[0] for n in found["chain"]] == ["arm_start_guide", "arm_mid_01_guide", "arm_end_guide"]
    assert (_pos(found["chain"][0]) - start).length() < 1e-5
    assert (_pos(found["chain"][-1]) - end).length() < 1e-5
    assert (_pos(found["up"]) - up).length() < 1e-5
    assert (_pos(found["chain"][1]) - (start + end) * 0.5).length() < 1e-5
    assert len(logic.previews(group)) == 3


def test_building_again_spreads_more_middles_evenly(new_scene):
    logic.build_guides("arm", 1, start=(0, 0, 0), end=(8, 0, 0))

    group = logic.build_guides("arm", 3)

    for node, x in zip(logic.guides(group)["chain"], (0, 2, 4, 6, 8)):
        assert (_pos(node) - om.MVector(x, 0, 0)).length() < 1e-5


def test_building_again_keeps_the_axes_unless_given(new_scene):
    group = _bent_arm()
    logic.set_axes(group, aim="z", up="-x")

    group = logic.build_guides("arm", 2)
    joints = logic.joints(group)
    assert (_axis(joints[0], "z") - (_pos(joints[1]) - _pos(joints[0])).normalize()).length() < 1e-4

    group = logic.build_guides("arm", 2, aim="x", up="y")
    joints = logic.joints(group)
    assert (_axis(joints[0], "x") - (_pos(joints[1]) - _pos(joints[0])).normalize()).length() < 1e-4


def test_building_again_with_the_same_count_keeps_the_joints_live(new_scene):
    group = logic.build_guides("arm", 2)
    uuids = [_uuid(j) for j in logic.joints(group)]
    cmds.rename(logic.joints(group)[1], "elbow_jnt")

    group = logic.build_guides("arm", 2)
    _move(logic.guides(group)["chain"][1], 3, 4, 0)

    joints = logic.joints(group)
    assert [_uuid(j) for j in joints] == uuids
    assert cmds.ls(joints[1])[0] == "elbow_jnt"
    for joint, preview in zip(joints, logic.previews(group)):
        _same_frame(joint, preview)


def test_building_again_with_another_count_replaces_the_joints(new_scene):
    group = logic.build_guides("arm", 2)
    old = [_uuid(j) for j in logic.joints(group)]

    group = logic.build_guides("arm", 4)

    joints = logic.joints(group)
    assert [cmds.ls(j)[0] for j in joints] == [f"arm_{i:02d}_jnt" for i in range(1, 7)]
    assert not any(cmds.ls(u) for u in old)
    assert len(cmds.ls(type="joint")) == 6
    for joint, preview in zip(joints, logic.previews(group)):
        _same_frame(joint, preview)


def test_building_again_made_before_axes_were_kept(new_scene):
    group = logic.build_guides("arm", 1)
    cmds.deleteAttr(f"{group}.previewAxes")

    group = logic.build_guides("arm", 2)

    assert len(logic.guides(group)["chain"]) == 4


def test_building_again_is_one_undo_step(new_scene):
    group = _bent_arm()
    before = [_pos(n) for n in logic.guides(group)["chain"]]

    logic.build_guides("arm", 1)
    cmds.undo()

    after = [_pos(n) for n in logic.guides("arm_guides_grp")["chain"]]
    assert len(after) == len(before)
    assert all((a - b).length() < 1e-5 for a, b in zip(after, before))
    assert len(logic.joints("arm_guides_grp")) == 5


# -- window icons -------------------------------------------------------------


@pytest.mark.parametrize("button", ["build", "delete"])
def test_button_icons_ship_as_svg(button):
    import os
    import xml.etree.ElementTree as ET

    from kaiju_suite.ui import icons

    path = icons.path(f"guide_tool_{button}.svg")
    assert os.path.isfile(path), path
    assert ET.parse(path).getroot().tag == "{http://www.w3.org/2000/svg}svg"


# -- delete_guides: extract the joints ------------------------------------------


def test_delete_guides_extracts_the_joints_where_they_are(new_scene):
    group = _bent_arm()
    joints = logic.joints(group)
    uuids = [_uuid(j) for j in joints]
    before = _frames(joints)

    extracted = logic.delete_guides(group)

    assert [_uuid(j) for j in extracted] == uuids
    _same_frames(before, _frames(extracted))


def test_extracted_joints_have_plain_values(new_scene):
    joints = logic.delete_guides(_bent_arm())

    for joint in joints:
        assert not cmds.listConnections(f"{joint}.offsetParentMatrix", source=True, destination=False)
        assert cmds.getAttr(f"{joint}.offsetParentMatrix") == pytest.approx(list(om.MMatrix()))
        assert cmds.getAttr(f"{joint}.rotate")[0] == pytest.approx((0, 0, 0))
        for attr in ("tx", "ty", "tz", "rx", "ry", "rz"):
            assert not cmds.getAttr(f"{joint}.{attr}", lock=True)
    assert cmds.getAttr(f"{joints[-1]}.jointOrient")[0] == pytest.approx((0, 0, 0), abs=1e-6)


def test_delete_guides_leaves_nothing_behind_but_the_joints(new_scene):
    before = set(cmds.ls())
    group = _bent_arm()
    names = {cmds.ls(j)[0] for j in logic.joints(group)}

    logic.delete_guides(group)

    assert set(cmds.ls()) - before == names
    assert not before - set(cmds.ls())


def test_build_again_then_delete_leaves_nothing_behind_but_the_joints(new_scene):
    before = set(cmds.ls())
    _bent_arm()
    group = logic.build_guides("arm", 4)

    logic.delete_guides(group)

    assert set(cmds.ls()) - before == {f"arm_{i:02d}_jnt" for i in range(1, 7)}


def test_delete_guides_with_up_in_line_changes_nothing(new_scene):
    group = logic.build_guides("arm", 1, start=(0, 0, 0), end=(10, 0, 0))
    _move(logic.guides(group)["up"], 20, 0, 0)

    with pytest.raises(ValueError, match="in line"):
        logic.delete_guides(group)
    assert cmds.objExists("arm_guides_grp")


def test_delete_guides_is_one_undo_step(new_scene):
    group = _bent_arm()
    joints = logic.joints(group)

    logic.delete_guides(group)
    cmds.undo()

    group = "arm_guides_grp"
    assert len(logic.guides(group)["chain"]) == 5
    _move(logic.guides(group)["chain"][2], 5, 6, 7)
    for joint, preview in zip(joints, logic.previews(group)):
        _same_frame(joint, preview)


# -- guides from joints, e.g. after Delete Guides ------------------------------


def test_guides_from_extracted_joints_bring_the_same_joints_back_live(new_scene):
    group = _bent_arm(aim="z", up="-x")
    found = logic.guides(group)
    up = _pos(found["up"])
    joints = logic.delete_guides(group)
    uuids = [_uuid(j) for j in joints]
    cmds.rename(joints[1], "elbow_jnt")
    before = _frames(cmds.ls(uuids, long=True))

    group = logic.guides_from_joints(cmds.ls(uuids[2], long=True)[0])

    assert cmds.ls(group)[0] == "arm_guides_grp"
    linked = logic.joints(group)
    assert [_uuid(j) for j in linked] == uuids
    _same_frames(before, _frames(linked))
    found = logic.guides(group)
    for guide, joint in zip(found["chain"], linked):
        assert (_pos(guide) - _pos(joint)).length() < 1e-4
    assert (_pos(found["up"]) - up).length() < 1e-4
    # Live again, with the axes it had.
    _move(found["chain"][1], 3, 2, 0)
    for joint, preview in zip(linked, logic.previews(group)):
        _same_frame(joint, preview)
    assert (_axis(linked[0], "z") - (_pos(linked[1]) - _pos(linked[0])).normalize()).length() < 1e-4


def test_guides_from_joints_round_trip(new_scene):
    joints = logic.delete_guides(_bent_arm())
    before = _frames(joints)

    for _ in range(2):
        joints = logic.delete_guides(logic.guides_from_joints(joints[0]))

    _same_frames(before, _frames(joints))


def test_guides_from_a_chain_the_tool_did_not_make(new_scene):
    cmds.select(clear=True)
    made = [cmds.joint(position=p) for p in ((0, 0, 0), (4, 1, 0), (8, 0, 0))]
    cmds.joint(made[0], edit=True, orientJoint="xyz", secondaryAxisOrient="yup", children=True, zeroScaleOrient=True)
    positions = [_pos(j) for j in made]

    group = logic.guides_from_joints(made[0], name="leg", aim="x", up="y")

    assert cmds.ls(group)[0] == "leg_guides_grp"
    linked = logic.joints(group)
    assert [_uuid(j) for j in linked] == [_uuid(j) for j in made]
    for joint, position in zip(linked, positions):
        assert (_pos(joint) - position).length() < 1e-4
    up = _pos(logic.guides(group)["up"])
    assert up.y > 0.5  # off to the joints' up (+Y) side


def test_free_joint_picks_a_selected_joint_that_follows_no_guides(new_scene):
    group = logic.build_guides("arm", 1)
    cube = cmds.polyCube()[0]
    cmds.select(clear=True)
    loose = cmds.joint()

    assert logic.free_joint([cube, logic.joints(group)[0], loose]) == cmds.ls(loose, long=True)[0]
    assert logic.free_joint([cube, logic.joints(group)[0], logic.guides(group)["up"]]) is None
    assert logic.free_joint([]) is None


def test_guides_from_joints_refuses_joints_that_follow_guides(new_scene):
    group = logic.build_guides("arm", 1)

    with pytest.raises(ValueError, match="already"):
        logic.guides_from_joints(logic.joints(group)[0])


def test_guides_from_joints_refuses_a_single_joint(new_scene):
    cmds.select(clear=True)
    joint = cmds.joint()

    with pytest.raises(ValueError, match="chain"):
        logic.guides_from_joints(joint, name="arm")


def test_guides_from_joints_refuses_a_taken_name_and_changes_nothing(new_scene):
    joints = logic.delete_guides(logic.build_guides("arm", 1))
    cmds.createNode("transform", name="arm_up_guide")
    before = set(cmds.ls())

    with pytest.raises(ValueError, match="arm_up_guide"):
        logic.guides_from_joints(joints[0])

    assert set(cmds.ls()) == before


def test_guides_from_joints_is_one_undo_step(new_scene):
    joints = logic.delete_guides(_bent_arm())
    before = set(cmds.ls())
    frames = _frames(joints)

    logic.guides_from_joints(joints[0])
    cmds.undo()

    assert set(cmds.ls()) == before
    _same_frames(frames, _frames(joints))
    assert not cmds.getAttr(f"{joints[0]}.tx", lock=True)


# -- menu -----------------------------------------------------------------------


def test_guide_tool_is_a_top_level_menu_entry():
    tool = registry.find("Guide Tool")

    assert tool is not None
    assert "category" not in tool
    assert "Guide Tool" in [t["name"] for t in registry.menu_tools()]


def _maya_errors(func, *args, **kwargs):
    """Run ``func`` and return the errors and warnings Maya printed meanwhile."""
    printed = []
    kinds = (om.MCommandMessage.kWarning, om.MCommandMessage.kError)
    callback = om.MCommandMessage.addCommandOutputCallback(
        lambda text, kind, _: printed.append(text.strip()) if kind in kinds else None
    )
    try:
        func(*args, **kwargs)
    finally:
        om.MMessage.removeCallback(callback)
    return printed


def test_delete_guides_prints_no_errors(new_scene):
    group = _bent_arm()

    assert _maya_errors(logic.delete_guides, group) == []


def test_building_again_prints_no_errors(new_scene):
    _bent_arm()

    assert _maya_errors(logic.build_guides, "arm", 1) == []


def _referenced(joint):
    return cmds.getAttr(f"{joint}.overrideEnabled") and cmds.getAttr(f"{joint}.overrideDisplayType") == 2


def test_live_joints_are_drawn_as_reference(new_scene):
    group = _bent_arm()

    assert all(_referenced(j) for j in logic.joints(group))


def test_building_again_keeps_the_joints_reference(new_scene):
    _bent_arm()

    group = logic.build_guides("arm", 1)

    assert all(_referenced(j) for j in logic.joints(group))


def test_delete_guides_makes_the_joints_normal_again(new_scene):
    joints = logic.delete_guides(_bent_arm())

    for joint in joints:
        assert not cmds.getAttr(f"{joint}.overrideEnabled")
        assert cmds.getAttr(f"{joint}.overrideDisplayType") == 0


def test_delete_guides_keeps_a_joint_color_override(new_scene):
    group = _bent_arm()
    top = logic.joints(group)[0]
    cmds.setAttr(f"{top}.overrideColor", 13)

    top = logic.delete_guides(group)[0]

    assert cmds.getAttr(f"{top}.overrideEnabled")
    assert cmds.getAttr(f"{top}.overrideDisplayType") == 0
    assert cmds.getAttr(f"{top}.overrideColor") == 13


def test_guides_from_joints_draws_them_as_reference(new_scene):
    joints = logic.delete_guides(_bent_arm())

    group = logic.guides_from_joints(joints[0])

    assert all(_referenced(j) for j in logic.joints(group))



# -- scaling the plane and discs ----------------------------------------------


def _scalables(group):
    return [logic.plane(group)] + [part(p) for p in logic.previews(group) for part in (_disc, _cylinder)]


def _extent(node, axis):
    box = cmds.exactWorldBoundingBox(node)
    return box[3 + axis] - box[axis]


def test_plane_and_discs_can_only_be_scaled(new_scene):
    group = logic.build_guides("arm", 1)

    for node in _scalables(group):
        for attr in ("tx", "ty", "tz", "rx", "ry", "rz"):
            assert cmds.getAttr(f"{node}.{attr}", lock=True), f"{node}.{attr}"
        for attr in ("sx", "sy", "sz"):
            assert not cmds.getAttr(f"{node}.{attr}", lock=True), f"{node}.{attr}"
            assert cmds.getAttr(f"{node}.{attr}", keyable=True), f"{node}.{attr}"
            assert not cmds.listConnections(f"{node}.{attr}", source=True, destination=False), f"{node}.{attr}"


def test_scaled_plane_keeps_following_the_guides(new_scene):
    group = logic.build_guides("arm", 1, start=(0, 0, 0), end=(10, 0, 0))
    plane = logic.plane(group)
    before = _extent(plane, 0)

    cmds.setAttr(f"{plane}.scaleX", 2)
    assert _extent(plane, 0) == pytest.approx(before * 2, rel=1e-3)

    _move(logic.guides(group)["chain"][-1], 20, 0, 0)
    assert _extent(plane, 0) == pytest.approx(before * 4, rel=1e-3)
    # Scaled from the first joint: twice as far from it as the guides' midpoint.
    assert (_center(plane) - om.MVector(20, 0, 0)).length() < 1e-3


def test_plane_scales_from_the_first_joint(new_scene):
    group = _bent_arm()
    start = _pos(logic.guides(group)["chain"][0])
    plane = logic.plane(group)
    before = _center(plane)
    pivot = om.MVector(cmds.xform(plane, query=True, worldSpace=True, rotatePivot=True))

    cmds.setAttr(f"{plane}.scale", 2, 3, 1)

    assert (pivot - start).length() < 1e-4
    assert (_center(plane) - (start + (before - start) * 2)).length() < 1e-3


def test_scaling_the_plane_and_discs_leaves_the_joints_alone(new_scene):
    group = _bent_arm()
    before = [_pos(j) for j in logic.joints(group)]

    for node in _scalables(group):
        cmds.setAttr(f"{node}.scale", 3, 0.5, 2)

    assert all((_pos(j) - b).length() < 1e-5 for j, b in zip(logic.joints(group), before))


def test_scaled_disc_stays_on_its_joint_and_turns_with_the_axes(new_scene):
    group = _bent_arm()
    for preview in logic.previews(group):
        cmds.setAttr(f"{_disc(preview)}.scale", 2, 2, 2)

    logic.set_axes(group, aim="y", up="x")

    for preview in logic.previews(group):
        disc = _disc(preview)
        assert (_center(disc) - _pos(preview)).length() < 1e-3
        assert abs(_axis(disc, "x") * _axis(preview, "y")) == pytest.approx(1.0, abs=1e-4)
        assert cmds.getAttr(f"{disc}.rx", lock=True)


def test_building_again_keeps_the_plane_and_disc_scales(new_scene):
    group = _bent_arm()
    cmds.setAttr(f"{logic.plane(group)}.scale", 2, 3, 1)
    for i, preview in enumerate(logic.previews(group)):
        cmds.setAttr(f"{_disc(preview)}.scale", i + 1, i + 1, i + 1)
        cmds.setAttr(f"{_cylinder(preview)}.scale", 1, i + 2, i + 2)

    group = logic.build_guides("arm", 3)

    assert cmds.getAttr(f"{logic.plane(group)}.scale")[0] == pytest.approx((2, 3, 1))
    for i, preview in enumerate(logic.previews(group)):
        assert cmds.getAttr(f"{_disc(preview)}.scale")[0] == pytest.approx((i + 1,) * 3)
        assert cmds.getAttr(f"{_cylinder(preview)}.scale")[0] == pytest.approx((1, i + 2, i + 2))


def test_building_again_with_another_count_keeps_the_plane_scale(new_scene):
    group = _bent_arm()
    cmds.setAttr(f"{logic.plane(group)}.scale", 2, 3, 1)

    group = logic.build_guides("arm", 1)

    assert cmds.getAttr(f"{logic.plane(group)}.scale")[0] == pytest.approx((2, 3, 1))



# -- the rotate-axis cylinders ---------------------------------------------------


@pytest.mark.parametrize("aim, up", [("x", "y"), ("y", "x"), ("-z", "y"), ("x", "-z")])
def test_each_joint_has_a_cylinder_along_its_rotate_axis(new_scene, aim, up):
    group = _bent_arm(aim=aim, up=up)
    normal = _normal(group)

    for preview in logic.previews(group):
        cylinder = _cylinder(preview)
        assert cmds.listRelatives(cylinder, shapes=True, type="nurbsSurface")
        assert abs(_axis(cylinder, "x") * normal) == pytest.approx(1.0, abs=1e-4)
        assert (_center(cylinder) - _pos(preview)).length() < 1e-3
        # Along its own X: longer than it is wide.
        shape = cmds.listRelatives(cylinder, shapes=True, fullPath=True)[0]
        length, width, depth = cmds.getAttr(f"{shape}.boundingBoxSize")[0]
        assert length > 2 * width and width == pytest.approx(depth)


def test_cylinders_follow_new_axes(new_scene):
    group = _bent_arm()

    logic.set_axes(group, aim="z", up="-x")

    for preview in logic.previews(group):
        assert abs(_axis(_cylinder(preview), "x") * _normal(group)) == pytest.approx(1.0, abs=1e-4)


def test_cylinders_are_solid_selectable_and_share_the_preview_shader(new_scene):
    group = logic.build_guides("arm", 1)
    disc_shape = cmds.listRelatives(_disc(logic.previews(group)[0]), shapes=True, fullPath=True)[0]
    engine = cmds.listConnections(disc_shape, type="shadingEngine")

    for preview in logic.previews(group):
        cylinder = _cylinder(preview)
        assert cmds.getAttr(f"{cylinder}.overrideEnabled")
        assert cmds.getAttr(f"{cylinder}.overrideDisplayType") == 0
        assert cmds.getAttr(f"{cylinder}.overrideShading")
        shape = cmds.listRelatives(cylinder, shapes=True, fullPath=True)[0]
        assert cmds.listConnections(shape, type="shadingEngine") == engine
