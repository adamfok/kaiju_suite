import json

import pytest
from maya import cmds

from kaiju_suite import rigging
from kaiju_suite.rigging import controls
from rig_cases import CASES


def _circle(name, parent=None):
    node = cmds.circle(name=name, constructionHistory=False)[0]
    return cmds.parent(node, parent)[0] if parent else node


def _short(nodes):
    return sorted(cmds.ls(nodes))


# -- add ----------------------------------------------------------------------


def test_add_tags_the_control_and_puts_it_in_the_controls_set(new_scene):
    control = _circle("a_ctrl")

    assert controls.add(control) == "a_ctrl"

    assert controls.is_control("a_ctrl")
    assert controls.tag("a_ctrl") == "a_ctrl_tag"
    assert cmds.nodeType("a_ctrl_tag") == "controller"
    assert cmds.nodeType(controls.SET) == "objectSet"
    assert _short(controls.all_controls()) == ["a_ctrl"]


def test_a_plain_node_is_not_a_control(new_scene):
    _circle("a_ctrl")
    assert not controls.is_control("a_ctrl")
    assert controls.tag("a_ctrl") is None
    assert controls.defaults("a_ctrl") == {}
    assert controls.all_controls() == []


def test_add_stores_the_keyable_values_as_built(new_scene):
    control = _circle("a_ctrl")
    cmds.setAttr(f"{control}.translateX", 2.5)
    cmds.addAttr(control, longName="stretch", attributeType="double", defaultValue=1, keyable=True)
    cmds.setAttr(f"{control}.scaleZ", lock=True)
    cmds.setAttr(f"{control}.visibility", keyable=False)

    controls.add(control)

    stored = controls.defaults(control)
    assert stored["translateX"] == 2.5
    assert stored["rotateY"] == 0
    assert stored["scaleX"] == 1
    assert stored["stretch"] == 1
    # Locked and non-keyable attributes can't be reset, so they aren't stored.
    assert "scaleZ" not in stored
    assert "visibility" not in stored
    assert json.loads(cmds.getAttr(f"{control}.{controls.DEFAULTS}")) == stored


def test_adding_again_keeps_the_stored_defaults_and_adds_new_attributes(new_scene):
    """E.g. Space Switch adds its enum to a control a rig module already made."""
    control = _circle("a_ctrl")
    controls.add(control)
    cmds.setAttr(f"{control}.translateX", 4)  # posed after the build
    cmds.addAttr(control, longName="space", attributeType="enum", enumName="world:chest", keyable=True)
    cmds.setAttr(f"{control}.space", 1)

    controls.add(control)

    stored = controls.defaults(control)
    assert stored["translateX"] == 0
    assert stored["space"] == 1
    assert len(cmds.ls(type="controller")) == 1
    assert _short(controls.all_controls()) == ["a_ctrl"]


def test_add_sets_the_pickwalk_parent(new_scene):
    root = controls.add(_circle("root_ctrl"))
    child = controls.add(_circle("child_ctrl", root), parent=root)

    assert controls.pickwalk_parent(child) == "root_ctrl"
    assert controls.pickwalk_parent(root) is None


def test_adding_again_without_a_parent_keeps_the_pickwalk_parent(new_scene):
    root = controls.add(_circle("root_ctrl"))
    child = controls.add(_circle("child_ctrl", root), parent=root)

    controls.add(child)

    assert controls.pickwalk_parent(child) == "root_ctrl"


def test_controls_of_several_rigs_share_one_set(new_scene):
    controls.add(_circle("a_ctrl"))
    controls.add(_circle("b_ctrl"))

    assert cmds.ls(type="objectSet").count(controls.SET) == 1
    assert _short(controls.all_controls()) == ["a_ctrl", "b_ctrl"]


def test_add_puts_the_control_in_its_rig_module_set_too(new_scene):
    a = controls.add(_circle("a_ctrl"), rig_module_set="L_arm_ik_controls_set")
    controls.add(_circle("b_ctrl"), rig_module_set="L_arm_ik_controls_set")
    controls.add(_circle("c_ctrl"))

    assert cmds.nodeType("L_arm_ik_controls_set") == "objectSet"
    assert _short(cmds.sets("L_arm_ik_controls_set", query=True)) == ["a_ctrl", "b_ctrl"]
    # The rig module set sits beside the rig-wide one, not in it.
    assert _short(controls.all_controls()) == ["a_ctrl", "b_ctrl", "c_ctrl"]
    assert controls.rig_module_sets(a) == ["L_arm_ik_controls_set"]


def test_rig_module_set_name_follows_the_rig_module_group():
    assert controls.rig_module_set_name("L_arm_ik_grp") == "L_arm_ik_controls_set"
    assert controls.rig_module_set_name("odd") == "odd_controls_set"


# -- reset --------------------------------------------------------------------


def _posed_pair():
    a = controls.add(_circle("a_ctrl"))
    cmds.addAttr(a, longName="stretch", attributeType="double", defaultValue=1, keyable=True)
    controls.add(a)
    b = controls.add(_circle("b_ctrl"))
    cmds.setAttr(f"{a}.translateY", 3)
    cmds.setAttr(f"{a}.stretch", 0.25)
    cmds.setAttr(f"{b}.rotateZ", 45)
    return a, b


def test_reset_puts_the_given_controls_back_to_their_defaults(new_scene):
    a, b = _posed_pair()

    assert _short(controls.reset([a])) == ["a_ctrl"]

    assert cmds.getAttr(f"{a}.translateY") == 0
    assert cmds.getAttr(f"{a}.stretch") == 1
    assert cmds.getAttr(f"{b}.rotateZ") == 45


def test_reset_with_no_nodes_resets_every_control(new_scene):
    a, b = _posed_pair()

    assert _short(controls.reset()) == ["a_ctrl", "b_ctrl"]

    assert cmds.getAttr(f"{a}.translateY") == 0
    assert cmds.getAttr(f"{b}.rotateZ") == 0


def test_reset_skips_nodes_that_are_not_controls(new_scene):
    a, _ = _posed_pair()
    other = _circle("other")
    cmds.setAttr(f"{other}.translateX", 5)

    assert _short(controls.reset([a, other])) == ["a_ctrl"]
    assert cmds.getAttr(f"{other}.translateX") == 5


def test_reset_skips_attributes_locked_or_driven_since(new_scene):
    a, _ = _posed_pair()
    cmds.setAttr(f"{a}.translateY", lock=True)
    driver = cmds.createNode("transform", name="driver", skipSelect=True)
    cmds.setAttr(f"{driver}.translateX", 7)
    cmds.connectAttr(f"{driver}.translateX", f"{a}.stretch")

    controls.reset([a])

    assert cmds.getAttr(f"{a}.translateY") == 3
    assert cmds.getAttr(f"{a}.stretch") == 7


def test_reset_is_one_undo_step(new_scene):
    a, b = _posed_pair()
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    controls.reset()
    cmds.undo()

    assert cmds.getAttr(f"{a}.translateY") == 3
    assert cmds.getAttr(f"{a}.stretch") == 0.25
    assert cmds.getAttr(f"{b}.rotateZ") == 45


# -- every rig module ---------------------------------------------------------

PICKWALK = {
    "root": {"main_offset_ctrl": "main_root_ctrl"},
    "fk_chain": {"L_finger_02_fk_ctrl": "L_finger_01_fk_ctrl", "L_finger_03_fk_ctrl": "L_finger_02_fk_ctrl"},
    "simple_ik": {"L_arm_pv_ctrl": "L_arm_ik_ctrl"},
    "stretchy_ik": {"L_arm_pv_ctrl": "L_arm_ik_ctrl"},
    "ik_fk": {
        "L_arm_ik_ctrl": "L_arm_switch_ctrl",
        "L_arm_pv_ctrl": "L_arm_ik_ctrl",
        "L_arm_01_fk_ctrl": "L_arm_switch_ctrl",
        "L_arm_02_fk_ctrl": "L_arm_01_fk_ctrl",
        "L_arm_03_fk_ctrl": "L_arm_02_fk_ctrl",
    },
    "spline_ik": {"spine_chest_ctrl": "spine_hip_ctrl"},
}


RIG_MODULE_SETS = {
    "root": "main_root_controls_set",
    "single_fk": "L_elbow_fk_controls_set",
    "fk_chain": "L_finger_fkChain_controls_set",
    "simple_ik": "L_arm_ik_controls_set",
    "stretchy_ik": "L_arm_stretchIk_controls_set",
    "ik_fk": "L_arm_ikfk_controls_set",
    "spline_ik": "spine_splineIk_controls_set",
}


@pytest.mark.parametrize("key", sorted(RIG_MODULE_SETS))
def test_every_rig_module_makes_a_set_of_its_controls(new_scene, key):
    params, expected = CASES[key]()

    rigging.get_rig_module(key).build(params)

    assert _short(cmds.sets(RIG_MODULE_SETS[key], query=True)) == sorted(expected)


def test_space_switch_makes_no_rig_module_set(new_scene):
    params, _ = CASES["space_switch"]()
    before = set(cmds.ls(type="objectSet"))

    rigging.get_rig_module("space_switch").build(params)

    assert set(cmds.ls(type="objectSet")) - before == {controls.SET}


def test_every_rig_module_has_a_case():
    assert sorted(CASES) == sorted(m.key for m in rigging.all_rig_modules())


@pytest.mark.parametrize("key", sorted(CASES))
def test_every_rig_module_makes_its_controls_rig_controls(new_scene, key):
    params, expected = CASES[key]()

    rigging.get_rig_module(key).build(params)

    assert _short(controls.all_controls()) == sorted(expected)
    for control in expected:
        assert controls.tag(control) == f"{control}_tag"
        stored = controls.defaults(control)
        keyable = cmds.listAttr(control, keyable=True, unlocked=True, scalar=True) or []
        assert sorted(stored) == sorted(a for a in keyable if cmds.getAttr(f"{control}.{a}", settable=True))
        assert controls.pickwalk_parent(control) == PICKWALK.get(key, {}).get(control)


def test_space_switch_stores_its_enum_at_the_default_space(new_scene):
    params, _ = CASES["space_switch"]()
    rigging.get_rig_module("space_switch").build(dict(params, default_space="chest"))

    assert controls.defaults("hand_ctrl")["space"] == 1


@pytest.mark.parametrize(
    "key, control, attr, default",
    [
        ("root", "main_root_ctrl", "globalScale", 1),
        ("stretchy_ik", "L_arm_ik_ctrl", "stretch", 1),
        ("ik_fk", "L_arm_switch_ctrl", "ikFk", 0),
    ],
)
def test_rig_module_attributes_reset_to_their_defaults(new_scene, key, control, attr, default):
    params, expected = CASES[key]()
    rigging.get_rig_module(key).build(params)
    cmds.setAttr(f"{control}.{attr}", 0.5)
    posed = expected[-1]  # e.g. an FK control: the switch's own rotation is locked
    cmds.setAttr(f"{posed}.rotateX", 30)

    controls.reset()

    assert cmds.getAttr(f"{control}.{attr}") == default
    assert cmds.getAttr(f"{posed}.rotateX") == 0


def test_undoing_a_rig_module_build_removes_its_controls(new_scene):
    params, _ = CASES["simple_ik"]()
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    rigging.get_rig_module("simple_ik").build(params)
    cmds.undo()

    assert controls.all_controls() == []
    assert cmds.ls(type="controller") == []
    assert not cmds.objExists("L_arm_ik_controls_set")
