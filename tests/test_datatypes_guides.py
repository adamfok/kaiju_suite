"""Guide layouts save/load (kaiju_suite.datatypes.guides), without the
Assembler. The Assembler's Guide product (tests/test_assembler_guides.py)
goes through this module. One file holds one chain."""

import pytest
from maya import cmds

from kaiju_suite.core import guides as core_guides
from kaiju_suite.datatypes import guides
from kaiju_suite.tools.assembler import runlog

ONE_CHAIN = "Select guides of one chain, not arm_guides_grp, leg_guides_grp."


def _pos(node):
    return [round(v, 5) for v in cmds.xform(node, query=True, worldSpace=True, translation=True)]


def _arm():
    group = core_guides.build_guides("arm", 2, start=(0, 0, 0), end=(9, 0, 0), aim="-x", up="z")
    cmds.xform(core_guides.guides(group)["chain"][1], worldSpace=True, translation=(3, 1, 2))
    cmds.xform(core_guides.guides(group)["up"], worldSpace=True, translation=(4, 5, 0))
    return group


def _leg():
    return core_guides.build_guides("leg", 0, start=(0, 0, 0), end=(0, -8, 0))


def test_kind_and_extension():
    assert guides.KIND == "guides"
    assert guides.EXTENSION == ".guide"


def test_gather_saves_the_chain_from_any_of_its_nodes(new_scene):
    arm = _arm()
    picked = [core_guides.joints(arm)[0], core_guides.guides(arm)["up"], arm]
    payload = guides.gather(cmds.ls(picked, long=True))
    assert payload == {
        "name": "arm",
        "aim": "-x",
        "up": "z",
        "guides": [[0.0, 0.0, 0.0], [3.0, 1.0, 2.0], [6.0, 0.0, 0.0], [9.0, 0.0, 0.0]],
        "up_guide": [4.0, 5.0, 0.0],
    }


def test_gather_refuses_two_chains(new_scene):
    arm, leg = _arm(), _leg()
    with pytest.raises(ValueError, match="one chain"):
        guides.gather([arm, leg])


def test_gather_then_apply_rebuilds_the_guides(new_scene):
    group = _arm()
    before = [_pos(g) for g in core_guides.guides(group)["chain"]]
    payload = guides.gather([group])

    cmds.file(new=True, force=True)
    lines = []
    message = guides.apply(payload, info=lines.append)
    assert message == "Built guides for arm: 4 guides, aim -x, up z"
    assert lines == []
    rebuilt = core_guides.guides("arm_guides_grp")
    assert [_pos(g) for g in rebuilt["chain"]] == before
    assert _pos(rebuilt["up"]) == [4.0, 5.0, 0.0]
    # Run leaves the guides live: the joints still follow them.
    assert len(core_guides.joints("arm_guides_grp")) == 4
    assert cmds.getAttr("arm_01_jnt.tx", lock=True)


def test_apply_stops_before_changing_anything_if_the_guides_exist(new_scene):
    payload = guides.gather([_arm()])
    with pytest.raises(RuntimeError, match="Guides already in the scene: arm"):
        guides.apply(payload)
    assert cmds.ls("arm_guides_grp*") == ["arm_guides_grp"]


def test_apply_stops_if_other_nodes_use_its_names(new_scene):
    payload = guides.gather([_arm()])
    cmds.file(new=True, force=True)
    cmds.createNode("transform", name="arm_03_jnt")
    with pytest.raises(RuntimeError, match="arm_03_jnt"):
        guides.apply(payload)
    assert not cmds.objExists("arm_guides_grp")


def test_apply_stops_on_guides_that_cant_be_built(new_scene):
    payload = guides.gather([_leg()])
    cmds.file(new=True, force=True)
    payload["up_guide"] = [0, -20, 0]  # in line with the leg
    with pytest.raises(RuntimeError, match="leg: .*in line"):
        guides.apply(payload)
    assert cmds.ls(type="joint") == []


def test_apply_does_not_warn(new_scene):
    payload = guides.gather([_arm()])
    cmds.file(new=True, force=True)
    with runlog.capture() as run:
        guides.apply(payload)
    assert run.warnings == []


def test_selection_problems(new_scene):
    assert guides.selection_problems([]) == ["Nothing selected. Select guides, a guide group or a joint they drive."]
    stray = cmds.createNode("transform", name="stray")
    arm, leg = _arm(), _leg()
    assert guides.selection_problems(cmds.ls([arm, stray], long=True)) == [
        "stray isn't a guide, a guide group or a joint built from guides."
    ]
    assert guides.selection_problems([arm, core_guides.guides(leg)["up"]]) == [ONE_CHAIN]
    assert guides.selection_problems([arm, core_guides.joints(arm)[1]]) == []


def test_gather_raises_on_a_node_that_isnt_a_guide(new_scene):
    with pytest.raises(ValueError, match="isn't a guide"):
        guides.gather(cmds.ls(cmds.createNode("transform", name="stray"), long=True))


def test_describe_and_nodes(new_scene):
    payload = guides.gather([_arm()])
    assert guides.describe(payload) == ["arm: 4 guides, aim -x, up z"]
    assert guides.nodes(payload) == ["arm_guides_grp"]
    assert guides.gather(cmds.ls(guides.nodes(payload), long=True)) == payload


def test_fields_for_the_guide_tool_window():
    payload = {"name": "L_arm", "aim": "-x", "up": "z", "guides": [[0, 0, 0]] * 5, "up_guide": [0, 1, 0]}
    assert guides.fields(payload) == {"name": "L_arm", "count": 3, "aim": "-x", "up": "z"}


def test_mirrored_flips_the_chain_across_x_and_reverses_its_axes():
    payload = {"name": "L_arm", "aim": "x", "up": "-z", "guides": [[2, 10, 0], [7, 9, -1]], "up_guide": [5, 10, -5]}
    assert guides.mirrored(payload) == {
        "name": "R_arm", "aim": "-x", "up": "z", "guides": [[-2, 10, 0], [-7, 9, -1]], "up_guide": [-5, 10, -5],
    }
    assert guides.mirrored(guides.mirrored(payload)) == payload
    unsided = {"name": "tail", "aim": "-y", "up": "x", "guides": [[0, 5, -2], [0, 2, -8]], "up_guide": [3, 4, -5]}
    assert guides.mirrored(unsided)["name"] == "tail_mirrored"
    assert guides.mirrored(unsided)["up"] == "-x"
