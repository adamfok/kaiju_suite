import pytest
from maya import cmds

from kaiju_suite.tools.joint_tool import logic


def _chain():
    """Three joints along +X: shoulder (0), elbow (4), wrist (8)."""
    cmds.select(clear=True)
    shoulder = cmds.joint(name="shoulder", position=(0, 0, 0))
    elbow = cmds.joint(name="elbow", position=(4, 0, 0))
    cmds.joint(name="wrist", position=(8, 0, 0))
    cmds.select(clear=True)
    return shoulder, elbow


def _arm():
    """A cylinder along X skinned smoothly to the chain."""
    shoulder, elbow = _chain()
    arm = cmds.polyCylinder(name="arm", radius=0.5, height=8, sx=8, sy=8, axis=(1, 0, 0), constructionHistory=False)[0]
    cmds.setAttr(f"{arm}.translateX", 4)
    cmds.makeIdentity(arm, apply=True, translate=True)
    skin = cmds.skinCluster(shoulder, elbow, arm, toSelectedBones=True, maximumInfluences=2)[0]
    return cmds.ls(arm, long=True)[0], skin, shoulder, elbow


# -- joint management ---------------------------------------------------------


def test_meshes_takes_shapes_and_components(new_scene):
    a, b = _arm()
    shape = cmds.listRelatives(b, shapes=True, noIntermediate=True, fullPath=True)[0]

    assert logic.meshes([f"{a}.vtx[0]", shape, a]) == cmds.ls([a, b], long=True)


# -- QC tab -------------------------------------------------------------------


def test_qc_runs_the_joint_checks_on_the_selected_meshes(new_scene):
    arm, _, shoulder, elbow = _arm()

    found = {check.key: problems for check, problems in logic.run_qc([arm])}

    assert list(found) == ["skinned", "normalized", "influence_count", "small_weights", "unused"]
    assert found["skinned"] == ["arm: no skinCluster"]

    
def test_qc_needs_meshes(new_scene):
    joint = cmds.createNode("joint", name="jnt")

    with pytest.raises(ValueError, match="No meshes selected"):
        logic.run_qc(cmds.ls(joint, long=True))
    with pytest.raises(ValueError, match="No meshes selected"):
        logic.run_qc([])


def test_qc_refuses_bad_settings(new_scene):
    arm, _, shoulder, elbow = _arm()

    with pytest.raises(ValueError, match="max_influences"):
        logic.run_qc(cmds.ls(arm, long=True), {"influence_count": {"max_influences": "four"}})


def test_qc_settings_are_saved_per_user(new_scene):
    logic.save_qc_setting("influence_count", "max_influences", 6)
    try:
        assert logic.qc_settings()["influence_count"]["max_influences"] == 6
    finally:
        cmds.optionVar(remove="kaiju_suite_datatype_skin_qc_influence_count_max_influences")


def test_select_problem_skips_what_is_gone(new_scene):
    from kaiju_suite.core.checks import Problem

    _arm()
    selected = logic.select_problem(Problem("x", ["here", "gone"]))

    assert selected == ["here"]
    assert cmds.ls(selection=True) == ["here"]


def test_qc_with_nothing_selected_checks_nothing(new_scene):
    _arm()

    with pytest.raises(ValueError, match="No meshes selected"):
        logic.run_qc([])


def test_qc_settings_are_the_ones_builder_publish_uses(new_scene):
    from kaiju_suite import datatypes
    from kaiju_suite.datatypes import skin

    logic.save_qc_setting("small_weights", "threshold", 0.05)
    try:
        assert datatypes.qc_settings(skin)["small_weights"]["threshold"] == 0.05
    finally:
        cmds.optionVar(remove="kaiju_suite_datatype_skin_qc_small_weights_threshold")


# -- UI -----------------------------------------------------------------------


def test_ui_loads_without_error(new_scene):
    """Test that the UI module can be imported without errors."""
    from kaiju_suite.tools.joint_tool import widget
    
    # This tests that the UI can be imported and doesn't have syntax errors
    assert hasattr(widget, 'JointToolWindow')