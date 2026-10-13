import pytest
from maya import cmds

from kaiju_suite.rigging.rig_module import get_rig_module
from rig_cases import CASES


def _transforms():
    return set(cmds.ls(type="transform"))


@pytest.mark.parametrize("key", sorted(CASES))
def test_outputs_are_the_transforms_create_builds(new_scene, key):
    params, _ = CASES[key]()
    rig_module = get_rig_module(key)
    before = _transforms()

    outputs = rig_module.outputs(params)
    assert _transforms() == before  # without touching the scene

    rig_module.build(params)
    assert len(outputs) == len(set(outputs))
    assert sorted(outputs) == sorted(_transforms() - before)


def test_space_switch_outputs_with_a_driven_group(new_scene):
    params, _ = CASES["space_switch"]()
    params["driven"] = "hand_ctrl_grp"
    rig_module = get_rig_module("space_switch")
    before = _transforms()

    outputs = rig_module.outputs(params)
    rig_module.build(params)

    assert outputs == ["hand_ctrl_space_parentConstraint"]
    assert sorted(_transforms() - before) == outputs


def test_spline_ik_outputs_with_a_given_curve(new_scene):
    params, _ = CASES["spline_ik"]()
    params["curve"] = cmds.curve(name="guide", degree=1, point=[(0, 0, 0), (0, 2, 0), (0, 4, 0)])
    rig_module = get_rig_module("spline_ik")
    before = _transforms()

    outputs = rig_module.outputs(params)
    rig_module.build(params)

    assert sorted(outputs) == sorted(_transforms() - before)


def test_fk_chain_without_end_control(new_scene):
    params, _ = CASES["fk_chain"]()
    params["end_control"] = False
    rig_module = get_rig_module("fk_chain")
    before = _transforms()

    outputs = rig_module.outputs(params)
    rig_module.build(params)

    assert "L_finger_03_fk_ctrl" not in outputs
    assert sorted(outputs) == sorted(_transforms() - before)


@pytest.mark.parametrize("key", ["fk_chain", "ik_fk"])
def test_chain_dependent_outputs_without_the_chain_list_what_they_can(new_scene, key):
    """Names that depend on how many joints the chain has need the chain."""
    params, _ = CASES[key]()
    cmds.file(new=True, force=True)

    outputs = get_rig_module(key).outputs(params)

    group = {"fk_chain": "L_finger_fkChain_grp", "ik_fk": "L_arm_ikfk_grp"}[key]
    assert group in outputs
    assert not any("_01_" in name for name in outputs)


def test_outputs_take_incomplete_params(new_scene):
    assert get_rig_module("root").outputs({"name": "hero"}) == ["hero_root_grp", "hero_root_ctrl", "hero_offset_ctrl"]


# -- the nodes a rig module needs -------------------------------------------------


def test_node_refs_are_the_filled_node_parameters():
    rig_module = get_rig_module("simple_ik")
    params = rig_module.complete({"start_joint": "shoulder", "end_joint": " wrist ", "parent": ""})

    assert rig_module.node_refs(params) == [("Start joint", "shoulder"), ("End joint", "wrist")]


def test_space_switch_node_refs_include_its_spaces():
    rig_module = get_rig_module("space_switch")
    params = rig_module.complete({"control": "hand_ctrl", "spaces": "world=world_space, chest=chest_ctrl"})

    assert rig_module.node_refs(params) == [
        ("Control", "hand_ctrl"),
        ("Space 'world' node", "world_space"),
        ("Space 'chest' node", "chest_ctrl"),
    ]


def test_space_switch_node_refs_skip_spaces_that_cannot_be_read():
    rig_module = get_rig_module("space_switch")
    params = rig_module.complete({"control": "hand_ctrl", "spaces": "a=b=c"})

    assert rig_module.node_refs(params) == [("Control", "hand_ctrl")]
