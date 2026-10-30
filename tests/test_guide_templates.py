import pytest
from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.core.selection import short_name
from kaiju_suite.tools.guide_tool import logic, templates

_FINGERS = ("index", "middle", "ring", "pinky")
_BIPED = [
    "root", "spine", "neck", "head", "l_shoulder", "l_arm", "l_hand",
    *(f"l_{f}_metacarpal" for f in _FINGERS), "l_thumb", *(f"l_{f}" for f in _FINGERS),
    "l_leg", "l_foot",
]


def _pos(node):
    return om.MVector(cmds.xform(node, query=True, worldSpace=True, translation=True))


def _close(a, b, tolerance=1e-3):
    return (om.MVector(a) - om.MVector(b)).length() < tolerance


def _axis(node, axis):
    m = om.MMatrix(cmds.xform(node, query=True, worldSpace=True, matrix=True))
    row = "xyz".index(axis)
    return om.MVector(m[row * 4], m[row * 4 + 1], m[row * 4 + 2]).normalize()


def _chains(name="biped"):
    return {chain["name"]: chain for chain in templates.TEMPLATES[name]}


# -- the data ---------------------------------------------------------------------


def test_biped_has_every_chain_in_order():
    assert list(templates.TEMPLATES) == ["biped"]
    assert [chain["name"] for chain in templates.TEMPLATES["biped"]] == _BIPED


def test_biped_chains_connect():
    c = _chains()
    for a, b in (("spine", "neck"), ("neck", "head"), ("l_shoulder", "l_arm"), ("l_arm", "l_hand"),
                 ("l_leg", "l_foot")):
        assert _close(c[a]["end"], c[b]["start"]), (a, b)
    for finger in _FINGERS:
        assert _close(c[f"l_{finger}_metacarpal"]["start"], c["l_hand"]["start"]), finger
        assert _close(c[f"l_{finger}_metacarpal"]["end"], c[f"l_{finger}"]["start"]), finger


def test_biped_chain_shapes():
    c = _chains()
    assert not c["root"]["end_joint"] and _close(c["root"]["start"], (0, 0, 0))
    for finger in _FINGERS:
        assert c[f"l_{finger}_metacarpal"]["count"] == 0 and c[f"l_{finger}_metacarpal"]["end_joint"]
        assert c[f"l_{finger}"]["count"] == 2 and c[f"l_{finger}"]["end_joint"]
    assert c["l_thumb"]["count"] == 2
    for name, chain in c.items():
        assert chain["mirror"] == name.startswith("l_"), name


def test_biped_chains_go_the_way_their_presets_do():
    c = _chains()
    for name, preset in logic.PRESETS.items():
        if name not in c:
            continue
        chain = c[name]
        way = om.MVector(chain["end"]) - om.MVector(chain["start"])
        preset_way = om.MVector(preset["end"]) - om.MVector(preset["start"])
        assert (way.normal() - preset_way.normal()).length() < 1e-6, name
        for key in ("count", "aim", "up", "up_side", "end_joint", "mirror"):
            assert chain[key] == preset[key], (name, key)


# -- check_build ------------------------------------------------------------------


def test_check_build_passes_and_changes_nothing(new_scene):
    before = set(cmds.ls())

    logic.check_build("arm", 1, mirror=True)

    assert set(cmds.ls()) == before


def test_check_build_refuses_what_build_guides_refuses(new_scene):
    cmds.createNode("transform", name="arm_r_02_jnt")
    with pytest.raises(ValueError, match="arm_r_02_jnt"):
        logic.check_build("arm_l", 1, mirror=True)
    with pytest.raises(ValueError):
        logic.check_build("arm", -1)
    with pytest.raises(ValueError):
        logic.check_build("arm", 1, start=(1, 1, 1), end=(1, 1, 1))


def test_check_build_lets_a_chain_build_again(new_scene):
    logic.build_guides("arm", 1, mirror=True)

    logic.check_build("arm", 3, mirror=True)


# -- build_template -----------------------------------------------------------------


def test_build_template_builds_every_chain_where_it_goes(new_scene):
    groups = templates.build_template("biped")

    assert [cmds.getAttr(f"{g}.kaijuGuides") for g in groups] == _BIPED
    for group, chain in zip(groups, templates.TEMPLATES["biped"]):
        found = logic.guides(group)["chain"]
        assert len(found) == chain["count"] + 2
        assert _close(_pos(found[0]), chain["start"]) and _close(_pos(found[-1]), chain["end"]), chain["name"]
        assert bool(logic.mirrored_joints(group)) == chain["mirror"]


def test_biped_fingers_and_metacarpals(new_scene):
    templates.build_template("biped")

    group = logic.find_group(["l_index_metacarpal_guides_grp"])
    assert [short_name(j) for j in logic.joints(group)] == [
        "l_index_metacarpal_01_jnt", "l_index_metacarpal_02_jnt_end"
    ]
    finger = logic.find_group(["l_index_guides_grp"])
    joints = logic.joints(finger)
    assert len(joints) == 4 and short_name(joints[-1]) == "l_index_04_jnt_end"
    assert _close(_pos(joints[0]), _pos(logic.joints(group)[-1]))
    assert short_name(logic.mirrored_joints(finger)[0]) == "r_index_01_jnt"


def test_biped_axes_follow_the_presets(new_scene):
    templates.build_template("biped")

    for joint in logic.joints("spine_guides_grp"):
        assert (_axis(joint, "y") - om.MVector(0, 1, 0)).length() < 1e-3
        assert (_axis(joint, "z") - om.MVector(0, 0, -1)).length() < 1e-3
    for joint in logic.joints("l_arm_guides_grp"):
        assert (_axis(joint, "x") - om.MVector(1, 0, 0)).length() < 1e-3
        assert (_axis(joint, "y") - om.MVector(0, 0, -1)).length() < 1e-3


def test_build_template_is_one_undo_step(new_scene):
    templates.build_template("biped")
    cmds.undo()

    assert not cmds.ls("*_guides_grp")
    assert not cmds.ls(type="joint")


def test_build_template_refuses_a_taken_name_and_builds_nothing(new_scene):
    cmds.createNode("transform", name="l_ring_02_jnt")
    before = set(cmds.ls())

    with pytest.raises(ValueError, match="l_ring_02_jnt"):
        templates.build_template("biped")

    assert set(cmds.ls()) == before


def test_build_template_again_keeps_the_joints(new_scene):
    groups = templates.build_template("biped")
    before = [cmds.ls(logic.joints(g), uuid=True) for g in groups]

    groups = templates.build_template("biped")

    assert [cmds.ls(logic.joints(g), uuid=True) for g in groups] == before


def test_build_template_refuses_an_unknown_template(new_scene):
    with pytest.raises(ValueError, match="dragon"):
        templates.build_template("dragon")
