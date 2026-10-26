import pytest
from maya import cmds

from kaiju_suite.tools.joint_tool import logic


def _long(name):
    return cmds.ls(name, long=True)[0]


# -- QC tab -----------------------------------------------------------------


def _qc_leg():
    cmds.select(clear=True)
    made = [cmds.joint(name=n, position=p) for n, p in (("L_hip", (1, 10, 0)), ("L_knee", (1, 5, 1)))]
    cmds.select(clear=True)
    return made


def test_qc_runs_the_joint_checks_on_the_selected_joints(new_scene):
    hip, knee = _qc_leg()
    cmds.setAttr(f"{knee}.rotateZ", 15)

    found = {check.key: problems for check, problems in logic.run_qc([_long(hip)])}

    assert list(found) == ["rotate", "scale", "end_orient", "overlapping", "duplicate_names", "mirror"]
    assert found["rotate"] == ["L_knee: rotate is (0, 0, 15)"]


def test_qc_needs_joints(new_scene):
    cube = cmds.polyCube(name="box", constructionHistory=False)[0]

    with pytest.raises(ValueError, match="No joints selected"):
        logic.run_qc([_long(cube)])
    with pytest.raises(ValueError, match="No joints selected"):
        logic.run_qc([])


def test_qc_options_are_saved_for_publish_too(new_scene):
    from kaiju_suite import datatypes
    from kaiju_suite.datatypes import joints

    logic.save_qc_setting("mirror", "tolerance", 0.5)
    try:
        assert logic.qc_settings()["mirror"]["tolerance"] == 0.5
        assert datatypes.qc_settings(joints)["mirror"]["tolerance"] == 0.5
    finally:
        cmds.optionVar(remove="kaiju_suite_datatype_joints_qc_mirror_tolerance")


def test_select_problem_selects_the_joints(new_scene):
    hip, knee = _qc_leg()
    cmds.setAttr(f"{knee}.scaleX", 2)
    found = dict((check.key, problems) for check, problems in logic.run_qc([_long(hip)]))

    assert logic.select_problem(found["scale"][0]) == ["L_knee"]
    assert cmds.ls(selection=True) == ["L_knee"]
