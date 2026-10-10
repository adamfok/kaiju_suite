import pytest
from maya import cmds

from kaiju_suite.core import attributes


def _node(name="ctrl"):
    return cmds.createNode("transform", name=name, skipSelect=True)


# -- reading ----------------------------------------------------------------


def test_custom_attributes_lists_user_defined_scalars_in_order(new_scene):
    node = _node()
    cmds.addAttr(node, longName="ikFk", attributeType="double", keyable=True)
    cmds.addAttr(node, longName="space", attributeType="enum", enumName="world:local")
    cmds.addAttr(node, longName="offset", attributeType="double3")
    for axis in "XYZ":
        cmds.addAttr(node, longName=f"offset{axis}", attributeType="double", parent="offset")
    assert attributes.custom_attributes(node) == ["ikFk", "space"]


def test_read_attribute_numeric(new_scene):
    node = _node()
    cmds.addAttr(node, longName="ikFk", attributeType="double", min=0, max=1, defaultValue=0.5, keyable=True)
    assert attributes.read_attribute(node, "ikFk") == {
        "name": "ikFk",
        "type": "double",
        "min": 0.0,
        "max": 1.0,
        "default": 0.5,
        "keyable": True,
        "channel_box": False,
        "locked": False,
    }


def test_read_attribute_without_limits_has_none(new_scene):
    node = _node()
    cmds.addAttr(node, longName="count", attributeType="long", defaultValue=3)
    cmds.setAttr(f"{node}.count", channelBox=True)
    record = attributes.read_attribute(node, "count")
    assert record["min"] is None and record["max"] is None
    assert record["default"] == 3 and record["type"] == "long"
    assert record["keyable"] is False and record["channel_box"] is True


def test_read_attribute_enum_bool_string(new_scene):
    node = _node()
    cmds.addAttr(node, longName="space", attributeType="enum", enumName="world=0:local=5", defaultValue=5)
    cmds.addAttr(node, longName="show", attributeType="bool", defaultValue=True, keyable=True)
    cmds.addAttr(node, longName="label", dataType="string")
    cmds.setAttr(f"{node}.label", lock=True)
    space = attributes.read_attribute(node, "space")
    assert space["type"] == "enum" and space["enum"] == "world:local=5"  # Maya drops "=0" on the first name and space["default"] == 5
    show = attributes.read_attribute(node, "show")
    assert show["type"] == "bool" and show["default"] is True
    label = attributes.read_attribute(node, "label")
    assert label["type"] == "string" and label["locked"] is True and "default" not in label


def test_read_channels(new_scene):
    node = _node()
    cmds.setAttr(f"{node}.translateX", lock=True)
    cmds.setAttr(f"{node}.scaleY", keyable=False, channelBox=False)
    cmds.setAttr(f"{node}.visibility", keyable=False, channelBox=True)
    channels = attributes.read_channels(node)
    assert list(channels) == list(attributes.STANDARD_CHANNELS)
    assert channels["translateX"] == {"locked": True, "keyable": True, "channel_box": False}
    assert channels["scaleY"] == {"locked": False, "keyable": False, "channel_box": False}
    assert channels["visibility"] == {"locked": False, "keyable": False, "channel_box": True}


def test_read_channels_of_a_node_without_them(new_scene):
    node = cmds.createNode("network", skipSelect=True)
    assert attributes.read_channels(node) == {}


# -- writing ----------------------------------------------------------------


def test_apply_round_trip_onto_a_new_node(new_scene):
    node = _node()
    cmds.addAttr(node, longName="ikFk", attributeType="double", min=0, max=1, defaultValue=0.5, keyable=True)
    cmds.addAttr(node, longName="twist", attributeType="doubleAngle", min=-90, max=90, defaultValue=45, keyable=True)
    cmds.addAttr(node, longName="len", attributeType="doubleLinear", defaultValue=2.5)
    cmds.setAttr(f"{node}.len", channelBox=True)
    cmds.addAttr(node, longName="space", attributeType="enum", enumName="world:local:parent", defaultValue=2)
    cmds.addAttr(node, longName="show", attributeType="bool", keyable=True)
    cmds.addAttr(node, longName="label", dataType="string")
    cmds.setAttr(f"{node}.ikFk", lock=True)
    cmds.setAttr(f"{node}.rotateZ", lock=True, keyable=False)
    saved = attributes.read_node(node)

    other = _node("other")
    for record in saved["attributes"]:
        assert attributes.attribute_problems(other, record) == []
        assert attributes.apply_attribute(other, record) == "added"
    attributes.apply_channels(other, saved["channels"])
    assert attributes.read_node(other) == saved
    assert cmds.getAttr(f"{other}.ikFk") == 0.5
    assert cmds.getAttr(f"{other}.twist") == pytest.approx(cmds.getAttr(f"{node}.twist"))
    assert cmds.getAttr(f"{other}.space") == 2


def test_apply_updates_an_existing_attribute(new_scene):
    node = _node()
    cmds.addAttr(node, longName="ikFk", attributeType="double", min=0, max=1, defaultValue=1, keyable=True)
    record = attributes.read_attribute(node, "ikFk")
    cmds.deleteAttr(f"{node}.ikFk")
    cmds.addAttr(node, longName="ikFk", attributeType="double", min=-5, defaultValue=0)
    cmds.setAttr(f"{node}.ikFk", 0.25)
    cmds.setAttr(f"{node}.ikFk", lock=True)

    assert attributes.apply_attribute(node, record) == "updated"
    assert attributes.read_attribute(node, "ikFk") == record
    assert cmds.getAttr(f"{node}.ikFk") == 0.25  # the value is left alone


def test_apply_removes_limits_not_in_the_record(new_scene):
    node = _node()
    cmds.addAttr(node, longName="amount", attributeType="double", keyable=True)
    record = attributes.read_attribute(node, "amount")
    cmds.addAttr(f"{node}.amount", edit=True, hasMinValue=True, minValue=-1, hasMaxValue=True, maxValue=1)
    attributes.apply_attribute(node, record)
    assert attributes.read_attribute(node, "amount") == record


def test_apply_updates_enum_names(new_scene):
    node = _node()
    cmds.addAttr(node, longName="space", attributeType="enum", enumName="a:b")
    record = dict(attributes.read_attribute(node, "space"), enum="world:local:parent")
    attributes.apply_attribute(node, record)
    assert attributes.read_attribute(node, "space")["enum"] == "world:local:parent"


def test_problems_for_a_different_type_or_a_builtin_name(new_scene):
    node = _node()
    cmds.addAttr(node, longName="space", attributeType="double")
    (problem,) = attributes.attribute_problems(node, {"name": "space", "type": "enum", "enum": "a:b"})
    assert "space" in problem and "double" in problem and "enum" in problem
    (problem,) = attributes.attribute_problems(node, {"name": "translateX", "type": "double"})
    assert "translateX" in problem
    (problem,) = attributes.attribute_problems(node, {"name": "thing", "type": "message"})
    assert "message" in problem


def test_apply_channels_lock_and_hide(new_scene):
    node = _node()
    attributes.apply_channels(node, {
        "scaleX": {"locked": True, "keyable": False, "channel_box": False},
        "visibility": {"locked": False, "keyable": False, "channel_box": True},
    })
    assert cmds.getAttr(f"{node}.scaleX", lock=True)
    assert not cmds.getAttr(f"{node}.scaleX", keyable=True)
    assert not cmds.getAttr(f"{node}.scaleX", channelBox=True)
    assert cmds.getAttr(f"{node}.visibility", channelBox=True)
    assert cmds.getAttr(f"{node}.translateX", keyable=True)  # not in the dict: left alone


def test_apply_channels_skips_channels_the_node_lacks(new_scene):
    node = cmds.createNode("network", skipSelect=True)
    attributes.apply_channels(node, {"scaleX": {"locked": True, "keyable": False, "channel_box": False}})
