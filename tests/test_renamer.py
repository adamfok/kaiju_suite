from maya import cmds

from kaiju_suite.tools.renamer import logic


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


def test_registry_finds_renamer():
    from kaiju_suite import registry

    names = [tool["name"] for tool in registry.discover()]
    assert "Renamer" in names
