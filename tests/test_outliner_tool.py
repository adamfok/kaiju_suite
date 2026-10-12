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
        (["|joint1", "|joint2"], "", ("", False)),
        ([], "L_*", ("Nothing selected", True)),
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


@pytest.mark.parametrize("button", ["group", "chain", "offset"])
def test_button_icons_ship_as_svg(button):
    import os
    import xml.etree.ElementTree as ET

    from kaiju_suite.ui import icons

    path = icons.path(f"outliner_tool_{button}.svg")
    assert os.path.isfile(path), path
    assert ET.parse(path).getroot().tag == "{http://www.w3.org/2000/svg}svg"
