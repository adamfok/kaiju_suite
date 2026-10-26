import pytest
from maya import cmds

from kaiju_suite.tools.blendshape_tool import logic


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


# -- target management ------------------------------------------------------


def test_mesh_from_selection(new_scene):
    arm, _, _, _ = _arm()
    shape = cmds.listRelatives(arm, shapes=True, noIntermediate=True, fullPath=True)[0]

    assert logic.meshes([f"{arm}.vtx[0]", shape]) == [arm]


# -- QC tab -----------------------------------------------------------------


def test_qc_runs_the_blendshape_checks_on_the_selected_meshes(new_scene):
    arm, _, _, _ = _arm()

    found = {check.key: problems for check, problems in logic.run_qc([arm])}

    assert list(found) == ["blendshape", "order", "empty_targets", "duplicate_names"]
    assert found["blendshape"] == ["arm: no blendShape"]


def test_qc_needs_meshes(new_scene):
    joint = cmds.createNode("joint", name="jnt")

    with pytest.raises(ValueError, match="No meshes selected"):
        logic.run_qc(cmds.ls(joint, long=True))
    with pytest.raises(ValueError, match="No meshes selected"):
        logic.run_qc([])


def test_qc_settings_are_shared_with_publish(new_scene):
    from kaiju_suite import datatypes
    from kaiju_suite.datatypes import blendshape

    assert logic.QC_CHECKS is blendshape.CHECKS
    assert logic.qc_settings() == datatypes.qc_settings(blendshape)


def test_select_problem_selects_the_mesh(new_scene):
    arm, _, _, _ = _arm()
    found = dict((check.key, problems) for check, problems in logic.run_qc([arm]))
    cmds.select(clear=True)

    assert logic.select_problem(found["blendshape"][0]) == ["arm"]
    assert cmds.ls(selection=True) == ["arm"]
