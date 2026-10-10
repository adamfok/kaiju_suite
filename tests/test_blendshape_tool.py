import pytest
from maya import cmds
from maya.api import OpenMaya as om

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


def _points(mesh):
    shape = cmds.listRelatives(mesh, shapes=True, noIntermediate=True, fullPath=True)[0]
    fn = om.MFnMesh(om.MSelectionList().add(shape).getDagPath(0))
    return [om.MPoint(p) for p in fn.getPoints(om.MSpace.kWorld)]


def _max_distance(a, b):
    return max(p.distanceTo(q) for p, q in zip(a, b))


def _sculpt_bump(sculpt):
    """Push the vertices near the elbow outwards, unevenly."""
    for v, p in enumerate(_points(sculpt)):
        if p.distanceTo(om.MPoint(4, 0, 0)) < 2.0:
            cmds.move(0.3, 0.2 + 0.05 * (v % 3), -0.1, f"{sculpt}.vtx[{v}]", relative=True, worldSpace=True)


def _posed_arm():
    arm, skin, shoulder, elbow = _arm()
    rest = _points(arm)
    cmds.setAttr(f"{elbow}.rotateZ", 70)
    cmds.setAttr(f"{shoulder}.rotateY", -25)
    return arm, skin, shoulder, elbow, rest


# -- sculpting --------------------------------------------------------------


def test_start_sculpt_duplicates_the_posed_mesh(new_scene):
    arm, _, _, _, _ = _posed_arm()

    sculpt = logic.start_sculpt(arm)

    assert sculpt != arm and cmds.objExists(sculpt)
    assert _max_distance(_points(sculpt), _points(arm)) < 1e-4
    assert not cmds.ls(cmds.listHistory(sculpt), type="skinCluster")
    assert logic.sculpt_base(sculpt) == arm
    assert not cmds.getAttr(f"{arm}.visibility")


def test_create_corrective_makes_the_posed_mesh_match_the_sculpt(new_scene):
    arm, skin, _, _, _ = _posed_arm()
    sculpt = logic.start_sculpt(arm)
    _sculpt_bump(sculpt)
    wanted = _points(sculpt)
    assert _max_distance(wanted, _points(arm)) > 0.2

    node, target = logic.create_corrective(arm, sculpt, name="elbow_fix")

    assert target == "elbow_fix"
    assert _max_distance(_points(arm), wanted) < 1e-4
    # The blendShape sits before the skin, and the sculpt is cleaned up.
    assert skin in cmds.listHistory(node, future=True)
    assert not cmds.objExists(sculpt)
    assert cmds.getAttr(f"{arm}.visibility")


def test_corrective_is_off_at_rest_when_weight_is_zero(new_scene):
    arm, _, shoulder, elbow, rest = _posed_arm()
    sculpt = logic.start_sculpt(arm)
    _sculpt_bump(sculpt)
    node, target = logic.create_corrective(arm, sculpt)

    logic.set_weight(node, target, 0.0)
    cmds.setAttr(f"{elbow}.rotateZ", 0)
    cmds.setAttr(f"{shoulder}.rotateY", 0)

    assert _max_distance(_points(arm), rest) < 1e-4


def test_create_corrective_reuses_a_blendshape_before_the_skin(new_scene):
    arm, _, _, elbow, _ = _posed_arm()
    first_node, _ = logic.create_corrective(arm, logic.start_sculpt(arm), name="a")
    cmds.setAttr(f"{elbow}.rotateZ", 30)
    sculpt = logic.start_sculpt(arm)
    _sculpt_bump(sculpt)
    wanted = _points(sculpt)

    node, target = logic.create_corrective(arm, sculpt, name="b")

    assert node == first_node
    assert [name for _, name in logic.targets(node)] == ["a", "b"]
    assert _max_distance(_points(arm), wanted) < 1e-4


def test_create_corrective_keeps_the_sculpt_when_asked(new_scene):
    arm, _, _, _, _ = _posed_arm()
    sculpt = logic.start_sculpt(arm)

    logic.create_corrective(arm, sculpt, keep_sculpt=True)

    assert cmds.objExists(sculpt)
    assert not cmds.getAttr(f"{sculpt}.visibility")


def test_create_corrective_rejects_a_different_topology(new_scene):
    arm, _, _, _, _ = _posed_arm()
    other = cmds.polyCube(constructionHistory=False)[0]

    with pytest.raises(ValueError):
        logic.create_corrective(arm, other)


def test_create_corrective_is_one_undo_step(new_scene):
    cmds.undoInfo(state=True)
    arm, _, _, _, _ = _posed_arm()
    sculpt = logic.start_sculpt(arm)
    _sculpt_bump(sculpt)
    before = _points(arm)

    logic.create_corrective(arm, sculpt)
    cmds.undo()

    assert cmds.objExists(sculpt)
    assert logic.blend_shapes(arm) == []
    assert _max_distance(_points(arm), before) < 1e-4


def test_start_sculpt_is_one_undo_step(new_scene):
    cmds.undoInfo(state=True)
    arm, _, _, _, _ = _posed_arm()

    sculpt = logic.start_sculpt(arm)
    cmds.undo()

    assert not cmds.objExists(sculpt)
    assert cmds.getAttr(f"{arm}.visibility")


# -- pose reader ------------------------------------------------------------


def test_pose_reader_is_one_at_the_pose_and_zero_at_rest(new_scene):
    _, elbow = _chain()
    cmds.setAttr(f"{elbow}.rotateZ", 90)

    reader = logic.create_pose_reader(elbow, axis="x", cone_angle=90, name="elbow_bend")

    assert cmds.getAttr(logic.reader_output(reader)) == pytest.approx(1.0)
    cmds.setAttr(f"{elbow}.rotateZ", 45)
    assert 0.0 < cmds.getAttr(logic.reader_output(reader)) < 1.0
    cmds.setAttr(f"{elbow}.rotateZ", 0)
    assert cmds.getAttr(logic.reader_output(reader)) == pytest.approx(0.0, abs=1e-6)
    assert logic.pose_readers() == [reader]
    assert logic.reader_joint(reader) == cmds.ls(elbow, long=True)[0]


def test_pose_reader_cone_angle_can_change(new_scene):
    _, elbow = _chain()
    cmds.setAttr(f"{elbow}.rotateZ", 90)
    reader = logic.create_pose_reader(elbow, cone_angle=90)
    cmds.setAttr(f"{elbow}.rotateZ", 30)

    logic.set_cone_angle(reader, 30)

    assert logic.cone_angle(reader) == pytest.approx(30)
    assert cmds.getAttr(logic.reader_output(reader)) == pytest.approx(0.0, abs=1e-6)


def test_pose_reader_drives_the_corrective(new_scene):
    arm, _, shoulder, elbow, rest = _posed_arm()
    sculpt = logic.start_sculpt(arm)
    _sculpt_bump(sculpt)
    wanted = _points(sculpt)
    node, target = logic.create_corrective(arm, sculpt)
    reader = logic.create_pose_reader(elbow, cone_angle=60)

    logic.drive_target(node, target, reader)

    assert logic.target_driver(node, target) == reader
    assert _max_distance(_points(arm), wanted) < 1e-4
    cmds.setAttr(f"{elbow}.rotateZ", 0)
    cmds.setAttr(f"{shoulder}.rotateY", 0)
    assert logic.weight(node, target) == pytest.approx(0.0, abs=1e-6)
    assert _max_distance(_points(arm), rest) < 1e-4
    with pytest.raises(ValueError):
        logic.set_weight(node, target, 0.5)


def test_pose_reader_is_one_undo_step(new_scene):
    cmds.undoInfo(state=True)
    _, elbow = _chain()
    cmds.setAttr(f"{elbow}.rotateZ", 90)

    logic.create_pose_reader(elbow)
    cmds.undo()

    assert logic.pose_readers() == []


# -- target management ------------------------------------------------------


def _with_targets():
    arm, _, _, elbow, _ = _posed_arm()
    node, _ = logic.create_corrective(arm, logic.start_sculpt(arm), name="one")
    logic.create_corrective(arm, logic.start_sculpt(arm), name="two")
    return arm, node


def test_list_and_set_weight(new_scene):
    arm, node = _with_targets()

    assert logic.blend_shapes(arm) == [node]
    assert logic.targets(node) == [(0, "one"), (1, "two")]
    logic.set_weight(node, "two", 0.25)
    assert logic.weight(node, "two") == pytest.approx(0.25)


def test_rename_target(new_scene):
    _, node = _with_targets()

    logic.rename_target(node, "one", "uno")

    assert logic.targets(node) == [(0, "uno"), (1, "two")]
    with pytest.raises(ValueError):
        logic.rename_target(node, "uno", "two")


def test_delete_target(new_scene):
    _, node = _with_targets()

    logic.delete_target(node, "one")

    assert logic.targets(node) == [(1, "two")]


def test_target_edits_are_one_undo_step_each(new_scene):
    cmds.undoInfo(state=True)
    _, node = _with_targets()
    def state():
        return [(index, name, round(cmds.getAttr(f"{node}.weight[{index}]"), 4)) for index, name in logic.targets(node)]

    before = state()

    for edit in (
        lambda: logic.set_weight(node, "one", 0.5),
        lambda: logic.rename_target(node, "one", "uno"),
        lambda: logic.delete_target(node, "one"),
    ):
        edit()
        assert state() != before
        cmds.undo()
        assert state() == before


def test_mesh_from_selection(new_scene):
    arm, _, _, _ = _arm()
    shape = cmds.listRelatives(arm, shapes=True, noIntermediate=True, fullPath=True)[0]

    assert logic.meshes([f"{arm}.vtx[0]", shape]) == [arm]
