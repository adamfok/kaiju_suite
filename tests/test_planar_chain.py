"""Planar chains (kaiju_suite.rigging.guide_module.planar_chain), shared by the
Guide Module Editor and the Chain guide module. Most of their behaviour is
covered in tests/test_guide_module_editor.py; this covers building a chain from a saved
layout and reading it back."""

import pytest
from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.rigging.guide_module import planar_chain as guides

POSITIONS = [(0, 0, 0), (3, 1, 0.5), (6, -1, 0), (10, 0, 0)]
UP = (5, 6, 0)


def _pos(node):
    return [round(v, 5) for v in cmds.xform(node, query=True, worldSpace=True, translation=True)]


def test_build_at_puts_every_guide_where_given(new_scene):
    group = guides.build_at("arm", POSITIONS, UP, aim="-x", up="z")
    found = guides.guides(group)
    assert [_pos(g) for g in found["chain"]] == [list(map(float, p)) for p in POSITIONS]
    assert _pos(found["up"]) == [5.0, 6.0, 0.0]
    assert len(guides.joints(group)) == 4
    assert cmds.getAttr(f"{group}.previewAxes") == "-x z"


def test_build_at_joints_follow_the_guides(new_scene):
    group = guides.build_at("arm", POSITIONS, UP)
    end_joint = guides.joints(group)[-1]
    end = om.MVector(cmds.xform(end_joint, query=True, worldSpace=True, translation=True))
    assert (end - om.MVector(10, 0, 0)).length() < 1e-4


def test_layout_reads_back_what_build_at_made(new_scene):
    group = guides.build_at("arm", POSITIONS, UP, aim="y", up="-z")
    assert guides.layout(group) == {
        "name": "arm",
        "aim": "y",
        "up": "-z",
        "guides": [list(map(float, p)) for p in POSITIONS],
        "up_guide": [5.0, 6.0, 0.0],
    }


def test_layout_follows_moved_guides(new_scene):
    group = guides.build_guides("leg", 1, start=(0, 0, 0), end=(0, -8, 0))
    cmds.xform(guides.guides(group)["chain"][1], worldSpace=True, translation=(0.5, -4, 1))
    assert guides.layout(group)["guides"][1] == [0.5, -4.0, 1.0]


def test_build_at_needs_two_positions(new_scene):
    with pytest.raises(ValueError, match="2 guides or more"):
        guides.build_at("arm", [(0, 0, 0)], UP)
    assert cmds.ls(type="joint") == []


def test_build_at_refuses_an_up_guide_in_line(new_scene):
    with pytest.raises(ValueError, match="in line"):
        guides.build_at("arm", POSITIONS, (20, 0, 0))
    assert cmds.ls(type="joint") == []


def test_build_at_refuses_names_in_use(new_scene):
    cmds.createNode("transform", name="arm_02_jnt")
    with pytest.raises(ValueError, match="arm_02_jnt"):
        guides.build_at("arm", POSITIONS, UP)
    assert not cmds.objExists("arm_guides_grp")


def test_taken_names_lists_names_in_use(new_scene):
    assert guides.taken_names("arm", 2) == []
    guides.build_at("arm", POSITIONS, UP)
    assert "arm_guides_grp" in guides.taken_names("arm", 2)



# -- leftover joints: what Delete Guides left -----------------------------------


def test_leftover_joint_is_the_top_joint_delete_guides_left(new_scene):
    group = guides.build_at("arm", POSITIONS, UP)
    top = guides.joints(group)[0]
    uuid = cmds.ls(top, uuid=True)[0]
    assert guides.leftover_joint("arm") is None  # still follows its guides
    guides.delete_guides(group)
    assert cmds.ls(guides.leftover_joint("arm"), uuid=True) == [uuid]
    assert guides.leftover_joint("leg") is None


def test_leftover_joint_ignores_joints_that_follow_guides_again(new_scene):
    group = guides.build_at("arm", POSITIONS, UP)
    top = guides.delete_guides(group)[0]
    guides.guides_from_joints(top)
    assert guides.leftover_joint("arm") is None


# -- set_layout: put guides back as a layout has them ---------------------------


def _layout(positions=POSITIONS, up=UP, aim="x", up_axis="y"):
    return {
        "name": "arm",
        "aim": aim,
        "up": up_axis,
        "guides": [[float(c) for c in p] for p in positions],
        "up_guide": [float(c) for c in up],
    }


def test_set_layout_moves_the_guides_and_turns_the_axes(new_scene):
    group = guides.build_at("arm", POSITIONS, UP)
    joint = cmds.ls(guides.joints(group)[0], uuid=True)[0]
    found = guides.guides(group)
    cmds.xform(found["chain"][1], worldSpace=True, translation=(4, 4, 4))
    cmds.xform(found["up"], worldSpace=True, translation=(5, 9, 1))
    guides.set_axes(group, aim="-y", up="z")

    group = guides.set_layout(group, POSITIONS, UP, aim="x", up="y")

    assert guides.layout(group) == _layout()
    assert cmds.ls(guides.joints(group)[0], uuid=True) == [joint]  # the same joints


def test_set_layout_remakes_the_middles_for_another_count(new_scene):
    group = guides.build_at("arm", POSITIONS, UP)
    three = [(0, 0, 0), (5, 1, 0), (10, 0, 0)]

    group = guides.set_layout(group, three, UP, aim="x", up="y")

    assert guides.layout(group) == _layout(three)
    assert len(guides.joints(group)) == 3


def test_set_layout_refuses_a_layout_it_cant_build_and_changes_nothing(new_scene):
    group = guides.build_at("arm", POSITIONS, UP)
    before = guides.layout(group)
    with pytest.raises(ValueError, match="in line"):
        guides.set_layout(group, POSITIONS, (20, 0, 0), aim="x", up="y")
    with pytest.raises(ValueError, match="different axes"):
        guides.set_layout(group, POSITIONS, UP, aim="x", up="-x")
    assert guides.layout(group) == before



# -- extract_problems: whether delete_guides can extract the joints ------------


def test_extract_problems_is_empty_for_whole_guides(new_scene):
    assert guides.extract_problems(guides.build_at("arm", POSITIONS, UP)) == []


def test_extract_problems_names_missing_guides(new_scene):
    group = guides.build_at("arm", POSITIONS, UP)
    cmds.delete(guides.guides(group)["up"])
    (problem,) = guides.extract_problems(group)
    assert "arm_guides_grp" in problem and "missing" in problem


# -- deleting guides quietly -----------------------------------------------------


@pytest.fixture
def maya_errors():
    """Maya's error and warning output while the test runs."""
    found = []
    kinds = (om.MCommandMessage.kError, om.MCommandMessage.kWarning)
    callback = om.MCommandMessage.addCommandOutputCallback(lambda message, kind, *_: kind in kinds and found.append(message))
    yield found
    om.MMessage.removeCallback(callback)


def test_delete_guides_reports_no_errors(new_scene, maya_errors):
    guides.delete_guides(guides.build_at("arm", POSITIONS, UP))
    assert maya_errors == []


def test_building_guides_again_reports_no_errors(new_scene, maya_errors):
    guides.build_guides("arm", 1)
    guides.build_guides("arm", 2)  # replaces the first guides
    assert maya_errors == []


# -- a chain hanging under another chain's joint ---------------------------------

LEG = [(1, 9, 0), (1, 5, 0.5), (1, 1, 0)]
LEG_UP = (1, 5, 5)
FOOT = [(1, 1, 0), (1, 0, 1.5), (1, 0, 3)]
FOOT_UP = (1, 3, 1.5)


def _leg_and_foot():
    leg = guides.build_at("leg", LEG, LEG_UP)
    ankle = guides.joints(leg)[-1]
    foot = guides.build_at("foot", FOOT, FOOT_UP, parent=ankle)
    return leg, foot


def test_an_attached_chain_shares_its_start_guide_and_hangs_under_the_parent_joint(new_scene):
    leg, foot = _leg_and_foot()
    ankle = guides.joints(leg)[-1]

    assert guides.guides(foot)["chain"][0] == guides.guides(leg)["chain"][-1]
    assert not cmds.objExists("foot_start_guide")
    joints = guides.joints(foot)
    assert cmds.ls(joints) == ["foot_01_jnt", "foot_02_jnt"]
    assert cmds.listRelatives(joints[0], parent=True, fullPath=True) == [ankle]
    assert [_pos(j) for j in joints] == [[1.0, 0.0, 1.5], [1.0, 0.0, 3.0]]
    assert guides.attached(ankle) == [foot]
    assert guides.attached(guides.joints(leg)[0]) == []


def test_an_attached_chains_joints_follow_both_chains_guides(new_scene):
    leg, foot = _leg_and_foot()
    ball, toe = guides.joints(foot)
    cmds.xform(guides.guides(foot)["chain"][1], worldSpace=True, translation=(1, 0.5, 1.5))
    assert _pos(ball) == [1.0, 0.5, 1.5]
    cmds.xform(guides.guides(leg)["chain"][-1], worldSpace=True, translation=(1, 2, 0))  # the shared ankle
    assert _pos(guides.joints(leg)[-1]) == [1.0, 2.0, 0.0]
    assert _pos(toe) == [1.0, 0.0, 3.0]


def test_the_shared_guide_belongs_to_the_chain_it_was_made_for(new_scene):
    leg, foot = _leg_and_foot()
    shared = guides.guides(leg)["chain"][-1]
    assert guides.guide_group(shared) == leg
    assert guides.guide_group(guides.guides(foot)["chain"][1]) == foot


def test_an_attached_chains_layout_starts_on_the_shared_guide(new_scene):
    _, foot = _leg_and_foot()
    assert guides.layout(foot)["guides"] == [list(map(float, p)) for p in FOOT]


def test_check_build_of_an_attached_chain_needs_no_start_guide_name(new_scene):
    cmds.createNode("transform", name="foot_start_guide")
    guides.check_build("foot", FOOT, FOOT_UP, attached=True)
    with pytest.raises(ValueError, match="foot_start_guide"):
        guides.check_build("foot", FOOT, FOOT_UP)
    cmds.createNode("transform", name="foot_02_jnt")
    with pytest.raises(ValueError, match="foot_02_jnt"):
        guides.check_build("foot", FOOT, FOOT_UP, attached=True)


def test_build_at_refuses_a_parent_that_isnt_a_guided_joint(new_scene):
    cmds.select(clear=True)
    loose = cmds.joint(name="loose_jnt")
    with pytest.raises(ValueError, match="loose_jnt isn't a joint built from guides"):
        guides.build_at("foot", FOOT, FOOT_UP, parent=loose)
    assert not cmds.objExists("foot_guides_grp")


def test_extracting_an_attached_chain_then_its_parent_keeps_every_joint_in_place(new_scene):
    leg, foot = _leg_and_foot()
    cmds.xform(guides.guides(foot)["chain"][1], worldSpace=True, translation=(1, 0.5, 1.5))
    ankle = guides.joints(leg)[-1]

    foot_joints = guides.delete_guides(foot)
    assert cmds.objExists("leg_guides_grp")
    assert guides.guides(leg)["chain"][-1]  # the shared guide stays with the leg
    leg_joints = guides.delete_guides(leg)

    assert [_pos(j) for j in leg_joints + foot_joints] == [
        [1.0, 9.0, 0.0], [1.0, 5.0, 0.5], [1.0, 1.0, 0.0], [1.0, 0.5, 1.5], [1.0, 0.0, 3.0]
    ]
    assert cmds.listRelatives(foot_joints[0], parent=True, fullPath=True) == cmds.ls(ankle, long=True)
    assert cmds.ls(type="locator") == []
    assert not cmds.attributeQuery("kaijuGuideName", node=foot_joints[0], exists=True)


def test_set_layout_moves_an_attached_chains_guides(new_scene):
    _, foot = _leg_and_foot()
    moved = [FOOT[0], (1, 0, 2), (1, 0, 4)]
    assert guides.set_layout(foot, moved, FOOT_UP) == foot
    assert guides.layout(foot)["guides"] == [list(map(float, p)) for p in moved]
    with pytest.raises(ValueError, match="attached"):
        guides.set_layout(foot, moved + [(1, 0, 5)], FOOT_UP)
