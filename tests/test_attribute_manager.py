import pytest
from maya import cmds

from kaiju_suite import registry
from kaiju_suite.tools.attribute_manager import logic


def _node(name="ctrl"):
    return cmds.ls(cmds.createNode("transform", name=name), long=True)[0]


def _nodes(*names):
    return [_node(name) for name in names]


def _add(nodes, name, kind="float", **kwargs):
    return logic.add_attribute(nodes, name, kind, **kwargs)


# -- tool -------------------------------------------------------------------


def test_tool_is_registered_under_rigging():
    tool = registry.find("Attribute Manager")

    assert tool is not None
    assert tool["category"] == "Rigging"
    assert callable(tool["launch"])


# -- adding -----------------------------------------------------------------


def test_add_float_with_range_default_and_keyable_on_every_node(new_scene):
    nodes = _nodes("a", "b")

    result = _add(nodes, "twist", "float", minimum=-10, maximum=10, default=2.5, keyable=True)

    assert result.changed == nodes
    for node in nodes:
        plug = f"{node}.twist"
        assert cmds.getAttr(plug, type=True) == "double"
        assert cmds.getAttr(plug) == pytest.approx(2.5)
        assert cmds.attributeQuery("twist", node=node, minimum=True) == [-10]
        assert cmds.attributeQuery("twist", node=node, maximum=True) == [10]
        assert cmds.getAttr(plug, keyable=True)


@pytest.mark.parametrize(
    "kind, maya_type, default",
    [("int", "long", 3), ("bool", "bool", True), ("string", "string", "hello")],
)
def test_add_other_kinds(new_scene, kind, maya_type, default):
    node = _node()

    _add([node], "thing", kind, default=default)

    assert cmds.getAttr(f"{node}.thing", type=True) == maya_type
    assert cmds.getAttr(f"{node}.thing") == default


def test_add_enum_with_names(new_scene):
    node = _node()

    _add([node], "space", "enum", enum_names=["world", "root", "chest"], default=1)

    assert cmds.attributeQuery("space", node=node, listEnum=True) == ["world:root:chest"]
    assert cmds.getAttr(f"{node}.space") == 1


def test_add_non_keyable_still_shows_in_channel_box(new_scene):
    node = _node()

    _add([node], "settings", "int", keyable=False)

    assert not cmds.getAttr(f"{node}.settings", keyable=True)
    assert cmds.getAttr(f"{node}.settings", channelBox=True)


def test_add_skips_nodes_that_already_have_the_attribute(new_scene):
    a, b = _nodes("a", "b")
    _add([a], "twist")

    result = _add([a, b], "twist")

    assert result.changed == [b]
    assert len(result.skipped) == 1 and "a" in result.skipped[0]


@pytest.mark.parametrize("name", ["", "1abc", "has space", "bad-name"])
def test_add_rejects_invalid_names(new_scene, name):
    with pytest.raises(ValueError):
        _add([_node()], name)


def test_add_rejects_unknown_kind_and_bad_range(new_scene):
    node = _node()
    with pytest.raises(ValueError):
        _add([node], "x", "vector")
    with pytest.raises(ValueError):
        _add([node], "x", "float", minimum=5, maximum=1)
    with pytest.raises(ValueError):
        _add([node], "x", "enum", enum_names=[])


def test_add_is_one_undo_step(new_scene):
    nodes = _nodes("a", "b")

    _add(nodes, "twist")
    cmds.undo()

    assert not any(cmds.attributeQuery("twist", node=n, exists=True) for n in nodes)


# -- listing ----------------------------------------------------------------


def test_custom_attributes_in_channel_box_order(new_scene):
    node = _node()
    for name in ("gamma", "alpha", "beta"):
        _add([node], name)

    assert logic.custom_attributes(node) == ["gamma", "alpha", "beta"]


def test_custom_attributes_list_compounds_once(new_scene):
    node = _node()
    cmds.addAttr(node, longName="offset", attributeType="double3")
    for axis in "XYZ":
        cmds.addAttr(node, longName=f"offset{axis}", attributeType="double", parent="offset")

    assert logic.custom_attributes(node) == ["offset"]


# -- separators -------------------------------------------------------------


def test_separator_is_a_locked_enum_shown_in_the_channel_box(new_scene):
    nodes = _nodes("a", "b")

    result = logic.add_separator(nodes, "IK")

    assert result.changed == nodes
    for node in nodes:
        attr = logic.custom_attributes(node)[-1]
        plug = f"{node}.{attr}"
        assert cmds.getAttr(plug, type=True) == "enum"
        assert cmds.getAttr(plug, lock=True)
        assert cmds.getAttr(plug, channelBox=True)
        assert not cmds.getAttr(plug, keyable=True)
        assert cmds.attributeQuery(attr, node=node, niceName=True) == "IK"
        assert cmds.attributeQuery(attr, node=node, listEnum=True)[0].startswith("___")
        assert logic.is_separator(node, attr)


def test_several_separators_get_unique_names(new_scene):
    node = _node()

    logic.add_separator([node], "IK")
    logic.add_separator([node], "IK")
    logic.add_separator([node], "")

    attrs = logic.custom_attributes(node)
    assert len(attrs) == len(set(attrs)) == 3
    assert all(logic.is_separator(node, a) for a in attrs)


def test_a_normal_attribute_is_not_a_separator(new_scene):
    node = _node()
    _add([node], "space", "enum", enum_names=["a", "b"])

    assert not logic.is_separator(node, "space")


def test_separator_is_one_undo_step(new_scene):
    node = _node()

    logic.add_separator([node], "IK")
    cmds.undo()

    assert logic.custom_attributes(node) == []


# -- renaming ---------------------------------------------------------------


def test_rename_on_every_node_keeps_value_and_connections(new_scene):
    a, b, driven = _nodes("a", "b", "driven")
    _add([a, b], "twist", default=4)
    cmds.connectAttr(f"{a}.twist", f"{driven}.translateX")

    result = logic.rename_attribute([a, b], "twist", "roll")

    assert result.changed == [a, b]
    assert logic.custom_attributes(a) == ["roll"]
    assert cmds.getAttr(f"{b}.roll") == 4
    assert cmds.isConnected(f"{a}.roll", f"{driven}.translateX")


def test_rename_skips_missing_and_taken_names(new_scene):
    a, b, c = _nodes("a", "b", "c")
    _add([a, b], "twist")
    _add([b], "roll")

    result = logic.rename_attribute([a, b, c], "twist", "roll")

    assert result.changed == [a]
    assert len(result.skipped) == 2


def test_rename_rejects_invalid_name_and_undoes_in_one_step(new_scene):
    a, b = _nodes("a", "b")
    _add([a, b], "twist")
    with pytest.raises(ValueError):
        logic.rename_attribute([a], "twist", "bad name")

    logic.rename_attribute([a, b], "twist", "roll")
    cmds.undo()

    assert logic.custom_attributes(a) == logic.custom_attributes(b) == ["twist"]


# -- reordering -------------------------------------------------------------


def _rig(node):
    """Four custom attrs on ``node`` with values, flags and connections."""
    driver, driven = _nodes("driver", "driven")
    _add([node], "first", "float", minimum=0, maximum=10, default=1)
    _add([node], "second", "int", default=2)
    _add([node], "third", "enum", enum_names=["off", "on", "auto"], default=0)
    _add([node], "label", "string", default="hi")
    cmds.setAttr(f"{node}.first", 7.5)
    cmds.setAttr(f"{node}.third", 2)
    cmds.setAttr(f"{node}.third", keyable=False, channelBox=True)
    cmds.connectAttr(f"{driver}.translateY", f"{node}.second", force=True)
    cmds.setAttr(f"{node}.second", lock=True)
    cmds.connectAttr(f"{node}.first", f"{driven}.translateX")
    cmds.connectAttr(f"{node}.third", f"{driven}.visibility")
    return driver, driven


def _check_rig(node, driver, driven):
    assert cmds.getAttr(f"{node}.first") == pytest.approx(7.5)
    assert cmds.attributeQuery("first", node=node, minimum=True) == [0]
    assert cmds.attributeQuery("first", node=node, maximum=True) == [10]
    assert cmds.attributeQuery("first", node=node, listDefault=True) == [1]
    assert cmds.attributeQuery("third", node=node, listEnum=True) == ["off:on:auto"]
    assert cmds.getAttr(f"{node}.third") == 2
    assert not cmds.getAttr(f"{node}.third", keyable=True)
    assert cmds.getAttr(f"{node}.third", channelBox=True)
    assert cmds.getAttr(f"{node}.label") == "hi"
    assert cmds.getAttr(f"{node}.second", lock=True)
    assert cmds.isConnected(f"{driver}.translateY", f"{node}.second")
    assert cmds.isConnected(f"{node}.first", f"{driven}.translateX")
    assert cmds.isConnected(f"{node}.third", f"{driven}.visibility")


def test_move_up_and_down_preserve_values_flags_and_connections(new_scene):
    node = _node()
    driver, driven = _rig(node)

    logic.move_attributes([node], ["first"], 1)
    assert logic.custom_attributes(node) == ["second", "first", "third", "label"]
    _check_rig(node, driver, driven)

    logic.move_attributes([node], ["label"], -1)
    assert logic.custom_attributes(node) == ["second", "first", "label", "third"]
    _check_rig(node, driver, driven)

    cmds.setAttr(f"{driver}.translateY", 5)
    assert cmds.getAttr(f"{node}.second") == 5


def test_move_keeps_animation_and_a_custom_nice_name(new_scene):
    node = _node()
    _add([node], "alpha")
    _add([node], "beta")
    cmds.addAttr(f"{node}.beta", edit=True, niceName="Bee Attr")
    cmds.setKeyframe(node, attribute="beta", time=1, value=1)
    cmds.setKeyframe(node, attribute="beta", time=10, value=5)

    logic.move_attributes([node], ["beta"], -1)

    assert logic.custom_attributes(node) == ["beta", "alpha"]
    assert cmds.attributeQuery("beta", node=node, niceName=True) == "Bee Attr"
    assert cmds.keyframe(f"{node}.beta", query=True, valueChange=True) == [1, 5]
    # Nice names that were never customised still follow renames.
    logic.rename_attribute([node], "alpha", "fooBar")
    assert cmds.attributeQuery("fooBar", node=node, niceName=True) == "Foo Bar"


def test_move_several_attributes_and_stop_at_the_ends(new_scene):
    node = _node()
    for name in ("alpha", "beta", "gamma", "delta"):
        _add([node], name)

    logic.move_attributes([node], ["alpha", "gamma"], -1)
    assert logic.custom_attributes(node) == ["alpha", "gamma", "beta", "delta"]

    logic.move_attributes([node], ["delta"], 1)
    assert logic.custom_attributes(node) == ["alpha", "gamma", "beta", "delta"]


def test_move_works_per_node_and_skips_nodes_without_the_attribute(new_scene):
    a, b, c = _nodes("a", "b", "c")
    _add([a], "xx")
    _add([a, b], "yy")
    _add([b], "zz")

    logic.move_attributes([a, b, c], ["yy"], -1)

    assert logic.custom_attributes(a) == ["yy", "xx"]
    assert logic.custom_attributes(b) == ["yy", "zz"]  # already first


def test_move_keeps_a_separator_a_separator(new_scene):
    node = _node()
    _add([node], "alpha")
    logic.add_separator([node], "IK")
    sep = logic.custom_attributes(node)[-1]

    logic.move_attributes([node], [sep], -1)

    assert logic.custom_attributes(node) == [sep, "alpha"]
    assert logic.is_separator(node, sep)
    assert cmds.attributeQuery(sep, node=node, niceName=True) == "IK"


def test_move_refuses_unsupported_attributes_and_changes_nothing(new_scene):
    node = _node()
    _add([node], "alpha")
    cmds.addAttr(node, longName="offset", attributeType="double3")
    for axis in "XYZ":
        cmds.addAttr(node, longName=f"offset{axis}", attributeType="double", parent="offset")

    with pytest.raises(ValueError):
        logic.move_attributes([node], ["alpha"], 1)
    assert logic.custom_attributes(node) == ["alpha", "offset"]


def test_move_is_one_undo_step(new_scene):
    node = _node()
    driver, driven = _rig(node)

    logic.move_attributes([node], ["first"], 1)
    logic.move_attributes([node], ["first"], 1)
    cmds.undo()
    assert logic.custom_attributes(node) == ["second", "first", "third", "label"]
    cmds.undo()

    assert logic.custom_attributes(node) == ["first", "second", "third", "label"]
    _check_rig(node, driver, driven)


def test_reorder_to_any_order(new_scene):
    node = _node()
    for name in ("alpha", "beta", "gamma", "delta"):
        _add([node], name)

    logic.reorder(node, ["delta", "beta", "alpha", "gamma"])

    assert logic.custom_attributes(node) == ["delta", "beta", "alpha", "gamma"]
    with pytest.raises(ValueError):
        logic.reorder(node, ["alpha", "beta"])


# -- lock / hide ------------------------------------------------------------


def test_lock_and_unlock(new_scene):
    nodes = _nodes("a", "b")
    _add(nodes, "twist")

    logic.set_locked(nodes, ["twist", "translateX"], True)
    assert all(cmds.getAttr(f"{n}.twist", lock=True) for n in nodes)
    assert all(cmds.getAttr(f"{n}.translateX", lock=True) for n in nodes)

    logic.set_locked(nodes, ["twist"], False)
    assert not any(cmds.getAttr(f"{n}.twist", lock=True) for n in nodes)


def test_hide_and_unhide(new_scene):
    node = _node()
    _add([node], "twist")
    logic.add_separator([node], "IK")
    sep = logic.custom_attributes(node)[-1]

    logic.set_hidden([node], ["twist", sep], True)
    for attr in ("twist", sep):
        assert not cmds.getAttr(f"{node}.{attr}", keyable=True)
        assert not cmds.getAttr(f"{node}.{attr}", channelBox=True)

    logic.set_hidden([node], ["twist", sep], False)
    assert cmds.getAttr(f"{node}.twist", keyable=True)
    # A separator comes back as shown but still not keyable.
    assert not cmds.getAttr(f"{node}.{sep}", keyable=True)
    assert cmds.getAttr(f"{node}.{sep}", channelBox=True)


def test_lock_and_hide_skip_missing_attributes_and_undo(new_scene):
    a, b = _nodes("a", "b")
    _add([a], "twist")

    result = logic.set_locked([a, b], ["twist"], True)
    assert result.changed == [a]
    assert result.skipped

    logic.set_hidden([a], ["twist"], True)
    cmds.undo()
    cmds.undo()
    assert cmds.getAttr(f"{a}.twist", keyable=True)
    assert not cmds.getAttr(f"{a}.twist", lock=True)


# -- presets ----------------------------------------------------------------


def test_preset_lock_and_hide_scale_and_visibility(new_scene):
    nodes = _nodes("a", "b")

    logic.apply_preset(nodes, "Lock and Hide Scale + Visibility")

    for node in nodes:
        for attr in ("scaleX", "scaleY", "scaleZ", "visibility"):
            assert cmds.getAttr(f"{node}.{attr}", lock=True)
            assert not cmds.getAttr(f"{node}.{attr}", keyable=True)
            assert not cmds.getAttr(f"{node}.{attr}", channelBox=True)
        assert not cmds.getAttr(f"{node}.translateX", lock=True)


def test_unlock_preset_restores_transforms_and_undo(new_scene):
    node = _node()
    logic.apply_preset([node], "Lock and Hide Translate")
    assert cmds.getAttr(f"{node}.translateY", lock=True)

    logic.apply_preset([node], "Unlock and Show Transforms")
    assert not cmds.getAttr(f"{node}.translateY", lock=True)
    assert cmds.getAttr(f"{node}.translateY", keyable=True)

    cmds.undo()
    assert cmds.getAttr(f"{node}.translateY", lock=True)


def test_presets_are_listed_and_unknown_ones_rejected(new_scene):
    assert "Lock and Hide Scale + Visibility" in logic.PRESETS
    with pytest.raises(KeyError):
        logic.apply_preset([_node()], "No Such Preset")


# -- deleting ---------------------------------------------------------------


def test_delete_removes_locked_and_connected_attributes(new_scene):
    a, b, driven = _nodes("a", "b", "driven")
    _add([a, b], "twist")
    _add([a, b], "roll")
    cmds.setAttr(f"{a}.twist", lock=True)
    cmds.connectAttr(f"{a}.twist", f"{driven}.translateX")

    result = logic.delete_attributes([a, b], ["twist"])

    assert result.changed == [a, b]
    assert logic.custom_attributes(a) == logic.custom_attributes(b) == ["roll"]


def test_delete_skips_built_in_attributes_and_undoes(new_scene):
    node = _node()
    _add([node], "twist", default=3)

    result = logic.delete_attributes([node], ["translateX", "twist"])
    assert result.skipped
    assert cmds.attributeQuery("translateX", node=node, exists=True)

    cmds.undo()
    assert cmds.getAttr(f"{node}.twist") == 3


def test_move_keeps_connections_between_attributes_that_both_move(new_scene):
    node = _node()
    for name in ("alpha", "beta", "gamma"):
        _add([node], name)
    cmds.connectAttr(f"{node}.beta", f"{node}.gamma")

    logic.reorder(node, ["gamma", "beta", "alpha"])

    assert logic.custom_attributes(node) == ["gamma", "beta", "alpha"]
    assert cmds.isConnected(f"{node}.beta", f"{node}.gamma")


def test_move_can_be_redone(new_scene):
    node = _node()
    driver, driven = _rig(node)

    logic.move_attributes([node], ["first"], 1)
    cmds.undo()
    cmds.redo()

    assert logic.custom_attributes(node) == ["second", "first", "third", "label"]
    _check_rig(node, driver, driven)
