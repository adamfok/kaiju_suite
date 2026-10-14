"""The Leg guide module (kaiju_suite.rigging.guide_module.modules.leg): a
hip-knee-ankle chain with a foot chain hanging under the ankle and the
reverse foot's pivots (kaiju_suite.rigging.guide_module.foot)."""

import os

import pytest
from maya import cmds

from kaiju_suite.rigging.guide_module import delete_all_guides, foot, get_guide_module, planar_chain, spec
from kaiju_suite.rigging.guide_module.guide_module import GuideError

L_LEG = {
    "name": "L_leg",
    "aim": "x",
    "up": "y",
    "leg": [[2.0, 10.0, 0.0], [2.0, 6.0, 1.0], [2.0, 1.0, 0.0]],
    "leg_up": [2.0, 6.0, 6.0],
    "foot": [[2.0, 0.0, 2.0], [2.0, 0.0, 4.0]],
    "foot_up": [2.0, 4.0, 2.0],
    "heel": [2.0, 0.0, -1.0],
    "inner": [1.0, 0.0, 2.0],
    "outer": [3.0, 0.0, 2.0],
    "foot_aim": "z",
    "foot_up_axis": "-x",
}


@pytest.fixture
def leg():
    return get_guide_module("leg")


def _pos(node):
    return [round(v, 5) + 0.0 for v in cmds.xform(node, query=True, worldSpace=True, translation=True)]


def test_leg_is_discovered(leg):
    assert leg.name == "Leg Guide"
    assert leg.mirrorable


def test_default_layout_is_a_buildable_leg(new_scene, leg):
    layout = leg.default_layout("L_leg")
    assert layout["name"] == "L_leg"
    assert len(layout["leg"]) == 3 and len(layout["foot"]) == 2
    assert leg.problems(layout) == []
    group = leg.build(layout)
    assert leg.layout(group) == layout


def test_default_layout_falls_back_to_leg_for_a_name_that_cant_name_nodes(leg):
    assert leg.default_layout("2 legs")["name"] == "leg"


def test_build_makes_hip_knee_ankle_with_the_foot_under_the_ankle(new_scene, leg):
    group = leg.build(L_LEG)

    assert cmds.ls(group) == ["L_leg_guides_grp"]
    assert cmds.getAttr(f"{group}.kaijuGuideModule") == "leg"
    hip, knee, ankle = planar_chain.joints(group)
    ball, toe = planar_chain.joints("L_leg_foot_guides_grp")
    assert cmds.listRelatives(ball, parent=True, fullPath=True) == [ankle]
    assert [_pos(j) for j in (hip, knee, ankle, ball, toe)] == L_LEG["leg"] + L_LEG["foot"]
    # The ankle guide is shared, not duplicated.
    assert planar_chain.guides("L_leg_foot_guides_grp")["chain"][0] == planar_chain.guides(group)["chain"][-1]


def test_build_makes_the_pivots_as_move_only_locators(new_scene, leg):
    group = leg.build(L_LEG)
    pivots = foot.pivots(group)
    assert [cmds.ls(p)[0] for p in pivots.values()] == ["L_leg_heel_pivot", "L_leg_inner_pivot", "L_leg_outer_pivot"]
    for key, pivot in pivots.items():
        assert cmds.listRelatives(pivot, shapes=True, type="locator")
        assert _pos(pivot) == L_LEG[key]
        assert cmds.getAttr(f"{pivot}.rx", lock=True)
    assert cmds.ls(type="joint", long=True) == cmds.ls(planar_chain.joints(group) + planar_chain.joints("L_leg_foot_guides_grp"), long=True)


def test_the_joints_follow_the_guides_live(new_scene, leg):
    group = leg.build(L_LEG)
    ball_guide = planar_chain.guides("L_leg_foot_guides_grp")["chain"][1]
    cmds.xform(ball_guide, worldSpace=True, translation=(2, 0.5, 2))
    assert _pos(planar_chain.joints("L_leg_foot_guides_grp")[0]) == [2.0, 0.5, 2.0]
    assert leg.layout(group)["foot"][0] == [2.0, 0.5, 2.0]


def test_build_is_one_undo_step(new_scene, leg):
    cmds.undoInfo(state=True)
    cmds.flushUndo()
    before = set(cmds.ls())
    leg.build(L_LEG)
    cmds.undo()
    assert set(cmds.ls()) == before


def test_problems(new_scene, leg):
    assert leg.problems({"name": "a"}) == [
        "The Leg Guide layout is missing aim, up, leg, leg_up, foot, foot_up, heel, inner, outer."
    ]
    assert leg.problems(dict(L_LEG, heel="here")) == ["L_leg: every guide must be an [x, y, z] position."]
    assert leg.problems(dict(L_LEG, leg=L_LEG["leg"][:2])) == ["L_leg: leg needs 3 guides (hip, knee, ankle)."]
    assert leg.problems(dict(L_LEG, foot=L_LEG["foot"] * 2)) == ["L_leg: foot needs 2 guides (ball, toe)."]
    in_line = dict(L_LEG, foot_up=[2.0, -1.0, 8.0])
    assert leg.problems(in_line) == [
        "L_leg foot: The up guide is in line with the start and end guides; move it to the side."
    ]
    cmds.createNode("transform", name="L_leg_heel_pivot")
    assert leg.problems(L_LEG) == ["These names are already used, rename or delete them first: L_leg_heel_pivot"]
    cmds.delete("L_leg_heel_pivot")
    leg.build(L_LEG)
    assert leg.problems(L_LEG) == ["Guides already in the scene: L_leg. Delete them first."]


def test_describe_and_nodes(leg):
    assert leg.describe(L_LEG) == [
        "L_leg: hip, knee, ankle, ball, toe; heel, inner and outer pivots; leg aim x, up y; foot aim z, up -x"
    ]
    assert leg.nodes(L_LEG) == ["L_leg_guides_grp"]


def test_mirrored_flips_across_x_and_reverses_the_axes(leg):
    mirrored = leg.mirrored(L_LEG)
    assert mirrored["name"] == "R_leg"
    assert (mirrored["aim"], mirrored["up"]) == ("-x", "-y")
    assert (mirrored["foot_aim"], mirrored["foot_up_axis"]) == ("-z", "x")
    assert mirrored["leg"][0] == [-2.0, 10.0, 0.0]
    assert mirrored["foot_up"] == [-2.0, 4.0, 2.0]
    assert mirrored["inner"] == [-1.0, 0.0, 2.0]  # still nearer the middle
    assert leg.mirrored(mirrored) == L_LEG


def test_mirrored_layout_builds_next_to_the_original(new_scene, leg):
    leg.build(L_LEG)
    group = leg.build(leg.mirrored(L_LEG))
    assert cmds.ls(group) == ["R_leg_guides_grp"]


def test_mirrored_joints_turn_in_mirror_image(new_scene, leg):
    left, right = leg.build(L_LEG), leg.build(leg.mirrored(L_LEG))
    for l_joint, r_joint in zip(
        planar_chain.joints(left) + planar_chain.joints("L_leg_foot_guides_grp"),
        planar_chain.joints(right) + planar_chain.joints("R_leg_foot_guides_grp"),
    ):
        l_m = cmds.xform(l_joint, query=True, worldSpace=True, matrix=True)
        r_m = cmds.xform(r_joint, query=True, worldSpace=True, matrix=True)
        for axis in range(3):
            l_row, r_row = l_m[axis * 4 : axis * 4 + 3], r_m[axis * 4 : axis * 4 + 3]
            # Behavior mirror: each axis is the left one flipped across X, then reversed.
            assert [round(v, 4) + 0.0 for v in r_row] == [round(v, 4) + 0.0 for v in (l_row[0], -l_row[1], -l_row[2])]


def test_restore_puts_everything_back(new_scene, leg):
    group = leg.build(L_LEG)
    cmds.xform(planar_chain.guides(group)["chain"][1], worldSpace=True, translation=(2, 6, 3))
    cmds.xform(foot.pivots(group)["heel"], worldSpace=True, translation=(2, 0, -2))
    cmds.xform(planar_chain.guides("L_leg_foot_guides_grp")["up"], worldSpace=True, translation=(2, 5, 2))

    assert leg.restore(group, L_LEG) == cmds.ls(group, long=True)[0]

    assert leg.layout(group) == L_LEG
    assert cmds.getAttr(f"{group}.kaijuGuideModule") == "leg"


def test_restore_is_one_undo_step(new_scene, leg):
    group = leg.build(L_LEG)
    cmds.xform(foot.pivots(group)["outer"], worldSpace=True, translation=(4, 0, 2))
    moved = leg.layout(group)
    cmds.undoInfo(state=True)
    cmds.flushUndo()
    leg.restore(group, L_LEG)
    cmds.undo()
    assert leg.layout(group) == moved


def test_restore_refuses_a_broken_layout(new_scene, leg):
    group = leg.build(L_LEG)
    with pytest.raises(GuideError, match="leg needs 3 guides"):
        leg.restore(group, dict(L_LEG, leg=L_LEG["leg"] + [[2, 0, 0]]))
    assert leg.layout(group) == L_LEG


def test_extract_keeps_every_joint_where_it_is(new_scene, leg):
    group = leg.build(L_LEG)
    uuids = cmds.ls(planar_chain.joints(group) + planar_chain.joints("L_leg_foot_guides_grp"), uuid=True)

    joints = leg.extract(group)

    assert cmds.ls(joints, uuid=True) == uuids
    assert [_pos(j) for j in joints] == L_LEG["leg"] + L_LEG["foot"]
    assert cmds.ls(type="locator") == []
    assert not cmds.objExists("L_leg_guides_grp")
    assert cmds.listRelatives(joints[3], parent=True, fullPath=True) == cmds.ls(joints[2], long=True)


def test_extract_is_one_undo_step(new_scene, leg):
    group = leg.build(L_LEG)
    cmds.undoInfo(state=True)
    cmds.flushUndo()
    leg.extract(group)
    cmds.undo()
    assert leg.layout("L_leg_guides_grp") == L_LEG


def test_check_extract_names_a_missing_foot_guide(new_scene, leg):
    group = leg.build(L_LEG)
    cmds.delete(planar_chain.guides("L_leg_foot_guides_grp")["up"])
    (problem,) = leg.check_extract(group)
    assert "missing" in problem


def test_delete_all_guides_extracts_the_leg(new_scene, leg):
    leg.build(L_LEG)
    extracted = delete_all_guides()
    assert list(extracted) == ["L_leg"]
    assert len(extracted["L_leg"]) == 5


# -- the guide file and the Assembler's datatype interface --------------------


def test_any_leg_node_finds_the_leg(new_scene, leg):
    group = leg.build(L_LEG)
    foot_group = "L_leg_foot_guides_grp"
    nodes = [
        planar_chain.guides(group)["chain"][-1],  # the shared ankle
        planar_chain.guides(foot_group)["chain"][-1],
        planar_chain.joints(foot_group)[0],
        planar_chain.joints(group)[1],
        foot.pivots(group)["heel"],
        foot_group,
    ]
    for node in nodes:
        assert spec.find_group([node]) == (leg, cmds.ls(group, long=True)[0]), node


def test_gather_then_apply_builds_the_leg_again(new_scene, leg):
    group = leg.build(L_LEG)
    payload = spec.gather([foot.pivots(group)["inner"]])
    assert payload == {"guide_module": "leg", "layout": L_LEG}
    cmds.file(new=True, force=True)
    spec.apply(payload)
    assert leg.layout("L_leg_guides_grp") == L_LEG


# -- the foot's own axes ---------------------------------------------------------


def _axis(node, index):
    m = cmds.xform(node, query=True, worldSpace=True, matrix=True)
    return [round(v, 4) + 0.0 for v in m[index * 4 : index * 4 + 3]]


def test_the_leg_and_the_foot_turn_to_their_own_axes(new_scene, leg):
    group = leg.build(L_LEG)
    hip = planar_chain.joints(group)[0]
    ball = planar_chain.joints("L_leg_foot_guides_grp")[0]
    assert _axis(hip, 0) == [0.0, -0.9701, 0.2425]  # leg aim +X: hip to knee
    assert _axis(ball, 2) == [0.0, 0.0, 1.0]  # foot aim +Z: ball to toe
    assert _axis(ball, 0) == [0.0, -1.0, 0.0]  # foot up -X: towards the foot's up guide


def test_default_layout_gives_the_foot_the_legs_axes(leg):
    layout = leg.default_layout("L_leg")
    assert (layout["foot_aim"], layout["foot_up_axis"]) == (layout["aim"], layout["up"])


def test_a_layout_without_foot_axes_uses_the_legs(new_scene, leg):
    older = {k: v for k, v in L_LEG.items() if k not in ("foot_aim", "foot_up_axis")}
    assert leg.problems(older) == []
    group = leg.build(older)
    assert leg.layout(group) == dict(older, foot_aim="x", foot_up_axis="y")


def test_problems_with_the_foot_axes(new_scene, leg):
    assert leg.problems(dict(L_LEG, foot_up_axis="-z")) == [
        "L_leg foot: The aim axis and the up axis must be different axes."
    ]


def test_restore_puts_the_foot_axes_back(new_scene, leg):
    group = leg.build(L_LEG)
    leg.set_axes(group, "foot", "y", "x")
    leg.restore(group, L_LEG)
    assert leg.layout(group) == L_LEG


def test_file_round_trip(tmp_path, leg):
    path = spec.write(os.path.join(tmp_path, "L_leg.guide"), "leg", L_LEG)
    assert spec.load(path) == (leg, L_LEG)
