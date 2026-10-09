import os

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import data, logic, products, runlog, versions
from kaiju_suite.tools.assembler.products import pose


def _ctrl(name="ctrl", parent=None):
    """A transform with a user-defined float, bool and enum, all off their defaults."""
    node = cmds.createNode("transform", name=name, parent=parent, skipSelect=True)
    cmds.addAttr(node, longName="weight", attributeType="double", keyable=True)
    cmds.addAttr(node, longName="ikFk", attributeType="bool", keyable=True)
    cmds.addAttr(node, longName="space", attributeType="enum", enumName="world:local:hand", keyable=True)
    cmds.addAttr(node, longName="note", dataType="string")
    cmds.setAttr(f"{node}.translate", 1, 2, 3)
    cmds.setAttr(f"{node}.rotate", 10, 20, 30)
    cmds.setAttr(f"{node}.weight", 0.25)
    cmds.setAttr(f"{node}.ikFk", True)
    cmds.setAttr(f"{node}.space", 2)
    return cmds.ls(node, long=True)[0]


def _zero(node):
    cmds.setAttr(f"{node}.translate", 0, 0, 0)
    cmds.setAttr(f"{node}.rotate", 0, 0, 0)
    cmds.setAttr(f"{node}.weight", 0)
    cmds.setAttr(f"{node}.ikFk", False)
    cmds.setAttr(f"{node}.space", 0)


def _publish(tmp_path, *selection, name="rest"):
    path = pose.PRODUCT.create(str(tmp_path), name)
    cmds.select(selection)
    message = versions.publish_action(path).fn()
    return path, message


def _saved(path):
    return {n["name"]: n["attrs"] for n in data.read(path, "pose")["nodes"]}


# -- product ----------------------------------------------------------------


def test_pose_is_discovered_and_owns_pose(tmp_path):
    assert pose.PRODUCT in products.discover()
    assert pose.PRODUCT.name == "Pose"
    assert pose.PRODUCT.extensions == (".pose",)
    assert pose.PRODUCT.order == 100
    assert pose.PRODUCT.runnable and pose.PRODUCT.versioned
    path = pose.PRODUCT.creators[0].fn(str(tmp_path), "rest", None)
    assert path == str(tmp_path / "rest.pose") and os.path.getsize(path) == 0
    assert products.product_for(path) is pose.PRODUCT


# -- publish ----------------------------------------------------------------


def test_publish_saves_keyable_unlocked_scalar_attributes(new_scene, tmp_path):
    node = _ctrl()
    cmds.setAttr(f"{node}.translateZ", lock=True)
    cmds.setAttr(f"{node}.scaleX", keyable=False, channelBox=True)
    path, message = _publish(tmp_path, node)
    assert message == "Published Pose rest.pose v001"

    attrs = _saved(path)["ctrl"]
    assert attrs["translateX"] == 1.0 and attrs["rotateY"] == 20.0
    assert attrs["weight"] == 0.25
    assert attrs["ikFk"] is True
    assert attrs["space"] == 2 and type(attrs["space"]) is int
    assert attrs["visibility"] is True
    for left_out in ("translateZ", "scaleX", "translate", "note", "message"):
        assert left_out not in attrs


def test_publish_stores_shortest_unique_names(new_scene, tmp_path):
    a = _ctrl("ctrl", cmds.createNode("transform", name="a"))
    b = _ctrl("ctrl", cmds.createNode("transform", name="b"))
    solo = _ctrl("solo", cmds.createNode("transform", name="grp"))
    path, _ = _publish(tmp_path, a, b, solo)
    assert list(_saved(path)) == ["a|ctrl", "b|ctrl", "solo"]


def test_publish_skips_multi_and_compound_parents(new_scene, tmp_path):
    node = _ctrl()
    cmds.addAttr(node, longName="extra", attributeType="double", multi=True, keyable=True)
    cmds.setAttr(f"{node}.extra[0]", 4)
    cube = cmds.polyCube(name="box")[0]
    shape = cmds.listRelatives(cube, shapes=True, fullPath=True)[0]
    path, _ = _publish(tmp_path, node, shape)
    saved = _saved(path)
    assert "extra" not in saved["ctrl"]
    assert all("." not in attr for attrs in saved.values() for attr in attrs)


def test_publish_saves_animated_values_at_the_current_frame(new_scene, tmp_path):
    node = _ctrl()
    cmds.setKeyframe(node, attribute="translateX", time=1, value=0)
    cmds.setKeyframe(node, attribute="translateX", time=11, value=10)
    cmds.currentTime(6)
    path, _ = _publish(tmp_path, node)
    assert _saved(path)["ctrl"]["translateX"] == pytest.approx(5.0)


# -- run --------------------------------------------------------------------


def test_round_trip_sets_values_and_creates_no_keys(new_scene, tmp_path):
    node = _ctrl()
    path, _ = _publish(tmp_path, node)
    _zero(node)

    message = pose.PRODUCT.run(path)
    assert "Skipped" not in message
    assert cmds.getAttr(f"{node}.translate")[0] == pytest.approx((1, 2, 3))
    assert cmds.getAttr(f"{node}.rotate")[0] == pytest.approx((10, 20, 30))
    assert cmds.getAttr(f"{node}.weight") == pytest.approx(0.25)
    assert cmds.getAttr(f"{node}.ikFk") is True
    assert cmds.getAttr(f"{node}.space") == 2
    assert not cmds.keyframe(node, query=True, keyframeCount=True)
    assert not cmds.ls(type="animCurve")


def test_round_trip_into_a_new_scene(new_scene, tmp_path):
    path, _ = _publish(tmp_path, _ctrl())
    cmds.file(new=True, force=True)
    node = _ctrl()
    _zero(node)
    logic.run_steps([path])
    assert cmds.getAttr(f"{node}.translateY") == pytest.approx(2)
    assert cmds.getAttr(f"{node}.space") == 2


def test_run_changes_keyed_values_and_leaves_keys_alone(new_scene, tmp_path):
    node = _ctrl()
    path, _ = _publish(tmp_path, node)
    cmds.setKeyframe(node, attribute="translateX", time=1, value=7)
    cmds.setKeyframe(node, attribute="translateX", time=10, value=8)
    cmds.currentTime(1)

    message = pose.PRODUCT.run(path)
    assert "Skipped" not in message
    assert cmds.getAttr(f"{node}.translateX") == pytest.approx(1)
    assert cmds.keyframe(f"{node}.translateX", query=True, valueChange=True) == pytest.approx([7, 8])
    assert cmds.keyframe(node, query=True, keyframeCount=True) == 2


def test_locked_connected_and_missing_attributes_are_skipped_and_reported(new_scene, tmp_path):
    node = _ctrl()
    path, _ = _publish(tmp_path, node)
    _zero(node)
    cmds.setAttr(f"{node}.translateX", lock=True)
    driver = cmds.createNode("transform", name="driver")
    cmds.connectAttr(f"{driver}.rotateY", f"{node}.rotateY")
    cmds.deleteAttr(f"{node}.weight")

    with runlog.capture() as run:
        message = pose.PRODUCT.run(path)
    skipped = "Skipped 3 attributes: ctrl.translateX (locked), ctrl.rotateY (connected), ctrl.weight (missing)"
    assert skipped in message
    assert run.warnings == [skipped]
    assert cmds.getAttr(f"{node}.translateX") == 0
    assert cmds.getAttr(f"{node}.translateY") == pytest.approx(2)
    assert cmds.getAttr(f"{node}.rotateX") == pytest.approx(10)


def test_missing_node_is_skipped_with_a_warning(new_scene, tmp_path):
    node = _ctrl()
    other = _ctrl("other")
    path, _ = _publish(tmp_path, node, other)
    cmds.delete(other)
    _zero(node)

    with runlog.capture() as run:
        message = pose.PRODUCT.run(path)
    assert run.warnings == ["Skipped missing nodes: other"]
    assert message.startswith("Set 13 attributes on 1 node")
    assert cmds.getAttr(f"{node}.translate")[0] == pytest.approx((1, 2, 3))


def test_all_nodes_missing_is_a_warning_not_an_error(new_scene, tmp_path):
    path, _ = _publish(tmp_path, _ctrl())
    cmds.file(new=True, force=True)
    with runlog.capture() as run:
        pose.PRODUCT.run(path)
    assert run.warnings == ["Skipped missing nodes: ctrl"]


def test_ambiguous_name_raises_and_changes_nothing(new_scene, tmp_path):
    node = _ctrl()
    path, _ = _publish(tmp_path, node)
    _zero(node)
    _ctrl("ctrl", cmds.createNode("transform", name="grp"))

    with pytest.raises(RuntimeError) as info:
        pose.PRODUCT.run(path)
    assert "ctrl" in str(info.value)
    assert cmds.getAttr(f"{node}.translate")[0] == (0, 0, 0)


def test_empty_file_is_skipped(new_scene, tmp_path):
    node = _ctrl()
    path = pose.PRODUCT.create(str(tmp_path), "rest")
    assert logic.run_steps([path]) == [path]
    assert cmds.getAttr(f"{node}.translateX") == 1


def test_one_undo_reverts_a_run(new_scene, tmp_path):
    node = _ctrl()
    path, _ = _publish(tmp_path, node)
    _zero(node)
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    pose.PRODUCT.run(path)
    assert cmds.getAttr(f"{node}.translateX") == 1
    cmds.undo()
    assert cmds.getAttr(f"{node}.translate")[0] == (0, 0, 0)
    assert cmds.getAttr(f"{node}.space") == 0
    assert cmds.getAttr(f"{node}.ikFk") is False


# -- publish checks and versions --------------------------------------------


def test_publish_problems(new_scene, tmp_path):
    path = pose.PRODUCT.create(str(tmp_path), "rest")
    cmds.select(clear=True)
    (problem,) = versions.publish_problems(path)
    assert "Nothing selected" in problem

    bare = cmds.createNode("transform", name="bare", skipSelect=True)
    cmds.setAttr(f"{bare}.visibility", keyable=False)
    for attr in ("translate", "rotate", "scale"):
        for axis in "XYZ":
            cmds.setAttr(f"{bare}.{attr}{axis}", lock=True)
    cmds.select(bare)
    (problem,) = versions.publish_problems(path)
    assert "keyable" in problem.lower()

    cmds.select(_ctrl())
    assert versions.publish_problems(path) == []


def test_republishing_adds_a_version_only_on_change(new_scene, tmp_path):
    node = _ctrl()
    path, message = _publish(tmp_path, node)
    assert message.endswith("v001")

    cmds.select(node)
    assert versions.publish_action(path).fn().endswith("v001")
    assert [v.number for v in versions.list_versions(path)] == [1]

    cmds.setAttr(f"{node}.weight", 0.75)
    assert versions.publish_action(path).fn().endswith("v002")


def test_panel_describes_the_pose(new_scene, tmp_path):
    path, _ = _publish(tmp_path, _ctrl(), _ctrl("other"))
    count = len(_saved(path)["ctrl"]) * 2
    assert pose.PRODUCT.panel(path).info == ["2 nodes", f"{count} attributes", "Nodes: ctrl, other"]
