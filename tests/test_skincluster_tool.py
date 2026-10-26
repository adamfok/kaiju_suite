import pytest
from maya import cmds

from kaiju_suite.datatypes import skin
from kaiju_suite.tools.skincluster_tool import logic


def _joint(name, x):
    cmds.select(clear=True)
    return cmds.joint(name=name, position=(x, 0, 0))


def _plane(name, sx=1, x=0.0):
    plane = cmds.polyPlane(name=name, width=2, height=2, sx=sx, sy=1, constructionHistory=False)[0]
    cmds.setAttr(f"{plane}.translateX", x)
    return plane


def _skinned_source():
    """A 2x2 plane: its -X half on ``left``, its +X half on ``right``."""
    left, right = _joint("left", -1), _joint("right", 1)
    plane = _plane("src")
    cluster = cmds.skinCluster(left, right, plane, toSelectedBones=True)[0]
    for v in range(cmds.polyEvaluate(plane, vertex=True)):
        x = cmds.pointPosition(f"{plane}.vtx[{v}]", world=True)[0]
        cmds.skinPercent(cluster, f"{plane}.vtx[{v}]", transformValue=[(left if x < 0 else right, 1.0)])
    return plane, cluster


# -- clean up ---------------------------------------------------------------


def test_meshes_takes_shapes_and_components(new_scene):
    a, b = _plane("a"), _plane("b")
    shape = cmds.listRelatives(b, shapes=True, fullPath=True)[0]

    assert logic.meshes([f"{a}.vtx[0]", shape, a]) == cmds.ls([a, b], long=True)


# -- QC tab -----------------------------------------------------------------


def test_qc_runs_the_skin_checks_on_the_selected_meshes(new_scene):
    src, _ = _skinned_source()
    bare = _plane("bare")
    cmds.select(src, bare)

    found = {check.key: problems for check, problems in logic.run_qc(cmds.ls(selection=True, long=True))}

    assert list(found) == ["skinned", "normalized", "influence_count", "small_weights", "unused"]
    assert found["skinned"] == ["bare: no skinCluster"]


def test_qc_needs_meshes(new_scene):
    joint = _joint("j", 0)

    with pytest.raises(ValueError, match="No meshes selected"):
        logic.run_qc(cmds.ls(joint, long=True))


def test_qc_refuses_bad_settings(new_scene):
    src, _ = _skinned_source()

    with pytest.raises(ValueError, match="max_influences"):
        logic.run_qc(cmds.ls(src, long=True), {"influence_count": {"max_influences": "four"}})


def test_qc_settings_are_saved_per_user(new_scene):
    logic.save_qc_setting("influence_count", "max_influences", 6)
    try:
        assert logic.qc_settings()["influence_count"]["max_influences"] == 6
    finally:
        cmds.optionVar(remove="kaiju_suite_datatype_skin_qc_influence_count_max_influences")


def test_select_problem_skips_what_is_gone(new_scene):
    from kaiju_suite.core.checks import Problem

    _plane("here")
    selected = logic.select_problem(Problem("x", ["here", "gone"]))

    assert selected == ["here"]
    assert cmds.ls(selection=True) == ["here"]


def test_qc_with_nothing_selected_checks_nothing(new_scene):
    _skinned_source()

    with pytest.raises(ValueError, match="No meshes selected"):
        logic.run_qc([])


def test_qc_settings_are_the_ones_builder_publish_uses(new_scene):
    from kaiju_suite import datatypes

    logic.save_qc_setting("small_weights", "threshold", 0.05)
    try:
        assert datatypes.qc_settings(skin)["small_weights"]["threshold"] == 0.05
    finally:
        cmds.optionVar(remove="kaiju_suite_datatype_skin_qc_small_weights_threshold")
