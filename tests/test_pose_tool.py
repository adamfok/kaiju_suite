import pytest
from maya import cmds

from kaiju_suite.tools.pose_tool import logic

_TR = ("translateX", "translateY", "translateZ", "rotateX", "rotateY", "rotateZ")


def _ctrl(name, x=0.0, parent=None):
    """A control under an offset group at ``(x, 0, 0)``, world-aligned."""
    group = cmds.createNode("transform", name=f"{name}_grp", parent=parent)
    cmds.setAttr(f"{group}.translateX", x)
    return cmds.ls(cmds.createNode("transform", name=name, parent=group), long=True)[0]


def _set(node, values):
    for attr, value in zip(_TR, values):
        cmds.setAttr(f"{node}.{attr}", value)


def _get(node):
    return [cmds.getAttr(f"{node}.{attr}") for attr in _TR]


def _world(node):
    return cmds.xform(node, query=True, worldSpace=True, translation=True)


def _mirrored(point):
    return [-point[0], point[1], point[2]]


def _arm(behavior=True):
    """A shoulder-elbow-wrist chain on the left; the right one mirrored from it."""
    cmds.select(clear=True)
    shoulder = cmds.joint(name="L_shoulder", position=(2, 10, 0))
    cmds.joint(name="L_elbow", position=(5, 10, -1))
    cmds.joint(name="L_wrist", position=(8, 10, 0))
    cmds.joint(shoulder, edit=True, orientJoint="xyz", secondaryAxisOrient="yup", children=True)
    cmds.mirrorJoint(shoulder, mirrorYZ=True, mirrorBehavior=behavior, searchReplace=("L_", "R_"))
    return {s: cmds.ls(f"{s}_shoulder", long=True)[0] for s in ("L", "R")}


# -- names ------------------------------------------------------------------


def test_opposite_finds_the_other_side(new_scene):
    left, right = _ctrl("L_arm_ctrl", 5), _ctrl("R_arm_ctrl", -5)

    assert logic.opposite(left) == right
    assert logic.opposite(right) == left


def test_opposite_is_none_for_a_centre_or_unmatched_node(new_scene):
    spine = _ctrl("spine_ctrl")
    lonely = _ctrl("L_lonely_ctrl")

    assert logic.opposite(spine) is None
    assert logic.opposite(lonely) is None


def test_select_opposite(new_scene):
    left, right = _ctrl("L_arm_ctrl", 5), _ctrl("R_arm_ctrl", -5)
    spine = _ctrl("spine_ctrl")

    assert logic.opposites([left, spine, right]) == [right, left]


# -- mirroring --------------------------------------------------------------


def test_mirror_world_aligned_controls(new_scene):
    left, right = _ctrl("L_arm_ctrl", 5), _ctrl("R_arm_ctrl", -5)
    _set(left, (1, 2, 3, 10, 20, 30))

    logic.mirror([left])

    assert _get(right) == pytest.approx([-1, 2, 3, 10, -20, -30])
    assert _get(left) == pytest.approx([1, 2, 3, 10, 20, 30])


@pytest.mark.parametrize("behavior", [True, False])
def test_mirrored_joints_end_up_mirrored_in_the_world(new_scene, behavior):
    shoulders = _arm(behavior)
    _set(shoulders["L"], (0.5, -0.2, 0.3, 15, -40, 25))
    elbow = cmds.ls("L_elbow", long=True)[0]
    cmds.setAttr(f"{elbow}.rotateZ", 35)

    logic.mirror([shoulders["L"], elbow])

    for joint in ("shoulder", "elbow", "wrist"):
        assert _world(f"R_{joint}") == pytest.approx(_mirrored(_world(f"L_{joint}")), abs=1e-4)


def test_behavior_mirrored_joints_keep_their_rotation(new_scene):
    shoulders = _arm(behavior=True)
    _set(shoulders["L"], (0, 0, 0, 15, -40, 25))

    logic.mirror([shoulders["L"]])

    assert _get(shoulders["R"])[3:] == pytest.approx([15, -40, 25], abs=1e-4)


def test_mirror_under_rotated_parents(new_scene):
    left, right = _ctrl("L_ctrl", 5), _ctrl("R_ctrl", -5)
    cmds.setAttr("L_ctrl_grp.rotate", 20, 35, -10)
    cmds.setAttr("R_ctrl_grp.rotate", 20, -35, 10)  # its mirror image
    cmds.setAttr(f"{cmds.createNode('transform', name='L_ctrl_tip', parent=left)}.translate", 1, 2, 3)
    cmds.setAttr(f"{cmds.createNode('transform', name='R_ctrl_tip', parent=right)}.translate", -1, 2, 3)
    assert _world("R_ctrl_tip") == pytest.approx(_mirrored(_world("L_ctrl_tip")), abs=1e-4)
    _set(left, (0.4, 1, -2, 30, 10, -50))

    logic.mirror([left])

    assert _world("R_ctrl_tip") == pytest.approx(_mirrored(_world("L_ctrl_tip")), abs=1e-4)


def test_a_centre_control_mirrors_onto_itself(new_scene):
    spine = _ctrl("spine_ctrl")
    _set(spine, (1, 2, 3, 10, 20, 30))

    logic.mirror([spine])

    assert _get(spine) == pytest.approx([-1, 2, 3, 10, -20, -30])


def test_mirror_copies_scale_and_custom_attributes(new_scene):
    left, right = _ctrl("L_ctrl", 5), _ctrl("R_ctrl", -5)
    for node in (left, right):
        cmds.addAttr(node, longName="ikFk", minValue=0, maxValue=1, keyable=True)
    cmds.setAttr(f"{left}.scaleY", 2)
    cmds.setAttr(f"{left}.ikFk", 0.75)

    logic.mirror([left])

    assert cmds.getAttr(f"{right}.scaleY") == 2
    assert cmds.getAttr(f"{right}.ikFk") == 0.75


def test_mirror_skips_locked_and_driven_attributes(new_scene):
    left, right = _ctrl("L_ctrl", 5), _ctrl("R_ctrl", -5)
    _set(left, (1, 2, 3, 0, 0, 0))
    cmds.setAttr(f"{right}.translateY", lock=True)
    driver = cmds.createNode("transform", name="driver")
    cmds.setAttr(f"{driver}.translateZ", 7)
    cmds.connectAttr(f"{driver}.translateZ", f"{right}.translateZ")

    result = logic.mirror([left])

    assert _get(right)[:3] == pytest.approx([-1, 0, 7])
    assert "R_ctrl.translateY" in result.skipped[0] and "R_ctrl.translateZ" in result.skipped[1]


def test_mirror_reports_nodes_without_an_opposite(new_scene):
    lonely = _ctrl("L_lonely_ctrl")

    result = logic.mirror([lonely])

    assert result.changed == []
    assert result.skipped == ["L_lonely_ctrl: no R_lonely_ctrl in the scene"]


def test_mirror_refuses_both_sides_at_once(new_scene):
    left, right = _ctrl("L_ctrl", 5), _ctrl("R_ctrl", -5)
    _set(left, (1, 0, 0, 0, 0, 0))

    with pytest.raises(ValueError) as info:
        logic.mirror([left, right])

    assert "L_ctrl" in str(info.value) and "R_ctrl" in str(info.value)
    assert _get(right)[0] == 0


def test_mirror_is_one_undo_step(new_scene):
    cmds.undoInfo(state=True)
    left, right = _ctrl("L_ctrl", 5), _ctrl("R_ctrl", -5)
    _set(left, (1, 2, 3, 10, 20, 30))
    _set(right, (4, 5, 6, 0, 0, 0))

    logic.mirror([left])
    cmds.undo()

    assert _get(right) == pytest.approx([4, 5, 6, 0, 0, 0])


# -- flipping ---------------------------------------------------------------


def test_flip_swaps_the_sides(new_scene):
    left, right = _ctrl("L_ctrl", 5), _ctrl("R_ctrl", -5)
    _set(left, (1, 2, 3, 10, 20, 30))
    _set(right, (-4, 5, 6, 40, 50, 60))

    logic.flip([left])

    assert _get(left) == pytest.approx([4, 5, 6, 40, -50, -60])
    assert _get(right) == pytest.approx([-1, 2, 3, 10, -20, -30])


@pytest.mark.parametrize("behavior", [True, False])
def test_flipping_posed_chains_swaps_them_in_the_world(new_scene, behavior):
    _arm(behavior)
    _set("L_shoulder", (2, 10, 0, 15, -40, 25))
    cmds.setAttr("L_elbow.rotateZ", 35)
    _set("R_shoulder", (-2, 10, 0, -30, 10, 5))
    cmds.setAttr("R_elbow.rotateY", -20)
    before = {name: _world(name) for side in "LR" for name in (f"{side}_elbow", f"{side}_wrist")}

    logic.flip(["L_shoulder", "L_elbow", "L_wrist"])

    for joint in ("elbow", "wrist"):
        assert _world(f"R_{joint}") == pytest.approx(_mirrored(before[f"L_{joint}"]), abs=1e-4)
        assert _world(f"L_{joint}") == pytest.approx(_mirrored(before[f"R_{joint}"]), abs=1e-4)


def test_flip_with_both_sides_selected_flips_once(new_scene):
    left, right = _ctrl("L_ctrl", 5), _ctrl("R_ctrl", -5)
    _set(left, (1, 0, 0, 0, 0, 0))

    logic.flip([left, right])

    assert _get(left)[0] == pytest.approx(0)
    assert _get(right)[0] == pytest.approx(-1)


def test_flip_mirrors_a_centre_control_in_place(new_scene):
    spine = _ctrl("spine_ctrl")
    _set(spine, (1, 2, 3, 10, 20, 30))

    logic.flip([spine])

    assert _get(spine) == pytest.approx([-1, 2, 3, 10, -20, -30])


# -- reset ------------------------------------------------------------------


def test_reset_sets_keyable_attributes_to_their_defaults(new_scene):
    ctrl = _ctrl("ctrl")
    cmds.addAttr(ctrl, longName="ikFk", defaultValue=1, minValue=0, maxValue=1, keyable=True)
    _set(ctrl, (1, 2, 3, 10, 20, 30))
    cmds.setAttr(f"{ctrl}.scaleX", 3)
    cmds.setAttr(f"{ctrl}.ikFk", 0.2)
    cmds.setAttr(f"{ctrl}.rotateZ", lock=True)

    logic.reset([ctrl])

    assert _get(ctrl) == pytest.approx([0, 0, 0, 0, 0, 30])
    assert cmds.getAttr(f"{ctrl}.scaleX") == 1
    assert cmds.getAttr(f"{ctrl}.ikFk") == 1


def test_reset_is_one_undo_step(new_scene):
    cmds.undoInfo(state=True)
    ctrl = _ctrl("ctrl")
    _set(ctrl, (1, 2, 3, 10, 20, 30))

    logic.reset([ctrl])
    cmds.undo()

    assert _get(ctrl) == pytest.approx([1, 2, 3, 10, 20, 30])
