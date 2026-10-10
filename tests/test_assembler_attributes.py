import os

import pytest
from maya import cmds

from kaiju_suite.core import attributes as core_attributes
from kaiju_suite.tools.assembler import data, logic, products, runlog, versions
from kaiju_suite.tools.assembler.products import attributes


def _ctrl(name="arm_ctrl", parent=None):
    """A control with custom attributes and its scale locked and hidden."""
    node = cmds.createNode("transform", name=name, parent=parent, skipSelect=True)
    cmds.addAttr(node, longName="ikFk", attributeType="double", min=0, max=1, defaultValue=1, keyable=True)
    cmds.addAttr(node, longName="space", attributeType="enum", enumName="world:local:parent", defaultValue=1)
    cmds.setAttr(f"{node}.space", channelBox=True)
    cmds.addAttr(node, longName="stretch", attributeType="bool", defaultValue=True, keyable=True)
    for axis in "XYZ":
        cmds.setAttr(f"{node}.scale{axis}", lock=True, keyable=False, channelBox=False)
    cmds.setAttr(f"{node}.visibility", keyable=False, channelBox=False)
    return node


def _state(node):
    return core_attributes.read_node(node)


def _publish(tmp_path, *selection, name="attrs"):
    path = attributes.PRODUCT.create(str(tmp_path), name)
    cmds.select(selection)
    message = versions.publish_action(path).fn()
    return path, message


# -- product ----------------------------------------------------------------


def test_attributes_is_discovered_and_owns_attr(tmp_path):
    assert attributes.PRODUCT in products.discover()
    assert attributes.PRODUCT.name == "Attributes"
    assert attributes.PRODUCT.kind == "attributes"
    assert attributes.PRODUCT.extensions == (".attr",)
    assert attributes.PRODUCT.runnable and attributes.PRODUCT.versioned
    path = attributes.PRODUCT.creators[0].fn(str(tmp_path), "attrs", None)
    assert path == str(tmp_path / "attrs.attr") and os.path.getsize(path) == 0
    assert products.product_for(path) is attributes.PRODUCT


# -- publish ----------------------------------------------------------------


def test_publish_saves_attributes_and_channels(new_scene, tmp_path):
    node = _ctrl()
    path, message = _publish(tmp_path, node)
    assert message == "Published Attributes attrs.attr v001"

    (record,) = data.read(path, "attributes")["nodes"]
    assert record["name"] == "arm_ctrl"
    assert [a["name"] for a in record["attributes"]] == ["ikFk", "space", "stretch"]
    assert record["channels"]["scaleX"] == {"locked": True, "keyable": False, "channel_box": False}
    assert record["channels"]["translateX"] == {"locked": False, "keyable": True, "channel_box": False}


# -- run --------------------------------------------------------------------


def test_round_trip_in_a_new_scene(new_scene, tmp_path):
    grp = cmds.createNode("transform", name="grp", skipSelect=True)
    arm = _ctrl("arm_ctrl", grp)
    leg = _ctrl("leg_ctrl")
    cmds.addAttr(leg, longName="label", dataType="string")
    cmds.setAttr(f"{leg}.label", lock=True)
    before = {n: _state(n) for n in ("arm_ctrl", "leg_ctrl")}
    path, _ = _publish(tmp_path, arm, leg)

    cmds.file(new=True, force=True)
    grp = cmds.createNode("transform", name="grp", skipSelect=True)
    cmds.createNode("transform", name="arm_ctrl", parent=grp, skipSelect=True)
    cmds.createNode("transform", name="leg_ctrl", skipSelect=True)
    assert logic.run_steps([path]) == [path]

    assert {n: _state(n) for n in ("arm_ctrl", "leg_ctrl")} == before
    assert cmds.getAttr("arm_ctrl.ikFk") == 1 and cmds.getAttr("arm_ctrl.space") == 1


def test_run_updates_existing_attributes_and_keeps_others(new_scene, tmp_path):
    node = _ctrl()
    path, _ = _publish(tmp_path, node)
    expected = _state(node)
    cmds.addAttr(f"{node}.ikFk", edit=True, maxValue=10)
    cmds.setAttr(f"{node}.ikFk", 0.3)
    cmds.setAttr(f"{node}.ikFk", lock=True)
    cmds.setAttr(f"{node}.scaleX", lock=False, keyable=True)
    cmds.addAttr(node, longName="extra", attributeType="double")

    message = attributes.PRODUCT.run(path)
    assert "arm_ctrl" in message
    state = _state(node)
    assert [a for a in state["attributes"] if a["name"] != "extra"] == expected["attributes"]
    assert state["channels"] == expected["channels"]
    assert cmds.getAttr(f"{node}.ikFk") == pytest.approx(0.3)  # values aren't touched
    assert cmds.attributeQuery("extra", node=node, exists=True)


def test_missing_node_is_skipped_with_a_warning(new_scene, tmp_path):
    arm = _ctrl("arm_ctrl")
    leg = _ctrl("leg_ctrl")
    path, _ = _publish(tmp_path, arm, leg)

    cmds.file(new=True, force=True)
    cmds.createNode("transform", name="arm_ctrl", skipSelect=True)
    with runlog.capture() as run:
        attributes.PRODUCT.run(path)
    assert run.warnings == ["Skipped missing nodes: leg_ctrl"]
    assert cmds.attributeQuery("ikFk", node="arm_ctrl", exists=True)


def test_ambiguous_name_raises_and_changes_nothing(new_scene, tmp_path):
    arm = _ctrl("arm_ctrl")
    leg = _ctrl("leg_ctrl")
    path, _ = _publish(tmp_path, arm, leg)

    cmds.file(new=True, force=True)
    cmds.createNode("transform", name="arm_ctrl", skipSelect=True)
    for parent in ("a", "b"):
        cmds.createNode("transform", name="leg_ctrl", parent=cmds.createNode("transform", name=parent))
    with pytest.raises(RuntimeError) as info:
        attributes.PRODUCT.run(path)
    assert "leg_ctrl" in str(info.value)
    assert not cmds.attributeQuery("ikFk", node="arm_ctrl", exists=True)
    assert not cmds.getAttr("arm_ctrl.scaleX", lock=True)


def test_type_clash_raises_and_changes_nothing(new_scene, tmp_path):
    arm = _ctrl("arm_ctrl")
    leg = _ctrl("leg_ctrl")
    path, _ = _publish(tmp_path, arm, leg)

    cmds.file(new=True, force=True)
    cmds.createNode("transform", name="arm_ctrl", skipSelect=True)
    leg = cmds.createNode("transform", name="leg_ctrl", skipSelect=True)
    cmds.addAttr(leg, longName="space", attributeType="double")
    with pytest.raises(RuntimeError) as info:
        attributes.PRODUCT.run(path)
    assert "leg_ctrl.space" in str(info.value)
    assert not cmds.attributeQuery("ikFk", node="arm_ctrl", exists=True)


def test_empty_file_is_skipped(new_scene, tmp_path):
    path = attributes.PRODUCT.create(str(tmp_path), "attrs")
    assert logic.run_steps([path]) == [path]


def test_one_undo_reverts_a_run(new_scene, tmp_path):
    node = _ctrl()
    path, _ = _publish(tmp_path, node)
    cmds.file(new=True, force=True)
    node = cmds.createNode("transform", name="arm_ctrl", skipSelect=True)
    cmds.addAttr(node, longName="ikFk", attributeType="double", defaultValue=0)
    before = _state(node)
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    attributes.PRODUCT.run(path)
    assert _state(node) != before
    cmds.undo()
    assert _state(node) == before


# -- publish checks and versions --------------------------------------------


def test_publish_problems(new_scene, tmp_path):
    path = attributes.PRODUCT.create(str(tmp_path), "attrs")
    cmds.select(clear=True)
    (problem,) = versions.publish_problems(path)
    assert "Nothing selected" in problem
    cmds.select(_ctrl())
    assert versions.publish_problems(path) == []


def test_republishing_adds_a_version_only_on_change(new_scene, tmp_path):
    node = _ctrl()
    path, message = _publish(tmp_path, node)
    assert message.endswith("v001")
    cmds.select(node)
    assert versions.publish_action(path).fn().endswith("v001")
    cmds.setAttr(f"{node}.translateY", lock=True)
    assert versions.publish_action(path).fn().endswith("v002")


def test_panel_describes_the_nodes(new_scene, tmp_path):
    path, _ = _publish(tmp_path, _ctrl("arm_ctrl"), _ctrl("leg_ctrl"))
    assert attributes.PRODUCT.panel(path).info == [
        "2 nodes, 6 custom attributes",
        "Nodes: arm_ctrl, leg_ctrl",
    ]
