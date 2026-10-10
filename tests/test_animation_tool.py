import pytest
from maya import cmds

from kaiju_suite.tools.animation_tool import logic

_TR = ("translateX", "translateY", "translateZ", "rotateX", "rotateY", "rotateZ")


def _ctrl(name, x=0.0, parent=None):
    """A control under an offset group at ``(x, 0, 0)``, world-aligned."""
    group = cmds.createNode("transform", name=f"{name}_grp", parent=parent)
    cmds.setAttr(f"{group}.translateX", x)
    return cmds.ls(cmds.createNode("transform", name=name, parent=group), long=True)[0]


def _key(node, frame, values, attrs=_TR):
    for attr, value in zip(attrs, values):
        cmds.setKeyframe(node, attribute=attr, time=frame, value=value)


def _times(node, attr):
    return cmds.keyframe(f"{node}.{attr}", query=True, timeChange=True) or []


def _values(node, attr):
    return cmds.keyframe(f"{node}.{attr}", query=True, valueChange=True) or []


def _at(node, frame, attrs=_TR):
    return [cmds.getAttr(f"{node}.{attr}", time=frame) for attr in attrs]


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


# -- mirror -----------------------------------------------------------------


def test_mirror_copies_keys_onto_the_opposite_mirrored(new_scene):
    left, right = _ctrl("L_arm_ctrl", 5), _ctrl("R_arm_ctrl", -5)
    _key(left, 1, (1, 2, 3, 10, 20, 30))
    _key(left, 12, (4, 5, 6, 40, 50, 60))

    result = logic.mirror([left])

    assert result.changed == [right]
    assert result.skipped == []
    for attr in _TR:
        assert _times(right, attr) == [1, 12]
    assert _at(right, 1) == pytest.approx([-1, 2, 3, 10, -20, -30])
    assert _at(right, 12) == pytest.approx([-4, 5, 6, 40, -50, -60])
    # The source is left alone.
    assert _at(left, 12) == pytest.approx([4, 5, 6, 40, 50, 60])


def test_mirror_keeps_tangents_and_infinity(new_scene):
    left, right = _ctrl("L_ctrl", 5), _ctrl("R_ctrl", -5)
    _key(left, 1, (0,), ("translateX",))
    _key(left, 10, (5,), ("translateX",))
    _key(left, 20, (2,), ("translateX",))
    plug = f"{left}.translateX"
    cmds.keyTangent(plug, time=(10, 10), inTangentType="linear", outTangentType="step")
    cmds.keyTangent(plug, time=(1, 1), outAngle=30, lock=False)
    cmds.setInfinity(plug, postInfinite="cycle")
    in_between = cmds.getAttr(plug, time=4.5)

    logic.mirror([left])

    target = f"{right}.translateX"
    assert cmds.keyTangent(target, query=True, time=(10, 10), inTangentType=True) == ["linear"]
    assert cmds.keyTangent(target, query=True, time=(10, 10), outTangentType=True) == ["step"]
    assert cmds.keyTangent(target, query=True, time=(1, 1), outAngle=True)[0] == pytest.approx(-30)
    assert cmds.setInfinity(target, query=True, postInfinite=True) == ["cycle"]
    assert cmds.getAttr(target, time=4.5) == pytest.approx(-in_between)


def test_mirror_replaces_the_opposites_keys(new_scene):
    left, right = _ctrl("L_ctrl", 5), _ctrl("R_ctrl", -5)
    _key(left, 1, (1,), ("translateX",))
    _key(left, 5, (2,), ("translateX",))
    _key(right, 3, (9, 9), ("translateX", "translateY"))
    _key(right, 30, (8, 8), ("translateX", "translateY"))

    logic.mirror([left])

    assert _times(right, "translateX") == [1, 5]
    assert _values(right, "translateX") == pytest.approx([-1, -2])
    # Keys the source doesn't have on an attribute are removed, leaving the
    # source's (mirrored) value.
    assert _times(right, "translateY") == []
    assert cmds.getAttr(f"{right}.translateY") == 0


def test_mirror_with_a_frame_offset(new_scene):
    left, right = _ctrl("L_ctrl", 5), _ctrl("R_ctrl", -5)
    _key(left, 1, (1,), ("translateX",))
    _key(left, 13, (3,), ("translateX",))

    logic.mirror([left], offset=12)

    assert _times(right, "translateX") == [13, 25]
    assert _values(right, "translateX") == pytest.approx([-1, -3])


def test_a_centre_control_mirrors_onto_itself(new_scene):
    spine = _ctrl("spine_ctrl")
    _key(spine, 1, (1, 2, 3, 10, 20, 30))
    _key(spine, 8, (2, 0, 0, 0, 5, 0))

    result = logic.mirror([spine])

    assert result.changed == [spine]
    assert _at(spine, 1) == pytest.approx([-1, 2, 3, 10, -20, -30])
    assert _at(spine, 8) == pytest.approx([-2, 0, 0, 0, -5, 0])


def test_mirror_copies_scale_and_custom_attributes(new_scene):
    left, right = _ctrl("L_ctrl", 5), _ctrl("R_ctrl", -5)
    for node in (left, right):
        cmds.addAttr(node, longName="ikFk", minValue=0, maxValue=1, keyable=True)
    _key(left, 1, (2, 0.25), ("scaleY", "ikFk"))
    _key(left, 9, (3, 0.75), ("scaleY", "ikFk"))

    logic.mirror([left])

    assert _values(right, "scaleY") == pytest.approx([2, 3])
    assert _values(right, "ikFk") == pytest.approx([0.25, 0.75])


@pytest.mark.parametrize("behavior", [True, False])
def test_mirrored_joint_animation_is_mirrored_in_the_world(new_scene, behavior):
    shoulders = _arm(behavior)
    elbow = cmds.ls("L_elbow", long=True)[0]
    _key(shoulders["L"], 1, (15, -40, 25), _TR[3:])
    _key(shoulders["L"], 10, (-20, 30, 5), _TR[3:])
    _key(elbow, 1, (0,), ("rotateZ",))
    _key(elbow, 10, (45,), ("rotateZ",))

    logic.mirror([shoulders["L"], elbow])

    for frame in (1, 5, 10):
        cmds.currentTime(frame)
        for joint in ("elbow", "wrist"):
            assert _world(f"R_{joint}") == pytest.approx(_mirrored(_world(f"L_{joint}")), abs=1e-3)


def test_mirror_under_rotated_parents(new_scene):
    left, right = _ctrl("L_ctrl", 5), _ctrl("R_ctrl", -5)
    cmds.setAttr("L_ctrl_grp.rotate", 20, 35, -10)
    cmds.setAttr("R_ctrl_grp.rotate", 20, -35, 10)  # its mirror image
    cmds.setAttr(f"{cmds.createNode('transform', name='L_ctrl_tip', parent=left)}.translate", 1, 2, 3)
    cmds.setAttr(f"{cmds.createNode('transform', name='R_ctrl_tip', parent=right)}.translate", -1, 2, 3)
    _key(left, 1, (0.4, 1, -2, 30, 10, -50))
    _key(left, 10, (-1, 0, 2, -10, 60, 20))

    result = logic.mirror([left])

    assert result.skipped == []
    for frame in (1, 10):
        cmds.currentTime(frame)
        assert _world("R_ctrl_tip") == pytest.approx(_mirrored(_world("L_ctrl_tip")), abs=1e-3)


def test_mirror_skips_locked_and_connected_attributes(new_scene):
    left, right = _ctrl("L_ctrl", 5), _ctrl("R_ctrl", -5)
    _key(left, 1, (1, 2, 3), _TR[:3])
    _key(left, 5, (4, 5, 6), _TR[:3])
    cmds.setAttr(f"{right}.translateY", lock=True)
    driver = cmds.createNode("transform", name="driver")
    cmds.connectAttr(f"{driver}.translateZ", f"{right}.translateZ")

    result = logic.mirror([left])

    assert _values(right, "translateX") == pytest.approx([-1, -4])
    assert _times(right, "translateY") == []
    assert cmds.listConnections(f"{right}.translateZ", source=True) == ["driver"]
    assert any("R_ctrl.translateY (locked)" in s for s in result.skipped)
    assert any("R_ctrl.translateZ (connected)" in s for s in result.skipped)


def test_mirror_reports_nodes_without_an_opposite(new_scene):
    lonely = _ctrl("L_lonely_ctrl")
    _key(lonely, 1, (1,), ("translateX",))

    result = logic.mirror([lonely])

    assert result.changed == []
    assert result.skipped == ["L_lonely_ctrl: no R_lonely_ctrl in the scene"]


def test_mirror_refuses_both_sides_at_once(new_scene):
    left, right = _ctrl("L_ctrl", 5), _ctrl("R_ctrl", -5)
    _key(left, 1, (1,), ("translateX",))

    with pytest.raises(ValueError) as info:
        logic.mirror([left, right])

    assert "L_ctrl" in str(info.value) and "R_ctrl" in str(info.value)
    assert _times(right, "translateX") == []


def test_mirror_is_one_undo_step(new_scene):
    cmds.undoInfo(state=True)
    left, right = _ctrl("L_ctrl", 5), _ctrl("R_ctrl", -5)
    _key(left, 1, (1, 2, 3, 10, 20, 30))
    _key(left, 10, (2, 3, 4, 11, 21, 31))
    _key(right, 4, (7,), ("translateX",))
    _key(right, 8, (9,), ("translateX",))

    logic.mirror([left])
    cmds.undo()

    assert _times(right, "translateX") == [4, 8]
    assert _values(right, "translateX") == pytest.approx([7, 9])
    assert _times(right, "rotateY") == []


# -- flip -------------------------------------------------------------------


def test_flip_swaps_the_animation_of_both_sides(new_scene):
    left, right = _ctrl("L_ctrl", 5), _ctrl("R_ctrl", -5)
    _key(left, 1, (1, 2, 3, 10, 20, 30))
    _key(left, 10, (2, 2, 2, 0, 0, 0))
    _key(right, 5, (-4, 5, 6, 40, 50, 60), _TR)
    _key(right, 15, (-1, 1, 1, 1, 1, 1), _TR)

    result = logic.flip([left])

    assert sorted(result.changed) == sorted([left, right])
    assert _times(left, "translateX") == [5, 15]
    assert _at(left, 5) == pytest.approx([4, 5, 6, 40, -50, -60])
    assert _times(right, "translateX") == [1, 10]
    assert _at(right, 1) == pytest.approx([-1, 2, 3, 10, -20, -30])


def test_flip_with_both_sides_selected_flips_once(new_scene):
    left, right = _ctrl("L_ctrl", 5), _ctrl("R_ctrl", -5)
    _key(left, 1, (1,), ("translateX",))
    _key(left, 5, (3,), ("translateX",))

    logic.flip([left, right])

    assert _times(left, "translateX") == []
    assert _values(right, "translateX") == pytest.approx([-1, -3])


def test_flip_with_a_frame_offset(new_scene):
    left, right = _ctrl("L_ctrl", 5), _ctrl("R_ctrl", -5)
    _key(left, 1, (1,), ("translateX",))
    _key(right, 1, (-2,), ("translateX",))

    logic.flip([left], offset=6)

    assert _times(right, "translateX") == [7]
    assert _values(right, "translateX") == pytest.approx([-1])
    assert _times(left, "translateX") == [7]
    assert _values(left, "translateX") == pytest.approx([2])


def test_flip_mirrors_a_centre_control_in_place(new_scene):
    spine = _ctrl("spine_ctrl")
    _key(spine, 1, (1, 2, 3, 10, 20, 30))

    logic.flip([spine])

    assert _at(spine, 1) == pytest.approx([-1, 2, 3, 10, -20, -30])


def test_flip_is_one_undo_step(new_scene):
    cmds.undoInfo(state=True)
    left, right = _ctrl("L_ctrl", 5), _ctrl("R_ctrl", -5)
    _key(left, 1, (1,), ("translateX",))
    _key(right, 3, (-5,), ("translateX",))

    logic.flip([left])
    cmds.undo()

    assert _times(left, "translateX") == [1]
    assert _values(left, "translateX") == pytest.approx([1])
    assert _times(right, "translateX") == [3]
    assert _values(right, "translateX") == pytest.approx([-5])
