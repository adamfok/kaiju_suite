import pytest
from maya import cmds

from kaiju_suite import registry, rig
from kaiju_suite.tools.space_switch import logic


def _rig_control(name, x):
    """``name`` under ``<name>_grp`` at ``(x, 8, 0)``, with world, chest and
    head spaces built on it."""
    group = cmds.createNode("transform", name=f"{name}_grp")
    cmds.xform(group, worldSpace=True, translation=(x, 8, 0))
    cmds.createNode("transform", name=name, parent=group)
    rig.get("space_switch").build(
        {"control": name, "driven": group, "spaces": "world=world_space, chest=chest_ctrl, head=head_ctrl"}
    )


def _scene():
    for name, position in (("world_space", (0, 0, 0)), ("chest_ctrl", (0, 10, 0)), ("head_ctrl", (0, 15, 2))):
        node = cmds.createNode("transform", name=name)
        cmds.xform(node, worldSpace=True, translation=position)
    _rig_control("L_hand_ctrl", 5)
    _rig_control("R_hand_ctrl", -5)
    # Move the targets so every space puts the hands somewhere else.
    cmds.move(0, 5, 3, "chest_ctrl", relative=True)
    cmds.rotate(0, 45, 0, "head_ctrl", relative=True)
    cmds.move(1, 2, 3, "L_hand_ctrl", "R_hand_ctrl", relative=True)


def _world(node):
    return cmds.xform(node, query=True, worldSpace=True, matrix=True)


def test_tool_is_registered_without_loading_its_window():
    tool = registry.find("Space Switch Tool")

    assert tool is not None
    assert tool["category"] == "Animation"
    assert callable(tool["launch"])


def test_space_controls_keeps_only_nodes_with_a_space(new_scene):
    _scene()

    assert logic.space_controls(["L_hand_ctrl", "chest_ctrl", "R_hand_ctrl"]) == ["L_hand_ctrl", "R_hand_ctrl"]


def test_common_spaces(new_scene):
    _scene()

    assert logic.common_spaces(["L_hand_ctrl", "R_hand_ctrl"]) == ["world", "chest", "head"]
    assert logic.common_spaces(["chest_ctrl"]) == []


def test_current_space(new_scene):
    _scene()
    cmds.setAttr("R_hand_ctrl.space", 2)

    assert logic.current_space("L_hand_ctrl") == "world"
    assert logic.current_space("R_hand_ctrl") == "head"


def test_switch_without_pop(new_scene):
    _scene()
    before = {node: _world(node) for node in ("L_hand_ctrl", "R_hand_ctrl")}

    result = logic.switch(["L_hand_ctrl", "R_hand_ctrl", "chest_ctrl"], "head")

    assert result.changed == ["L_hand_ctrl", "R_hand_ctrl"]
    assert result.skipped == ["chest_ctrl"]
    for node, matrix in before.items():
        assert cmds.getAttr(f"{node}.space") == 2
        assert _world(node) == pytest.approx(matrix, abs=1e-4)


def test_switch_skips_a_control_without_that_space(new_scene):
    _scene()

    result = logic.switch(["L_hand_ctrl"], "moon")

    assert result.changed == []
    assert result.skipped == ["L_hand_ctrl"]


def test_switch_is_one_undo_step(new_scene):
    _scene()
    cmds.undoInfo(state=True)
    before = {node: (_world(node), cmds.getAttr(f"{node}.translate")[0]) for node in ("L_hand_ctrl", "R_hand_ctrl")}

    logic.switch(["L_hand_ctrl", "R_hand_ctrl"], "chest")
    cmds.undo()

    for node, (matrix, translate) in before.items():
        assert cmds.getAttr(f"{node}.space") == 0
        assert cmds.getAttr(f"{node}.translate")[0] == pytest.approx(translate)
        assert _world(node) == pytest.approx(matrix, abs=1e-4)


def test_keyed_switch_keys_both_frames_without_a_pop(new_scene):
    _scene()
    cmds.currentTime(10)
    before = _world("L_hand_ctrl")

    logic.switch(["L_hand_ctrl"], "head", key=True)

    assert cmds.keyframe("L_hand_ctrl.space", query=True, timeChange=True) == [9.0, 10.0]
    assert cmds.keyframe("L_hand_ctrl.translateX", query=True, timeChange=True) == [9.0, 10.0]
    assert cmds.keyframe("L_hand_ctrl.rotateY", query=True, timeChange=True) == [9.0, 10.0]
    assert _world("L_hand_ctrl") == pytest.approx(before, abs=1e-4)
    cmds.currentTime(9)
    assert cmds.getAttr("L_hand_ctrl.space") == 0
    assert _world("L_hand_ctrl") == pytest.approx(before, abs=1e-4)
    cmds.currentTime(10)
    assert cmds.getAttr("L_hand_ctrl.space") == 2
    assert _world("L_hand_ctrl") == pytest.approx(before, abs=1e-4)


def test_keyed_switch_is_one_undo_step(new_scene):
    _scene()
    cmds.undoInfo(state=True)
    cmds.currentTime(10)

    logic.switch(["L_hand_ctrl"], "head", key=True)
    cmds.undo()

    assert not cmds.keyframe("L_hand_ctrl", query=True)
    assert cmds.getAttr("L_hand_ctrl.space") == 0
