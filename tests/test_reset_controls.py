from maya import cmds

from kaiju_suite import registry
from kaiju_suite.rigging import controls
from kaiju_suite.tools.reset_controls import logic


def _posed(name):
    control = controls.add(cmds.circle(name=name, constructionHistory=False)[0])
    cmds.setAttr(f"{control}.translateX", 2)
    return control


def test_resets_the_selected_controls(new_scene):
    a, b = _posed("a_ctrl"), _posed("b_ctrl")
    cmds.select(a)

    done, message = logic.reset_controls()
    assert cmds.ls(done) == ["a_ctrl"]
    assert message == "Reset 1 control."

    assert cmds.getAttr(f"{a}.translateX") == 0
    assert cmds.getAttr(f"{b}.translateX") == 2


def test_with_nothing_selected_resets_every_control(new_scene):
    a, b = _posed("a_ctrl"), _posed("b_ctrl")
    cmds.select(clear=True)

    done, message = logic.reset_controls()
    assert len(done) == 2
    assert message == "Reset all 2 controls."

    assert cmds.getAttr(f"{a}.translateX") == 0
    assert cmds.getAttr(f"{b}.translateX") == 0


def test_says_so_when_the_selection_holds_no_controls(new_scene):
    _posed("a_ctrl")
    cmds.select(cmds.createNode("transform", name="other"))

    assert logic.reset_controls() == ([], "None of the selected nodes is a rig control.")
    assert cmds.getAttr("a_ctrl.translateX") == 2


def test_says_so_when_the_scene_has_no_controls(new_scene):
    cmds.select(clear=True)
    assert logic.reset_controls() == ([], "The scene has no rig controls.")


def test_reset_is_one_undo_step(new_scene):
    a, b = _posed("a_ctrl"), _posed("b_ctrl")
    cmds.select(clear=True)
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    logic.reset_controls()
    cmds.undo()

    assert cmds.getAttr(f"{a}.translateX") == 2
    assert cmds.getAttr(f"{b}.translateX") == 2


def test_is_in_the_menu():
    tool = registry.find("Reset Controls")
    assert tool is not None and tool.get("menu", True)
