"""The Quad Leg guide module (kaiju_suite.rigging.guide_module.modules.quad_leg):
a hip-stifle-hock-fetlock chain with the shared foot (hoof, toe and the
reverse foot's pivots, kaiju_suite.rigging.guide_module.foot) under the
fetlock."""

import os

import pytest
from maya import cmds

from kaiju_suite.rigging.guide_module import delete_all_guides, foot, get_guide_module, planar_chain, spec
from kaiju_suite.rigging.guide_module.guide_module import GuideError

L_HIND = {
    "name": "L_hind",
    "aim": "x",
    "up": "y",
    "leg": [[2.0, 10.0, 0.0], [2.0, 7.0, 1.0], [2.0, 4.0, -1.0], [2.0, 1.0, -0.5]],
    "leg_up": [2.0, 6.0, 6.0],
    "foot": [[2.0, 0.0, 0.0], [2.0, 0.0, 1.0]],
    "foot_up": [2.0, 3.0, 0.5],
    "heel": [2.0, 0.0, -0.5],
    "inner": [1.5, 0.0, 0.5],
    "outer": [2.5, 0.0, 0.5],
    "foot_aim": "z",
    "foot_up_axis": "-x",
}
FOOT = "L_hind_foot_guides_grp"


@pytest.fixture
def quad():
    return get_guide_module("quad_leg")


def _pos(node):
    return [round(v, 5) + 0.0 for v in cmds.xform(node, query=True, worldSpace=True, translation=True)]


def test_quad_leg_is_discovered(quad):
    assert quad.name == "Quad Leg Guide"
    assert quad.mirrorable


def test_it_reuses_the_shared_foot_helper(quad):
    from kaiju_suite.rigging.guide_module.modules import leg, quad_leg

    assert quad_leg.foot is foot
    assert isinstance(quad, leg.LegGuideModule)


def test_default_layout_is_a_buildable_quad_leg(new_scene, quad):
    layout = quad.default_layout("L_hind")
    assert layout["name"] == "L_hind"
    assert len(layout["leg"]) == 4 and len(layout["foot"]) == 2
    assert quad.problems(layout) == []
    group = quad.build(layout)
    assert quad.layout(group) == layout


def test_default_layout_falls_back_to_quad_leg_for_a_name_that_cant_name_nodes(quad):
    assert quad.default_layout("2 legs")["name"] == "quad_leg"


def test_default_layout_gives_the_foot_the_legs_axes(quad):
    layout = quad.default_layout("L_hind")
    assert (layout["foot_aim"], layout["foot_up_axis"]) == (layout["aim"], layout["up"])


def test_build_makes_four_leg_joints_with_the_foot_under_the_fetlock(new_scene, quad):
    group = quad.build(L_HIND)

    assert cmds.ls(group) == ["L_hind_guides_grp"]
    assert cmds.getAttr(f"{group}.kaijuGuideModule") == "quad_leg"
    hip, stifle, hock, fetlock = planar_chain.joints(group)
    hoof, toe = planar_chain.joints(FOOT)
    assert cmds.listRelatives(hoof, parent=True, fullPath=True) == [fetlock]
    assert [_pos(j) for j in (hip, stifle, hock, fetlock, hoof, toe)] == L_HIND["leg"] + L_HIND["foot"]
    # The fetlock guide is shared, not duplicated.
    assert planar_chain.guides(FOOT)["chain"][0] == planar_chain.guides(group)["chain"][-1]


def test_build_makes_the_pivots(new_scene, quad):
    group = quad.build(L_HIND)
    pivots = foot.pivots(group)
    assert [cmds.ls(p)[0] for p in pivots.values()] == ["L_hind_heel_pivot", "L_hind_inner_pivot", "L_hind_outer_pivot"]
    for key, pivot in pivots.items():
        assert _pos(pivot) == L_HIND[key]


def test_the_joints_follow_the_guides_live(new_scene, quad):
    group = quad.build(L_HIND)
    hock_guide = planar_chain.guides(group)["chain"][2]
    cmds.xform(hock_guide, worldSpace=True, translation=(2, 4, -2))
    assert _pos(planar_chain.joints(group)[2]) == [2.0, 4.0, -2.0]
    assert quad.layout(group)["leg"][2] == [2.0, 4.0, -2.0]


def test_build_is_one_undo_step(new_scene, quad):
    cmds.undoInfo(state=True)
    cmds.flushUndo()
    before = set(cmds.ls())
    quad.build(L_HIND)
    cmds.undo()
    assert set(cmds.ls()) == before


def test_problems(new_scene, quad):
    assert quad.problems({"name": "a"}) == [
        "The Quad Leg Guide layout is missing aim, up, leg, leg_up, foot, foot_up, heel, inner, outer."
    ]
    assert quad.problems(dict(L_HIND, leg=L_HIND["leg"][:3])) == [
        "L_hind: leg needs 4 guides (hip, stifle, hock, fetlock)."
    ]
    assert quad.problems(dict(L_HIND, foot=L_HIND["foot"] * 2)) == ["L_hind: foot needs 2 guides (hoof, toe)."]
    quad.build(L_HIND)
    assert quad.problems(L_HIND) == ["Guides already in the scene: L_hind. Delete them first."]


def test_a_leg_layout_is_not_a_quad_leg_layout(quad):
    leg = get_guide_module("leg")
    assert quad.problems(leg.default_layout("L_leg")) == ["L_leg: leg needs 4 guides (hip, stifle, hock, fetlock)."]
    assert leg.problems(quad.default_layout("L_hind")) == ["L_hind: leg needs 3 guides (hip, knee, ankle)."]


def test_describe_and_fields(quad):
    assert quad.describe(L_HIND) == [
        "L_hind: hip, stifle, hock, fetlock, hoof, toe; heel, inner and outer pivots; "
        "leg aim x, up y; foot aim z, up -x"
    ]
    assert quad.nodes(L_HIND) == ["L_hind_guides_grp"]
    assert quad.fields(L_HIND) == {
        "name": "L_hind",
        "axes": [
            {"part": "leg", "label": "Leg", "aim": "x", "up": "y"},
            {"part": "foot", "label": "Foot", "aim": "z", "up": "-x"},
        ],
    }


def test_mirrored_flips_across_x_and_reverses_the_axes(quad):
    mirrored = quad.mirrored(L_HIND)
    assert mirrored["name"] == "R_hind"
    assert (mirrored["aim"], mirrored["up"]) == ("-x", "-y")
    assert (mirrored["foot_aim"], mirrored["foot_up_axis"]) == ("-z", "x")
    assert mirrored["leg"][3] == [-2.0, 1.0, -0.5]
    assert mirrored["inner"] == [-1.5, 0.0, 0.5]
    assert quad.mirrored(mirrored) == L_HIND


def test_mirrored_joints_turn_in_mirror_image(new_scene, quad):
    left, right = quad.build(L_HIND), quad.build(quad.mirrored(L_HIND))
    assert cmds.ls(right) == ["R_hind_guides_grp"]
    for l_joint, r_joint in zip(
        planar_chain.joints(left) + planar_chain.joints(FOOT),
        planar_chain.joints(right) + planar_chain.joints("R_hind_foot_guides_grp"),
    ):
        l_m = cmds.xform(l_joint, query=True, worldSpace=True, matrix=True)
        r_m = cmds.xform(r_joint, query=True, worldSpace=True, matrix=True)
        for axis in range(3):
            l_row, r_row = l_m[axis * 4 : axis * 4 + 3], r_m[axis * 4 : axis * 4 + 3]
            assert [round(v, 4) + 0.0 for v in r_row] == [round(v, 4) + 0.0 for v in (l_row[0], -l_row[1], -l_row[2])]


def test_set_axes_turns_one_part(new_scene, quad):
    group = quad.build(L_HIND)
    quad.set_axes(group, "leg", "y", "x")
    assert (quad.layout(group)["aim"], quad.layout(group)["up"]) == ("y", "x")
    assert quad.layout(group)["foot_aim"] == "z"


def test_restore_puts_everything_back(new_scene, quad):
    group = quad.build(L_HIND)
    cmds.xform(planar_chain.guides(group)["chain"][2], worldSpace=True, translation=(2, 4, -3))
    cmds.xform(foot.pivots(group)["heel"], worldSpace=True, translation=(2, 0, -2))
    quad.set_axes(group, "foot", "y", "x")
    quad.restore(group, L_HIND)
    assert quad.layout(group) == L_HIND


def test_restore_is_one_undo_step(new_scene, quad):
    group = quad.build(L_HIND)
    cmds.xform(foot.pivots(group)["outer"], worldSpace=True, translation=(4, 0, 2))
    moved = quad.layout(group)
    cmds.undoInfo(state=True)
    cmds.flushUndo()
    quad.restore(group, L_HIND)
    cmds.undo()
    assert quad.layout(group) == moved


def test_restore_refuses_a_broken_layout(new_scene, quad):
    group = quad.build(L_HIND)
    with pytest.raises(GuideError, match="leg needs 4 guides"):
        quad.restore(group, dict(L_HIND, leg=L_HIND["leg"][:3]))
    assert quad.layout(group) == L_HIND


def test_extract_keeps_every_joint_where_it_is(new_scene, quad):
    group = quad.build(L_HIND)
    uuids = cmds.ls(planar_chain.joints(group) + planar_chain.joints(FOOT), uuid=True)

    joints = quad.extract(group)

    assert cmds.ls(joints, uuid=True) == uuids
    assert [_pos(j) for j in joints] == L_HIND["leg"] + L_HIND["foot"]
    assert cmds.ls(type="locator") == []
    assert cmds.listRelatives(joints[4], parent=True, fullPath=True) == cmds.ls(joints[3], long=True)


def test_extract_is_one_undo_step(new_scene, quad):
    group = quad.build(L_HIND)
    cmds.undoInfo(state=True)
    cmds.flushUndo()
    quad.extract(group)
    cmds.undo()
    assert quad.layout("L_hind_guides_grp") == L_HIND


def test_delete_all_guides_extracts_the_quad_leg(new_scene, quad):
    quad.build(L_HIND)
    extracted = delete_all_guides()
    assert list(extracted) == ["L_hind"]
    assert len(extracted["L_hind"]) == 6


# -- the guide file and the Assembler's datatype interface --------------------


def test_any_quad_leg_node_finds_it(new_scene, quad):
    group = quad.build(L_HIND)
    for node in (planar_chain.guides(group)["chain"][-1], planar_chain.joints(FOOT)[0], foot.pivots(group)["heel"]):
        assert spec.find_group([node]) == (quad, cmds.ls(group, long=True)[0]), node


def test_gather_then_apply_builds_it_again(new_scene, quad):
    group = quad.build(L_HIND)
    payload = spec.gather([foot.pivots(group)["inner"]])
    assert payload == {"guide_module": "quad_leg", "layout": L_HIND}
    cmds.file(new=True, force=True)
    spec.apply(payload)
    assert quad.layout("L_hind_guides_grp") == L_HIND


def test_file_round_trip(tmp_path, quad):
    path = spec.write(os.path.join(tmp_path, "L_hind.guide"), "quad_leg", L_HIND)
    assert spec.load(path) == (quad, L_HIND)
