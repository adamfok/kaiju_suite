import pytest
from maya import cmds

from kaiju_suite.tools.pose_tool import logic


def _ctrl(name, x=0.0, parent=None):
    """A control under an offset group at ``(x, 0, 0)``, world-aligned."""
    group = cmds.createNode("transform", name=f"{name}_grp", parent=parent)
    cmds.setAttr(f"{group}.translateX", x)
    return cmds.ls(cmds.createNode("transform", name=name, parent=group), long=True)[0]


# -- QC tab -----------------------------------------------------------------


def test_qc_runs_the_pose_checks_on_the_selected_nodes(new_scene):
    ctrl = _ctrl("L_hand_ctrl")
    driver = cmds.createNode("transform", name="driver")
    cmds.connectAttr(f"{driver}.rotateY", f"{ctrl}.rotateY")

    found = {check.key: problems for check, problems in logic.run_qc([ctrl])}

    assert list(found) == ["driven", "nothing_to_save", "duplicate_names"]
    assert found["driven"] == ["L_hand_ctrl: 1 driven attribute (Run will skip them): rotateY"]
    assert found["nothing_to_save"] == [] and found["duplicate_names"] == []


def test_qc_needs_a_selection(new_scene):
    with pytest.raises(ValueError, match="Nothing selected"):
        logic.run_qc([])


def test_qc_options_are_shared_with_publish(new_scene):
    from kaiju_suite import datatypes
    from kaiju_suite.datatypes import pose

    assert logic.QC_CHECKS is pose.CHECKS
    assert logic.qc_settings() == datatypes.qc_settings(pose)


def test_select_problem_selects_the_nodes(new_scene):
    a = _ctrl("ctrl", parent=cmds.createNode("transform", name="a"))
    _ctrl("ctrl", parent=cmds.createNode("transform", name="b"))
    found = {check.key: problems for check, problems in logic.run_qc([a])}
    (problem,) = found["duplicate_names"]
    assert logic.select_problem(problem) == ["a|ctrl_grp|ctrl", "b|ctrl_grp|ctrl"]
