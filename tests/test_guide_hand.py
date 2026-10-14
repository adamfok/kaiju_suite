"""The Hand guide module (kaiju_suite.rigging.guide_module.modules.hand): a
wrist joint with one finger chain per finger hanging under it, the first
finger optionally a thumb with one middle joint fewer."""

import os

import pytest
from maya import cmds

from kaiju_suite.rigging.guide_module import delete_all_guides, get_guide_module, planar_chain, spec
from kaiju_suite.rigging.guide_module.guide_module import GuideError

THUMB = {"guides": [[10.6, -0.2, 0.7], [11.2, -0.4, 1.0], [11.8, -0.6, 1.3]], "up_guide": [11.2, 0.6, 1.3]}
INDEX = {"guides": [[11.5, 0.0, 0.4], [12.2, 0.0, 0.4], [12.7, 0.0, 0.4], [13.1, 0.0, 0.4]], "up_guide": [12.3, 1.0, 0.4]}
MIDDLE = {"guides": [[11.5, 0.0, -0.4], [12.1, 0.0, -0.4], [12.6, 0.0, -0.4], [13.0, 0.0, -0.4]], "up_guide": [12.3, 1.0, -0.4]}
L_HAND = {
    "name": "L_hand",
    "aim": "x",
    "up": "y",
    "wrist": [10.0, 0.0, 0.0],
    "palm": [11.5, 0.0, 0.0],
    "hand_up": [10.75, 1.5, 0.0],
    "thumb": True,
    "fingers": [THUMB, INDEX, MIDDLE],
}


@pytest.fixture
def hand():
    return get_guide_module("hand")


def _pos(node):
    return [round(v, 5) + 0.0 for v in cmds.xform(node, query=True, worldSpace=True, translation=True)]


def _finger_group(name):
    return cmds.ls(f"{name}_guides_grp", long=True)[0]


def test_hand_is_discovered(hand):
    assert hand.name == "Hand Guide"
    assert hand.mirrorable


def test_default_layout_is_five_fingers_with_a_thumb_and_two_middles(new_scene, hand):
    layout = hand.default_layout("L_hand")
    assert layout["name"] == "L_hand"
    assert layout["thumb"] is True
    assert [len(f["guides"]) for f in layout["fingers"]] == [3, 4, 4, 4, 4]
    assert hand.problems(layout) == []
    group = hand.build(layout)
    assert hand.layout(group) == layout


def test_default_layout_falls_back_to_hand_for_a_name_that_cant_name_nodes(hand):
    assert hand.default_layout("2 hands")["name"] == "hand"


def test_finger_names(hand):
    from kaiju_suite.rigging.guide_module.modules.hand import finger_names

    assert finger_names(5, True) == ["thumb", "index", "middle", "ring", "pinky"]
    assert finger_names(3, False) == ["index", "middle", "ring"]
    assert finger_names(6, False) == ["index", "middle", "ring", "pinky", "finger_05", "finger_06"]


def test_build_makes_a_wrist_with_the_fingers_under_it(new_scene, hand):
    group = hand.build(L_HAND)

    assert cmds.ls(group) == ["L_hand_guides_grp"]
    assert cmds.getAttr(f"{group}.kaijuGuideModule") == "hand"
    (wrist,) = planar_chain.joints(group)
    assert cmds.ls(wrist) == ["L_hand_01_jnt"]
    assert _pos(wrist) == L_HAND["wrist"]
    assert cmds.listRelatives(wrist, parent=True) is None
    for finger, expected in (("thumb", THUMB), ("index", INDEX), ("middle", MIDDLE)):
        joints = planar_chain.joints(_finger_group(f"L_hand_{finger}"))
        assert cmds.ls(joints) == [f"L_hand_{finger}_{i:02d}_jnt" for i in range(1, len(expected["guides"]) + 1)]
        assert [_pos(j) for j in joints] == expected["guides"]
        assert cmds.listRelatives(joints[0], parent=True, fullPath=True) == [wrist]
    assert len(cmds.ls(type="joint")) == 1 + 3 + 4 + 4


def test_the_joints_follow_the_guides_live(new_scene, hand):
    group = hand.build(L_HAND)
    index = _finger_group("L_hand_index")
    cmds.xform(planar_chain.guides(index)["chain"][0], worldSpace=True, translation=(11.4, 0.1, 0.4))
    assert _pos(planar_chain.joints(index)[0]) == [11.4, 0.1, 0.4]
    assert hand.layout(group)["fingers"][1]["guides"][0] == [11.4, 0.1, 0.4]


def test_build_is_one_undo_step(new_scene, hand):
    cmds.undoInfo(state=True)
    cmds.flushUndo()
    before = set(cmds.ls())
    hand.build(L_HAND)
    cmds.undo()
    assert set(cmds.ls()) == before


def test_problems(new_scene, hand):
    assert hand.problems({"name": "a"}) == [
        "The Hand Guide layout is missing aim, up, wrist, palm, hand_up, thumb, fingers."
    ]
    assert hand.problems(dict(L_HAND, palm="here")) == ["L_hand: every guide must be an [x, y, z] position."]
    assert hand.problems(dict(L_HAND, fingers=[])) == ["L_hand: a hand needs 1 finger or more."]
    assert hand.problems(dict(L_HAND, fingers=[{"guides": [[0, 0, 0]], "up_guide": [0, 1, 0]}])) == [
        "L_hand thumb: a finger needs 2 guides or more."
    ]
    assert hand.problems(dict(L_HAND, fingers=[{"guides": THUMB["guides"]}])) == [
        "L_hand: every finger needs guides and an up_guide."
    ]
    assert hand.problems(dict(L_HAND, thumb="yes")) == ["L_hand: thumb must be true or false."]
    in_line = dict(L_HAND, fingers=[THUMB, dict(INDEX, up_guide=[14.0, 0.0, 0.4]), MIDDLE])
    assert hand.problems(in_line) == [
        "L_hand index: The up guide is in line with the start and end guides; move it to the side."
    ]
    cmds.createNode("transform", name="L_hand_index_02_jnt")
    assert hand.problems(L_HAND) == [
        "L_hand index: These names are already used, rename or delete them first: L_hand_index_02_jnt"
    ]
    cmds.delete("L_hand_index_02_jnt")
    hand.build(L_HAND)
    assert hand.problems(L_HAND) == ["Guides already in the scene: L_hand. Delete them first."]


def test_describe_and_nodes(hand):
    assert hand.describe(L_HAND) == ["L_hand: wrist; thumb, index, middle; aim x, up y"]
    assert hand.nodes(L_HAND) == ["L_hand_guides_grp"]


def test_mirrored_flips_across_x_and_reverses_the_axes(hand):
    mirrored = hand.mirrored(L_HAND)
    assert mirrored["name"] == "R_hand"
    assert (mirrored["aim"], mirrored["up"]) == ("-x", "-y")
    assert mirrored["wrist"] == [-10.0, 0.0, 0.0]
    assert mirrored["fingers"][0]["guides"][0] == [-10.6, -0.2, 0.7]
    assert mirrored["fingers"][1]["up_guide"] == [-12.3, 1.0, 0.4]
    assert mirrored["thumb"] is True
    assert hand.mirrored(mirrored) == L_HAND


def test_mirrored_joints_turn_in_mirror_image(new_scene, hand):
    left, right = hand.build(L_HAND), hand.build(hand.mirrored(L_HAND))

    def every_joint(side):
        found = planar_chain.joints(f"{side}_hand_guides_grp")
        for finger in ("thumb", "index", "middle"):
            found += planar_chain.joints(f"{side}_hand_{finger}_guides_grp")
        return found

    for l_joint, r_joint in zip(every_joint("L"), every_joint("R")):
        l_m = cmds.xform(l_joint, query=True, worldSpace=True, matrix=True)
        r_m = cmds.xform(r_joint, query=True, worldSpace=True, matrix=True)
        for axis in range(3):
            l_row, r_row = l_m[axis * 4 : axis * 4 + 3], r_m[axis * 4 : axis * 4 + 3]
            assert [round(v, 4) + 0.0 for v in r_row] == [round(v, 4) + 0.0 for v in (l_row[0], -l_row[1], -l_row[2])]


def test_set_axes_turns_the_wrist_and_every_finger(new_scene, hand):
    group = hand.build(L_HAND)
    hand.set_axes(group, "hand", "z", "-x")
    layout = hand.layout(group)
    assert (layout["aim"], layout["up"]) == ("z", "-x")
    for finger in ("thumb", "index", "middle"):
        assert cmds.getAttr(f"L_hand_{finger}_guides_grp.previewAxes") == "z -x"
    with pytest.raises(ValueError, match="no 'leg' axes"):
        hand.set_axes(group, "leg", "x", "y")


def test_fields(hand):
    assert hand.fields(L_HAND) == {
        "name": "L_hand",
        "fingers": 3,
        "count": 2,
        "thumb": True,
        "axes": [{"part": "hand", "label": "", "aim": "x", "up": "y"}],
    }
    no_thumb = dict(L_HAND, thumb=False, fingers=[INDEX])
    assert hand.fields(no_thumb)["count"] == 2
    assert hand.fields(dict(L_HAND, fingers=[THUMB]))["count"] == 2  # only a thumb: one more than its own


# -- restoring ---------------------------------------------------------------------


def test_restore_puts_everything_back(new_scene, hand):
    group = hand.build(L_HAND)
    joints = cmds.ls(cmds.ls(type="joint"), uuid=True)
    cmds.xform(planar_chain.guides(group)["chain"][1], worldSpace=True, translation=(11.5, 0.5, 0))
    cmds.xform(planar_chain.guides("L_hand_thumb_guides_grp")["up"], worldSpace=True, translation=(11, 2, 2))

    assert hand.restore(group, L_HAND) == cmds.ls(group, long=True)[0]

    assert hand.layout(group) == L_HAND
    assert sorted(cmds.ls(cmds.ls(type="joint"), uuid=True)) == sorted(joints)  # same shape: the joints stay


def test_restore_to_another_shape_builds_the_hand_again(new_scene, hand):
    group = hand.build(L_HAND)
    two = dict(L_HAND, thumb=False, fingers=[INDEX, MIDDLE])
    group = hand.restore(group, two)
    assert hand.layout(group) == two
    assert cmds.getAttr(f"{group}.kaijuGuideModule") == "hand"
    assert not cmds.objExists("L_hand_thumb_guides_grp")
    assert not cmds.objExists("L_hand_thumb_01_jnt")
    assert len(cmds.ls(type="joint")) == 1 + 4 + 4


def test_restore_is_one_undo_step(new_scene, hand):
    group = hand.build(L_HAND)
    cmds.undoInfo(state=True)
    cmds.flushUndo()
    hand.restore(group, dict(L_HAND, fingers=[THUMB, INDEX]))
    cmds.undo()
    assert hand.layout("L_hand_guides_grp") == L_HAND


def test_restore_refuses_a_broken_layout(new_scene, hand):
    group = hand.build(L_HAND)
    with pytest.raises(GuideError, match="a finger needs 2 guides"):
        hand.restore(group, dict(L_HAND, fingers=[THUMB, dict(INDEX, guides=INDEX["guides"][:1])]))
    in_line = dict(L_HAND, fingers=[THUMB, INDEX], hand_up=[12.0, 0.0, 0.0])
    with pytest.raises(GuideError, match="in line"):
        hand.restore(group, in_line)
    assert hand.layout(group) == L_HAND


# -- changing the number of fingers and middle joints ----------------------------


def test_reshaped_changes_the_middles_of_every_finger(hand):
    layout = hand.reshaped(L_HAND, count=1)
    assert layout["fingers"][0]["guides"] == [THUMB["guides"][0], THUMB["guides"][-1]]  # thumb: one fewer
    assert layout["fingers"][1]["guides"] == [[11.5, 0.0, 0.4], [12.3, 0.0, 0.4], [13.1, 0.0, 0.4]]
    assert layout["fingers"][1]["up_guide"] == INDEX["up_guide"]
    assert hand.reshaped(L_HAND, count=2) == L_HAND  # unchanged fingers keep their guides


def test_reshaped_adds_fingers_past_the_last_one(hand):
    layout = hand.reshaped(L_HAND, fingers=4)
    added = layout["fingers"][3]
    assert added["guides"][0] == [11.5, 0.0, -1.2]  # as far past the middle finger as it is past the index
    assert added["up_guide"] == [12.3, 1.0, -1.2]
    assert layout["fingers"][:3] == L_HAND["fingers"]


def test_reshaped_adds_a_finger_away_from_the_thumb(hand):
    layout = hand.reshaped(dict(L_HAND, fingers=[THUMB, INDEX]), fingers=3)
    assert layout["fingers"][2]["guides"][0][2] < INDEX["guides"][0][2]


def test_reshaped_removes_fingers_from_the_end(hand):
    assert hand.reshaped(L_HAND, fingers=2)["fingers"] == [THUMB, INDEX]


def test_reshaped_turns_the_first_finger_into_a_thumb_and_back(hand):
    no_thumb = hand.reshaped(L_HAND, thumb=False)
    assert no_thumb["thumb"] is False
    assert len(no_thumb["fingers"][0]["guides"]) == 4
    assert no_thumb["fingers"][0]["guides"][0] == THUMB["guides"][0]
    again = hand.reshaped(no_thumb, thumb=True)
    assert again["thumb"] is True
    assert len(again["fingers"][0]["guides"]) == 3


def test_reshaped_refuses_what_it_cant_make(hand):
    with pytest.raises(ValueError, match="1 finger or more"):
        hand.reshaped(L_HAND, fingers=0)
    with pytest.raises(ValueError, match="thumb needs 1 middle joint"):
        hand.reshaped(L_HAND, count=0)
    assert len(hand.reshaped(dict(L_HAND, thumb=False), count=0)["fingers"][1]["guides"]) == 2


def test_reshape_builds_the_new_shape_as_one_undo_step(new_scene, hand):
    group = hand.build(L_HAND)
    cmds.undoInfo(state=True)
    cmds.flushUndo()
    group = hand.reshape(group, fingers=4)
    assert len(hand.layout(group)["fingers"]) == 4
    assert cmds.objExists("L_hand_ring_01_jnt")
    cmds.undo()
    assert hand.layout("L_hand_guides_grp") == L_HAND


def test_reshape_keeps_moved_guides(new_scene, hand):
    group = hand.build(L_HAND)
    cmds.xform(planar_chain.guides(group)["chain"][0], worldSpace=True, translation=(9, 0, 0))
    group = hand.reshape(group, count=3)
    layout = hand.layout(group)
    assert layout["wrist"] == [9.0, 0.0, 0.0]
    assert [len(f["guides"]) for f in layout["fingers"]] == [4, 5, 5]


# -- extracting --------------------------------------------------------------------


def test_extract_keeps_every_joint_where_it_is(new_scene, hand):
    group = hand.build(L_HAND)
    uuids = cmds.ls(cmds.ls(type="joint"), uuid=True)

    joints = hand.extract(group)

    assert sorted(cmds.ls(joints, uuid=True)) == sorted(uuids)
    assert cmds.ls(type="locator") == []
    assert not cmds.objExists("L_hand_guides_grp")
    assert _pos("L_hand_index_04_jnt") == INDEX["guides"][-1]
    assert cmds.listRelatives("L_hand_index_01_jnt", parent=True) == ["L_hand_01_jnt"]


def test_extract_is_one_undo_step(new_scene, hand):
    group = hand.build(L_HAND)
    cmds.undoInfo(state=True)
    cmds.flushUndo()
    hand.extract(group)
    cmds.undo()
    assert hand.layout("L_hand_guides_grp") == L_HAND


def test_check_extract_names_a_missing_finger_guide(new_scene, hand):
    group = hand.build(L_HAND)
    cmds.delete(planar_chain.guides("L_hand_index_guides_grp")["up"])
    (problem,) = hand.check_extract(group)
    assert "missing" in problem


def test_delete_all_guides_extracts_the_hand(new_scene, hand):
    hand.build(L_HAND)
    extracted = delete_all_guides()
    assert list(extracted) == ["L_hand"]
    assert len(extracted["L_hand"]) == 1 + 3 + 4 + 4


# -- the guide file and the Assembler's datatype interface --------------------


def test_any_hand_node_finds_the_hand(new_scene, hand):
    group = hand.build(L_HAND)
    index = "L_hand_index_guides_grp"
    nodes = [
        planar_chain.guides(group)["chain"][0],
        planar_chain.guides(index)["chain"][0],
        planar_chain.guides(index)["up"],
        planar_chain.joints(index)[2],
        planar_chain.joints(group)[0],
        index,
    ]
    for node in nodes:
        assert spec.find_group([node]) == (hand, cmds.ls(group, long=True)[0]), node


def test_gather_then_apply_builds_the_hand_again(new_scene, hand):
    group = hand.build(L_HAND)
    payload = spec.gather([planar_chain.joints("L_hand_middle_guides_grp")[0]])
    assert payload == {"guide_module": "hand", "layout": L_HAND}
    cmds.file(new=True, force=True)
    spec.apply(payload)
    assert hand.layout("L_hand_guides_grp") == L_HAND


def test_file_round_trip(tmp_path, hand):
    path = spec.write(os.path.join(tmp_path, "L_hand.guide"), "hand", L_HAND)
    assert spec.load(path) == (hand, L_HAND)


def test_building_reshaping_and_extracting_report_no_errors(new_scene, hand, maya_errors):
    group = hand.build(L_HAND)
    group = hand.reshape(group, fingers=4)
    hand.extract(group)
    assert maya_errors == []
