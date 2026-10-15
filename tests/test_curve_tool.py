"""Curve Tool logic: QC on the selected NURBS curves (the checks themselves
are tests/test_curve_checks.py)."""

import pytest
from maya import cmds

from kaiju_suite import datatypes, registry
from kaiju_suite.datatypes import curves
from kaiju_suite.tools.curve_tool import logic


def _curve(name, points=((0, 0, 0), (1, 2, 0), (3, 1, 1), (4, 4, 2))):
    return cmds.ls(cmds.curve(name=name, degree=3, point=list(points)), long=True)[0]


def test_the_tool_is_in_the_menu_under_utilities():
    tool = registry.find("Curve Tool")
    assert tool is not None
    assert tool["category"] == "Utilities"
    assert callable(tool["launch"])


def test_qc_runs_the_curve_checks_on_the_selected_curves(new_scene):
    ring = cmds.ls(cmds.circle(name="ring_crv")[0], long=True)[0]
    spine = _curve("spine_crv")
    shape = cmds.listRelatives(spine, shapes=True, fullPath=True)[0]

    found = {check.key: problems for check, problems in logic.run_qc([ring, shape])}

    assert list(found) == ["duplicate_names", "rational", "history", "degenerate"]
    assert found["history"] == ["ring_crv: driven by makeNurbCircle1 (only the current shape is saved)"]


def test_qc_takes_components(new_scene):
    dot = _curve("dot_crv", [(1, 1, 1)] * 4)

    found = dict((check.key, problems) for check, problems in logic.run_qc([f"{dot}.cv[0]"]))

    assert found["degenerate"] == ["dot_crv: all CVs on one spot"]


def test_qc_needs_curves(new_scene):
    cube = cmds.ls(cmds.polyCube(name="box", constructionHistory=False)[0], long=True)

    with pytest.raises(ValueError, match="No NURBS curves selected"):
        logic.run_qc(cube)
    with pytest.raises(ValueError, match="No NURBS curves selected"):
        logic.run_qc([])


def test_qc_changes_nothing_and_adds_no_undo_step(new_scene):
    cmds.undoInfo(state=True)
    ring = cmds.ls(cmds.circle(name="ring_crv")[0], long=True)[0]
    cmds.flushUndo()
    before = cmds.ls(long=True)

    logic.run_qc([ring])

    assert cmds.ls(long=True) == before
    assert not cmds.undoInfo(query=True, undoName=True)


def test_qc_options_are_saved_for_publish_too(new_scene):
    logic.save_qc_setting("degenerate", "tolerance", 0.5)
    try:
        assert logic.qc_settings()["degenerate"]["tolerance"] == 0.5
        assert datatypes.qc_settings(curves)["degenerate"]["tolerance"] == 0.5
    finally:
        cmds.optionVar(remove="kaiju_suite_datatype_curves_qc_degenerate_tolerance")


def test_select_problem_selects_the_curve(new_scene):
    ring = cmds.ls(cmds.circle(name="ring_crv")[0], long=True)[0]
    cmds.select(clear=True)
    found = dict((check.key, problems) for check, problems in logic.run_qc([ring]))

    assert logic.select_problem(found["history"][0]) == ["ring_crv"]
    assert cmds.ls(selection=True) == ["ring_crv"]
