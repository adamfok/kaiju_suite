import pytest

from maya import cmds

from kaiju_suite.tools.outliner_tool import logic


def test_rename_sequential(new_scene):
    nodes = [cmds.createNode("transform") for _ in range(3)]
    result = logic.rename_sequential(cmds.ls(nodes, long=True), "arm_##_jnt")
    assert [r.split("|")[-1] for r in result] == ["arm_01_jnt", "arm_02_jnt", "arm_03_jnt"]


def test_rename_parent_and_child_together(new_scene):
    parent = cmds.createNode("transform", name="grp")
    child = cmds.createNode("transform", name="child", parent=parent)
    nodes = cmds.ls([parent, child], long=True)

    result = logic.rename_sequential(nodes, "node_#")

    assert result == ["|node_1", "|node_1|node_2"]


def test_rename_is_one_undo_step(new_scene):
    cmds.undoInfo(state=True)
    nodes = cmds.ls([cmds.createNode("transform", name=f"a{i}") for i in range(3)], long=True)
    logic.add_prefix_suffix(nodes, prefix="L_")
    cmds.undo()
    assert sorted(cmds.ls(nodes, long=True)) == sorted(nodes)


def test_search_replace(new_scene):
    node = cmds.createNode("transform", name="left_arm")
    assert logic.search_replace([node], "left", "right") == ["|right_arm"]


def test_registry_finds_outliner_tool():
    from kaiju_suite import registry

    names = [tool["name"] for tool in registry.discover()]
    assert "Outliner Tool" in names


# -- one-field rename --------------------------------------------------------


def _nodes(*names):
    return cmds.ls([cmds.createNode("transform", name=n) for n in names], long=True)


def _short(names):
    return [n.split("|")[-1] for n in names]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("L_arm_##_jnt", ["L_arm_01_jnt", "L_arm_02_jnt", "L_arm_03_jnt"]),
        ("L_arm_###_jnt", ["L_arm_001_jnt", "L_arm_002_jnt", "L_arm_003_jnt"]),
        ("L_arm_##_jnt @5", ["L_arm_05_jnt", "L_arm_06_jnt", "L_arm_07_jnt"]),
        ("L_arm_##_jnt@10", ["L_arm_10_jnt", "L_arm_11_jnt", "L_arm_12_jnt"]),
        ("arm", ["arm1", "arm2", "arm3"]),
        ("arm @0", ["arm0", "arm1", "arm2"]),
        ("*_jnt", ["joint1_jnt", "joint2_jnt", "bone_jnt"]),
        ("L_*", ["L_joint1", "L_joint2", "L_bone"]),
        ("L_*_jnt", ["L_joint1_jnt", "L_joint2_jnt", "L_bone_jnt"]),
        ("*_##", ["joint1_01", "joint2_02", "bone_03"]),
        ("joint > arm", ["arm1", "arm2", "bone"]),
        ("joint>arm", ["arm1", "arm2", "bone"]),
        ("oint >", ["j1", "j2", "bone"]),
        ("  L_*  ", ["L_joint1", "L_joint2", "L_bone"]),
    ],
)
def test_plan(text, expected):
    assert logic.plan(["|joint1", "|grp|joint2", "|bone"], text) == expected


def test_plan_single_node_without_hashes_is_the_exact_name():
    assert logic.plan(["|joint1"], "L_arm_jnt") == ["L_arm_jnt"]


@pytest.mark.parametrize(
    "text, message",
    [
        ("", "Type a name"),
        ("   ", "Type a name"),
        ("> arm", "Nothing to search for"),
        ("*_*", "Only one *"),
        ("L_arm @x", "not a valid name"),
        ("L arm_##", "not a valid name"),
        ("1_arm", "not a valid name"),
    ],
)
def test_plan_rejects(text, message):
    with pytest.raises(ValueError, match=message):
        logic.plan(["|joint1", "|joint2"], text)


def test_rename_applies_plan(new_scene):
    nodes = _nodes("joint1", "joint2")
    assert _short(logic.rename(nodes, "L_*_jnt")) == ["L_joint1_jnt", "L_joint2_jnt"]
    assert cmds.objExists("L_joint1_jnt") and cmds.objExists("L_joint2_jnt")


def test_rename_parent_and_child_by_text(new_scene):
    parent = cmds.createNode("transform", name="grp")
    child = cmds.createNode("transform", name="child", parent=parent)
    result = logic.rename(cmds.ls([parent, child], long=True), "node_#")
    assert result == ["|node_1", "|node_1|node_2"]


def test_rename_by_text_is_one_undo_step(new_scene):
    cmds.undoInfo(state=True)
    nodes = _nodes("a1", "a2", "a3")
    logic.rename(nodes, "L_arm_##_jnt @5")
    cmds.undo()
    assert sorted(cmds.ls(nodes, long=True)) == sorted(nodes)


def test_rename_bad_text_changes_nothing(new_scene):
    nodes = _nodes("a1")
    with pytest.raises(ValueError):
        logic.rename(nodes, "*_*")
    assert cmds.ls(nodes, long=True) == nodes


@pytest.mark.parametrize(
    "nodes, text, expected",
    [
        (["|joint1", "|joint2", "|joint3"], "L_arm_##_jnt", ("L_arm_01_jnt … L_arm_03_jnt  (3)", False)),
        (["|joint1"], "L_*", ("L_joint1  (1)", False)),
        (["|joint1", "|joint2"], "", ("Rename", False)),
        (["|joint1"], "   ", ("Rename", False)),
        ([], "L_*", ("Rename", False)),
        ([], "", ("Rename", False)),
        ([], "*_*", ("Rename", False)),
        (["|joint1", "|joint2"], "*_*", ("Only one * is allowed", True)),
        (["|a|joint", "|b|joint"], "L_*", ("L_joint … L_joint  (2), 1 name clashes", True)),
    ],
)
def test_preview(nodes, text, expected):
    assert logic.preview(nodes, text) == expected


def test_help_lists_every_shortcut():
    examples = [example for example, _ in logic.SHORTCUTS]
    for example in ("L_arm_##_jnt", "@5", "*_jnt", "L_*", "L_*_jnt", "old > new", "old >"):
        assert any(example in e for e in examples), example


# -- group, chain, offset ----------------------------------------------------


def _world(node):
    return [round(v, 4) for v in cmds.xform(node, query=True, worldSpace=True, matrix=True)]


def _placed(name, translate=(0, 0, 0), rotate=(0, 0, 0), parent=None):
    kwargs = {"name": name}
    if parent:
        kwargs["parent"] = parent
    node = cmds.createNode("transform", **kwargs)
    cmds.xform(node, translation=translate, rotation=rotate)
    return cmds.ls(node, long=True)[0]


@pytest.mark.parametrize(
    "names, expected",
    [
        (["L_arm_01_jnt", "L_arm_02_jnt"], "L_arm"),
        (["joint1", "joint2", "joint3"], "joint"),
        (["L_hand_jnt"], "L_hand_jnt"),
        (["|grp|L_leg_1", "|L_leg_2"], "L_leg"),
        (["ns:L_eye_1", "ns:L_eye_2"], "L_eye"),
        (["arm", "leg"], ""),
        (["_a", "_b"], ""),
    ],
)
def test_common_name(names, expected):
    assert logic.common_name(names) == expected


def test_group_selected_names_it_after_the_selection(new_scene):
    parent = _placed("rig", translate=(1, 0, 0))
    a = _placed("L_arm_01_jnt", translate=(2, 3, 4), parent=parent)
    b = _placed("L_arm_02_jnt", translate=(5, 0, 0), parent=parent)
    before = [_world(a), _world(b)]

    group = logic.group_selected([a, b])

    assert group == "|rig|L_arm_grp"
    assert cmds.listRelatives(group, children=True, fullPath=True) == ["|rig|L_arm_grp|L_arm_01_jnt", "|rig|L_arm_grp|L_arm_02_jnt"]
    assert [_world(n) for n in cmds.listRelatives(group, children=True, fullPath=True)] == before


def test_group_selected_with_nothing_in_common_is_named_after_the_first(new_scene):
    group = logic.group_selected([_placed("arm"), _placed("leg")])
    assert group.split("|")[-1] == "arm_grp"


def test_group_selected_is_one_undo_step(new_scene):
    cmds.undoInfo(state=True)
    nodes = [_placed("a_1"), _placed("a_2")]
    logic.group_selected(nodes)
    cmds.undo()
    assert cmds.ls(nodes, long=True) == nodes
    assert not cmds.objExists("a_grp")


def test_chain_parents_each_node_under_the_one_before(new_scene):
    nodes = [_placed(f"c{i}", translate=(i, i * 2, 0), rotate=(0, i * 10, 0)) for i in range(3)]
    before = [_world(n) for n in nodes]

    result = logic.chain(nodes)

    assert result == ["|c0", "|c0|c1", "|c0|c1|c2"]
    assert [_world(n) for n in result] == before


def test_chain_skips_a_node_already_in_place(new_scene):
    upper = _placed("upper")
    child = _placed("child", parent=upper)
    assert logic.chain([upper, child]) == ["|upper", "|upper|child"]


def test_chain_rejects_a_node_above_an_earlier_one(new_scene):
    upper = _placed("upper")
    child = _placed("child", parent=upper)
    with pytest.raises(ValueError, match="above"):
        logic.chain([child, upper])
    assert cmds.ls([upper, child], long=True) == ["|upper", "|upper|child"]


def test_chain_is_one_undo_step(new_scene):
    cmds.undoInfo(state=True)
    nodes = [_placed(f"c{i}") for i in range(3)]
    logic.chain(nodes)
    cmds.undo()
    assert cmds.ls(nodes, long=True) == nodes


def test_offset_puts_a_matching_group_above_each_node(new_scene):
    parent = _placed("rig", translate=(0, 1, 0))
    a = _placed("L_arm_ctrl", translate=(1, 2, 3), rotate=(0, 45, 0), parent=parent)
    b = _placed("R_arm_ctrl", translate=(-1, 2, 3), parent=parent)
    before = [_world(a), _world(b)]

    offsets = logic.offset([a, b])

    assert offsets == ["|rig|L_arm_ctrl_offset", "|rig|R_arm_ctrl_offset"]
    nodes = ["|rig|L_arm_ctrl_offset|L_arm_ctrl", "|rig|R_arm_ctrl_offset|R_arm_ctrl"]
    assert [_world(n) for n in nodes] == before
    assert [_world(o) for o in offsets] == before
    for node in nodes:
        assert [round(v, 4) for v in cmds.getAttr(f"{node}.translate")[0]] == [0, 0, 0]
        assert [round(v, 4) for v in cmds.getAttr(f"{node}.rotate")[0]] == [0, 0, 0]


def test_offset_of_parent_and_child_together(new_scene):
    upper = _placed("upper", translate=(1, 0, 0))
    child = _placed("child", translate=(0, 1, 0), parent=upper)

    offsets = logic.offset([upper, child])

    assert offsets == ["|upper_offset", "|upper_offset|upper|child_offset"]
    assert cmds.ls("child", long=True) == ["|upper_offset|upper|child_offset|child"]


def test_offset_is_one_undo_step(new_scene):
    cmds.undoInfo(state=True)
    nodes = [_placed("a", translate=(1, 2, 3)), _placed("b")]
    logic.offset(nodes)
    cmds.undo()
    assert cmds.ls(nodes, long=True) == nodes
    assert not cmds.ls("*_offset")


# -- button icons ------------------------------------------------------------


@pytest.mark.parametrize("button", ["group", "chain", "offset", "parent", "unparent", "reparent", "lock", "unlock"])
def test_button_icons_ship_as_svg(button):
    import os
    import xml.etree.ElementTree as ET

    from kaiju_suite.ui import icons

    path = icons.path(f"outliner_tool_{button}.svg")
    assert os.path.isfile(path), path
    assert ET.parse(path).getroot().tag == "{http://www.w3.org/2000/svg}svg"


# -- lock and hide -----------------------------------------------------------

_STANDARD = ["visibility", "translateX", "translateY", "translateZ",
             "rotateX", "rotateY", "rotateZ", "scaleX", "scaleY", "scaleZ"]


def _node(kind="transform", **extra):
    """A node of ``kind`` with one keyable attribute per ``name=attributeType``."""
    node = cmds.ls(cmds.createNode(kind, name="ctrl"), long=True)[0]
    for name, kind in extra.items():
        cmds.addAttr(node, longName=name, attributeType=kind, keyable=True, **({"enumName": "a:b"} if kind == "enum" else {}))
    return node


def _keyable(node):
    return cmds.listAttr(node, keyable=True) or []


def _shown(node):
    """Shown in the channel box but not keyable."""
    return cmds.listAttr(node, channelBox=True) or []


def _locked(node, attr):
    return cmds.getAttr(f"{node}.{attr}", lock=True)


def test_lock_and_hide_locks_and_hides_every_channel_box_attribute(new_scene):
    node = _node(space="enum")

    assert logic.lock_and_hide([node]) == [node]

    assert _keyable(node) == [] and _shown(node) == []
    assert all(_locked(node, a) for a in _STANDARD + ["space"])


def test_lock_and_hide_hides_shown_attributes_too(new_scene):
    joint = _node("joint")
    assert "radius" in _shown(joint)

    logic.lock_and_hide([joint])

    assert _keyable(joint) == [] and _shown(joint) == []


def test_lock_and_hide_handles_several_nodes(new_scene):
    a, b = _node(), _node()

    logic.lock_and_hide([a, b])

    assert _keyable(a) == _keyable(b) == []


def test_unlock_and_show_makes_the_standard_channels_keyable(new_scene):
    node = _node()
    logic.lock_and_hide([node])

    assert logic.unlock_and_show([node]) == [node]

    assert _keyable(node) == _STANDARD
    assert _shown(node) == []
    assert not any(_locked(node, a) for a in _STANDARD)


@pytest.mark.parametrize("kind", [
    "bool", "enum", "long", "short", "byte", "float", "double", "doubleLinear", "doubleAngle",
])
def test_unlock_and_show_makes_own_numeric_attributes_keyable(new_scene, kind):
    node = _node(extra=kind)
    logic.lock_and_hide([node])

    logic.unlock_and_show([node])

    assert "extra" in _keyable(node)
    assert not _locked(node, "extra")


def test_unlock_and_show_leaves_text_attributes_hidden(new_scene):
    node = _node()
    cmds.addAttr(node, longName="note", dataType="string")

    logic.unlock_and_show([node])

    assert "note" not in _keyable(node) + _shown(node)


def test_unlock_and_show_shows_joint_radius_without_making_it_keyable(new_scene):
    joint = _node("joint")
    logic.lock_and_hide([joint])

    logic.unlock_and_show([joint])

    assert _shown(joint) == ["radius"]
    assert "radius" not in _keyable(joint)
    assert not _locked(joint, "radius")


def test_lock_and_hide_is_one_undo_step(new_scene):
    cmds.undoInfo(state=True)
    node = _node(space="enum")
    before = _keyable(node)
    logic.lock_and_hide([node])
    cmds.undo()
    assert _keyable(node) == before
    assert not _locked(node, "translateX")


def test_unlock_and_show_is_one_undo_step(new_scene):
    cmds.undoInfo(state=True)
    node = _node()
    logic.lock_and_hide([node])
    logic.unlock_and_show([node])
    cmds.undo()
    assert _keyable(node) == []
    assert _locked(node, "translateX")


@pytest.mark.parametrize("func", ["lock_and_hide", "unlock_and_show"])
def test_lock_and_unlock_need_a_selection(func):
    with pytest.raises(ValueError):
        getattr(logic, func)([])


# -- unparent and reparent ---------------------------------------------------


def test_unparent_moves_node_to_world(new_scene):
    parent = _placed("rig", translate=(1, 2, 3))
    child = _placed("child", translate=(4, 5, 6), parent=parent)
    before_world = _world(child)

    result = logic.unparent([child])

    assert result == ["|child"]
    assert cmds.listRelatives("|child", parent=True, fullPath=True) is None
    assert _world("|child") == before_world


def test_unparent_node_already_at_world(new_scene):
    node = _placed("root", translate=(1, 2, 3))
    result = logic.unparent([node])
    assert result == ["|root"]
    assert cmds.listRelatives("|root", parent=True, fullPath=True) is None


def test_unparent_is_one_undo_step(new_scene):
    cmds.undoInfo(state=True)
    parent = _placed("rig")
    child = _placed("child", parent=parent)
    logic.unparent([child])
    cmds.undo()
    assert cmds.ls(child, long=True) == [child]


def test_reparent_restores_previous_parent(new_scene):
    parent = _placed("rig", translate=(1, 2, 3))
    child = _placed("child", translate=(4, 5, 6), parent=parent)
    before_world = _world(child)

    logic.unparent([child])
    result = logic.reparent(["|child"])

    assert result == ["|rig|child"]
    assert cmds.listRelatives(result[0], parent=True, fullPath=True) == ["|rig"]
    assert _world(result[0]) == before_world


def test_unparent_and_reparent_multiple_nodes(new_scene):
    p1 = _placed("rig1")
    p2 = _placed("rig2")
    c1 = _placed("c1", parent=p1)
    c2 = _placed("c2", parent=p2)

    unparented = logic.unparent([c1, c2])
    assert unparented == ["|c1", "|c2"]

    reparented = logic.reparent(unparented)
    assert reparented == ["|rig1|c1", "|rig2|c2"]


def test_unparent_and_reparent_nested_hierarchy(new_scene):
    grandparent = _placed("grandparent")
    parent = _placed("parent", parent=grandparent)
    child = _placed("child", parent=parent)

    unparented = logic.unparent([parent, child])
    assert unparented == ["|parent", "|child"]

    reparented = logic.reparent(unparented)
    assert reparented == ["|grandparent|parent", "|grandparent|parent|child"]


def test_reparent_works_after_parent_renamed(new_scene):
    parent = _placed("rig")
    child = _placed("child", parent=parent)

    logic.unparent([child])
    cmds.rename(parent, "rig_renamed")

    reparented = logic.reparent(["|child"])
    assert reparented == ["|rig_renamed|child"]


def test_reparent_works_after_child_renamed(new_scene):
    parent = _placed("rig")
    child = _placed("child", parent=parent)

    logic.unparent([child])
    cmds.rename("|child", "child_renamed")

    reparented = logic.reparent(["|child_renamed"])
    assert reparented == ["|rig|child_renamed"]


def test_reparent_without_unparent_raises(new_scene):
    node = _placed("standalone")
    with pytest.raises(ValueError, match="No previous parent"):
        logic.reparent([node])


def test_reparent_when_parent_deleted_raises(new_scene):
    parent = _placed("rig")
    child = _placed("child", parent=parent)

    logic.unparent([child])
    cmds.delete(parent)

    with pytest.raises(ValueError, match="no longer exists"):
        logic.reparent(["|child"])


def test_reparent_is_one_undo_step(new_scene):
    cmds.undoInfo(state=True)
    parent = _placed("rig")
    child = _placed("child", parent=parent)
    logic.unparent([child])
    logic.reparent(["|child"])
    cmds.undo()
    assert cmds.ls("|child", long=True) == ["|child"]


def test_reparent_clears_the_saved_parent(new_scene):
    parent = _placed("rig")
    child = _placed("child", parent=parent)
    logic.unparent([child])
    logic.reparent(["|child"])
    assert not _has_saved_parent("|rig|child")
    with pytest.raises(ValueError, match="No previous parent"):
        logic.reparent(["|rig|child"])


def test_reparent_node_already_back_under_saved_parent_just_clears(new_scene):
    parent = _placed("rig")
    child = _placed("child", parent=parent)
    logic.unparent([child])
    cmds.parent("|child", "|rig")
    assert logic.reparent(["|rig|child"]) == ["|rig|child"]
    assert not _has_saved_parent("|rig|child")


def test_unparent_mixed_world_and_child_nodes(new_scene):
    root = _placed("root")
    parent = _placed("rig")
    child = _placed("child", parent=parent)

    result = logic.unparent([root, child])
    assert result == ["|root", "|child"]


def test_reparent_mixed_nodes_reparents_the_remembered_ones(new_scene):
    parent = _placed("rig")
    child = _placed("child", parent=parent)
    other = _placed("other")

    logic.unparent([child])
    result = logic.reparent(["|child", other])
    assert result == ["|rig|child", "|other"]


@pytest.mark.parametrize("func", ["unparent", "reparent"])
def test_unparent_and_reparent_need_a_selection(func):
    with pytest.raises(ValueError, match="Nothing selected"):
        getattr(logic, func)([])


def test_reparent_changes_nothing_when_one_previous_parent_is_gone(new_scene):
    keep = _placed("keep")
    gone = _placed("gone")
    _placed("a", parent=keep)
    _placed("b", parent=gone)
    logic.unparent(["|keep|a", "|gone|b"])
    cmds.delete(gone)

    with pytest.raises(ValueError, match="no longer exists"):
        logic.reparent(["|a", "|b"])

    assert cmds.ls("a", long=True) == ["|a"]


def test_reparent_skips_node_moved_since_unparent_was_undone(new_scene):
    cmds.undoInfo(state=True)
    parent = _placed("rig")
    child = _placed("child", parent=parent)
    logic.unparent([child])
    cmds.undo()
    other = _placed("other")
    cmds.parent(child, other)

    with pytest.raises(ValueError, match="No previous parent"):
        logic.reparent(["|other|child"])

    assert cmds.ls("child", long=True) == ["|other|child"]


def test_reparent_works_again_after_undo(new_scene):
    cmds.undoInfo(state=True)
    parent = _placed("rig")
    child = _placed("child", parent=parent)
    logic.unparent([child])
    logic.reparent(["|child"])
    cmds.undo()

    assert logic.reparent(["|child"]) == ["|rig|child"]


def test_reparent_under_own_descendant_raises_value_error(new_scene):
    parent = _placed("rig")
    child = _placed("child", parent=parent)
    logic.unparent([child])
    cmds.parent(parent, "|child")

    with pytest.raises(ValueError, match="is now under"):
        logic.reparent(["|child"])

    assert cmds.ls("child", long=True) == ["|child"]


# -- parent and saved parents -------------------------------------------------


def _has_saved_parent(node):
    return cmds.attributeQuery("kaijuPrevParentUuid", node=node, exists=True)


def test_unparent_saves_parent_on_the_node(new_scene):
    parent = _placed("rig")
    child = _placed("child", parent=parent)
    logic.unparent([child])
    assert cmds.getAttr("|child.kaijuPrevParentUuid") == cmds.ls(parent, uuid=True)[0]
    assert cmds.getAttr("|child.kaijuPrevParentName") == "|rig"


def test_reparent_works_after_saving_and_reopening_the_scene(new_scene, tmp_path):
    parent = _placed("rig")
    child = _placed("child", parent=parent)
    logic.unparent([child])
    path = str(tmp_path / "scene.ma").replace("\\", "/")
    cmds.file(rename=path)
    cmds.file(save=True, type="mayaAscii")
    cmds.file(new=True, force=True)
    cmds.file(path, open=True, force=True)
    assert logic.reparent(["|child"]) == ["|rig|child"]


def test_reparent_falls_back_to_the_name_when_uuid_is_gone(new_scene):
    parent = _placed("rig")
    child = _placed("child", parent=parent)
    logic.unparent([child])
    cmds.setAttr("|child.kaijuPrevParentUuid", "00000000-0000-0000-0000-000000000000", type="string")
    assert logic.reparent(["|child"]) == ["|rig|child"]


def test_reparent_returns_node_from_anywhere(new_scene):
    parent = _placed("rig")
    child = _placed("child", parent=parent)
    temp = _placed("temp")
    logic.unparent([child])
    cmds.parent("|child", temp)
    assert logic.reparent(["|temp|child"]) == ["|rig|child"]


def test_parent_under_last_moves_nodes_and_keeps_world_position(new_scene):
    rig = _placed("rig", translate=(1, 2, 3))
    a = _placed("a", translate=(4, 5, 6), parent=rig)
    b = _placed("b", translate=(7, 8, 9))
    target = _placed("target", translate=(-1, 0, 2), rotate=(0, 45, 0))
    before = [_world(a), _world(b)]

    result = logic.parent_under_last([a, b, target])

    assert result == ["|target|a", "|target|b"]
    assert [_world(n) for n in result] == before


def test_parent_under_last_needs_two_nodes(new_scene):
    with pytest.raises(ValueError):
        logic.parent_under_last([_placed("a")])


def test_parent_under_last_refuses_target_below_a_node(new_scene):
    a = _placed("a")
    below = _placed("below", parent=a)
    with pytest.raises(ValueError, match="under"):
        logic.parent_under_last([a, below])
    assert cmds.ls("|a|below", long=True) == ["|a|below"]


def test_parent_then_reparent_restores_previous_parent(new_scene):
    rig = _placed("rig")
    child = _placed("child", parent=rig)
    target = _placed("target")
    logic.parent_under_last([child, target])
    assert logic.reparent(["|target|child"]) == ["|rig|child"]


def test_parent_from_world_then_reparent_goes_back_to_world(new_scene):
    node = _placed("node", translate=(1, 2, 3))
    target = _placed("target", translate=(5, 0, 0))
    before = _world(node)
    logic.parent_under_last([node, target])
    assert logic.reparent(["|target|node"]) == ["|node"]
    assert _world("|node") == before


def test_reparent_goes_back_to_the_first_saved_parent(new_scene):
    rig = _placed("rig")
    child = _placed("child", parent=rig)
    temp = _placed("temp")
    logic.unparent([child])
    logic.parent_under_last(["|child", temp])
    assert logic.reparent(["|temp|child"]) == ["|rig|child"]


def test_parent_skips_nodes_already_under_the_target(new_scene):
    target = _placed("target")
    child = _placed("child", parent=target)
    assert logic.parent_under_last([child, target]) == ["|target|child"]
    assert not _has_saved_parent("|target|child")


def test_parent_under_last_is_one_undo_step(new_scene):
    cmds.undoInfo(state=True)
    rig = _placed("rig")
    child = _placed("child", parent=rig)
    target = _placed("target")
    logic.parent_under_last([child, target])
    cmds.undo()
    assert cmds.ls(child, long=True) == [child]
    assert not _has_saved_parent(child)
