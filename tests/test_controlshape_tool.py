"""ControlShape Tool logic: its QC tab."""

import pytest
from maya import cmds

from kaiju_suite.tools.controlshape_tool import logic


def _ctrl(name, color=None):
    """A circle control with a ``<name>Shape`` curve shape, colored if ``color`` is given."""
    ctrl = cmds.circle(name=name, constructionHistory=False)[0]
    shape = cmds.listRelatives(ctrl, shapes=True)[0]
    if color is not None:
        cmds.setAttr(f"{shape}.overrideEnabled", True)
        cmds.setAttr(f"{shape}.overrideColor", color)
    return ctrl


def _long(*nodes):
    return cmds.ls(nodes, long=True)


def test_qc_runs_the_controlshape_checks_on_the_selected_controls(new_scene):
    ctrl = _ctrl("L_hand_ctrl", color=17)
    plain = _ctrl("plain_ctrl")

    found = {check.key: problems for check, problems in logic.run_qc(_long(ctrl, plain))}

    assert list(found) == ["no_shapes", "shape_names", "color", "duplicate_names", "rational"]
    assert found["color"] == ["plain_ctrl: no color"]


def test_qc_needs_a_selection(new_scene):
    with pytest.raises(ValueError, match="Nothing selected"):
        logic.run_qc([])


def test_qc_options_are_saved_for_publish_too():
    from kaiju_suite import datatypes
    from kaiju_suite.datatypes import controlshape

    assert logic.QC_CHECKS is controlshape.CHECKS
    assert logic.qc_settings() == datatypes.qc_settings(controlshape)


def test_select_problem_selects_the_control(new_scene):
    _ctrl("plain_ctrl")
    found = dict((check.key, problems) for check, problems in logic.run_qc(_long("plain_ctrl")))

    assert logic.select_problem(found["color"][0]) == ["plain_ctrl"]
    assert cmds.ls(selection=True) == ["plain_ctrl"]


def test_qc_changes_nothing_and_adds_no_undo_step(new_scene):
    ctrl = _ctrl("plain_ctrl")
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    logic.run_qc(_long(ctrl))

    assert not cmds.undoInfo(query=True, undoName=True)
