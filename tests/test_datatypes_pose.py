"""Pose save/load (kaiju_suite.datatypes.pose) and its QC checks."""

import json

import pytest
from maya import cmds

from kaiju_suite import datatypes
from kaiju_suite.core import checks
from kaiju_suite.datatypes import pose


def _ctrl(name="ctrl", parent=None):
    node = cmds.createNode("transform", name=name, parent=parent, skipSelect=True)
    cmds.addAttr(node, longName="weight", attributeType="double", keyable=True)
    cmds.setAttr(f"{node}.translate", 1, 2, 3)
    cmds.setAttr(f"{node}.weight", 0.25)
    return cmds.ls(node, long=True)[0]


def _bare(name="bare"):
    """A transform with no keyable, unlocked attributes."""
    node = cmds.createNode("transform", name=name, skipSelect=True)
    cmds.setAttr(f"{node}.visibility", keyable=False)
    for attr in ("translate", "rotate", "scale"):
        for axis in "XYZ":
            cmds.setAttr(f"{node}.{attr}{axis}", lock=True)
    return cmds.ls(node, long=True)[0]


def _long(*nodes):
    return cmds.ls(nodes, long=True)


def test_kind_and_extension():
    assert pose.KIND == "pose"
    assert pose.EXTENSION == ".pose"


def test_gather_then_apply_sets_the_values_back(new_scene):
    node = _ctrl()
    payload = pose.gather([node])
    assert [r["name"] for r in payload["nodes"]] == ["ctrl"]
    assert payload["nodes"][0]["attrs"]["weight"] == 0.25

    cmds.setAttr(f"{node}.translate", 0, 0, 0)
    cmds.setAttr(f"{node}.weight", 0)
    lines = []
    message = pose.apply(payload, info=lines.append)

    assert message == f"Set {len(payload['nodes'][0]['attrs'])} attributes on 1 node"
    assert lines == [f"ctrl: set {len(payload['nodes'][0]['attrs'])} attributes"]
    assert cmds.getAttr(f"{node}.translate")[0] == pytest.approx((1, 2, 3))
    assert cmds.getAttr(f"{node}.weight") == pytest.approx(0.25)


def test_gather_skips_nodes_with_nothing_to_save_and_raises_when_none_have(new_scene):
    node, bare = _ctrl(), _bare()
    assert [r["name"] for r in pose.gather([node, bare])["nodes"]] == ["ctrl"]
    with pytest.raises(RuntimeError, match="no keyable attributes"):
        pose.gather([bare])


def test_files_written_before_the_move_still_load(new_scene, tmp_path):
    node = _ctrl()
    old = tmp_path / "rest.pose"
    old.write_text(
        json.dumps({"kaiju": "pose", "format": 1, "data": {"nodes": [{"name": "ctrl", "attrs": {"translateX": 7.0}}]}}),
        encoding="utf-8",
    )
    datatypes.load(pose, str(old))
    assert cmds.getAttr(f"{node}.translateX") == 7


def test_selection_problems(new_scene):
    assert pose.selection_problems([]) == ["Nothing selected. Select the nodes whose pose to publish."]
    assert pose.selection_problems([_bare()]) == ["The selected nodes have no keyable attributes to save."]
    assert pose.selection_problems([_ctrl()]) == []


def test_describe_nodes_and_compare_view(new_scene):
    payload = pose.gather([_ctrl(), _ctrl("other")])
    count = sum(len(r["attrs"]) for r in payload["nodes"])
    assert pose.describe(payload) == ["2 nodes", f"{count} attributes", "Nodes: ctrl, other"]
    assert pose.nodes(payload) == ["ctrl", "other"]
    assert pose.compare_view(payload) == payload


# -- QC checks --------------------------------------------------------------


def _run(key, nodes):
    return checks.get(key, pose.CHECKS).run(nodes=nodes)


def test_the_pose_checks():
    assert [c.key for c in pose.CHECKS] == ["driven", "nothing_to_save", "duplicate_names"]
    assert [c.label for c in pose.CHECKS] == ["Driven attributes", "Nothing to save", "Duplicate names"]
    assert all(c.publish for c in pose.CHECKS)


def test_a_clean_control_has_no_problems(new_scene):
    node = _ctrl()
    cmds.setKeyframe(node, attribute="translateX", time=1, value=0)  # time keys don't drive it
    assert datatypes.qc_failed(datatypes.run_qc(pose, [node])) == []


def test_driven_attributes_are_found(new_scene):
    node = _ctrl()
    driver = cmds.createNode("transform", name="driver", skipSelect=True)
    cmds.connectAttr(f"{driver}.rotateY", f"{node}.rotateY")
    cmds.setDrivenKeyframe(f"{node}.weight", currentDriver=f"{driver}.translateX")

    (problem,) = _run("driven", [node])

    assert problem == "ctrl: 2 driven attributes (Run will skip them): rotateY, weight"
    assert checks.selection_of(problem) == ["ctrl"]


def test_nodes_with_nothing_to_save_are_found(new_scene):
    node, bare = _ctrl(), _bare()
    assert _run("nothing_to_save", [node, bare]) == ["bare: no keyable, unlocked attributes"]


def test_duplicate_names_are_found(new_scene):
    a = _ctrl("ctrl", cmds.createNode("transform", name="a"))
    _ctrl("ctrl", cmds.createNode("transform", name="b"))
    solo = _ctrl("solo")

    (problem,) = _run("duplicate_names", [a, solo])

    assert problem == "a|ctrl: 2 nodes are called ctrl"
    assert checks.selection_of(problem) == ["a|ctrl", "b|ctrl"]


def test_checks_change_nothing(new_scene):
    node = _ctrl()
    before = cmds.getAttr(f"{node}.translate")[0]
    datatypes.run_qc(pose, [node])
    assert cmds.getAttr(f"{node}.translate")[0] == before
