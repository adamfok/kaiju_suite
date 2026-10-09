import os

import pytest
from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.core import curves
from kaiju_suite.tools.controlshape_tool import logic, presets


def _cvs(node, space="object"):
    """Every CV of every curve shape under ``node`` (periodic overlaps included)."""
    found = []
    for shape in curves.shapes(node):
        curve = om.MFnNurbsCurve(om.MSelectionList().add(shape).getDagPath(0))
        mspace = om.MSpace.kWorld if space == "world" else om.MSpace.kObject
        found += [[p.x, p.y, p.z] for p in curve.cvPositions(mspace)]
    return found


def _assert_points(got, want):
    assert len(got) == len(want)
    for g, w in zip(got, want):
        assert g == pytest.approx(w, abs=1e-5)


def _ctrl(name="ctrl", preset="square", **kwargs):
    return logic.create_control(name, presets.BUILT_IN[preset], **kwargs)


def _radius(node):
    return max(om.MVector(p).length() for p in _cvs(node))


# -- presets ----------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(presets.BUILT_IN))
def test_every_built_in_preset_builds(new_scene, name):
    ctrl = logic.create_control(name, presets.BUILT_IN[name])

    assert curves.shapes(ctrl)
    assert 0.9 <= _radius(ctrl) <= 1.75  # about one unit: a cube's corners are at sqrt(3)


def test_there_are_plenty_of_built_in_presets():
    assert {"circle", "square", "cube", "sphere", "arrow", "cross", "locator"} <= set(presets.BUILT_IN)


def test_library_lists_built_in_then_saved_presets(new_scene, tmp_path):
    ctrl = _ctrl()
    logic.save_preset(ctrl, "my_shape", str(tmp_path))

    names = logic.preset_names(str(tmp_path))

    assert names[: len(presets.BUILT_IN)] == list(presets.BUILT_IN)
    assert names[-1] == "my_shape"


def test_a_saved_preset_loads_back_without_colors(new_scene, tmp_path):
    ctrl = _ctrl(preset="cube", color=13)
    cmds.setAttr(f"{ctrl}.translate", 4, 5, 6)

    path = logic.save_preset(ctrl, "box", str(tmp_path))
    loaded = logic.load_preset("box", str(tmp_path))

    assert os.path.basename(path) == "box.json"
    assert [len(r["cvs"]) for r in loaded] == [len(r["cvs"]) for r in presets.BUILT_IN["cube"]]
    assert all("overrideColor" not in record for record in loaded)
    other = logic.create_control("other", loaded)
    _assert_points(_cvs(other), _cvs(ctrl))


def test_saving_refuses_bad_or_taken_names(new_scene, tmp_path):
    ctrl = _ctrl()
    logic.save_preset(ctrl, "mine", str(tmp_path))

    for name in ("", "a/b", "circle", "mine"):
        with pytest.raises(ValueError):
            logic.save_preset(ctrl, name, str(tmp_path))
    logic.save_preset(ctrl, "mine", str(tmp_path), overwrite=True)


def test_saving_needs_curve_shapes(new_scene, tmp_path):
    with pytest.raises(ValueError):
        logic.save_preset(cmds.createNode("transform", name="empty"), "x", str(tmp_path))


def test_delete_preset(new_scene, tmp_path):
    logic.save_preset(_ctrl(), "mine", str(tmp_path))

    logic.delete_preset("mine", str(tmp_path))

    assert "mine" not in logic.preset_names(str(tmp_path))
    with pytest.raises(ValueError):
        logic.delete_preset("circle", str(tmp_path))


def test_load_preset_refuses_an_unknown_name(tmp_path):
    with pytest.raises(LookupError):
        logic.load_preset("nope", str(tmp_path))


# -- creating ---------------------------------------------------------------


def test_create_control_with_size_and_color(new_scene):
    ctrl = _ctrl("arm_ctrl", size=3, color=17)

    assert cmds.ls(ctrl) == ["arm_ctrl"]
    assert cmds.listRelatives(ctrl, shapes=True) == ["arm_ctrlShape"]
    assert _radius(ctrl) == pytest.approx(3 * _radius(_ctrl("unit")))
    shape = curves.shapes(ctrl)[0]
    assert cmds.getAttr(f"{shape}.overrideEnabled") and cmds.getAttr(f"{shape}.overrideColor") == 17


def test_create_control_at_a_node(new_scene):
    target = cmds.createNode("transform", name="target")
    cmds.xform(target, translation=(1, 2, 3), rotation=(0, 90, 0))

    ctrl = _ctrl(at=target)

    assert cmds.xform(ctrl, query=True, worldSpace=True, matrix=True) == pytest.approx(
        cmds.xform(target, query=True, worldSpace=True, matrix=True)
    )
    assert cmds.listRelatives(ctrl, parent=True) is None


def test_create_control_picks_a_free_name(new_scene):
    _ctrl("ctrl")

    assert cmds.ls(_ctrl("ctrl")) == ["ctrl1"]


def test_create_control_is_one_undo_step(new_scene):
    cmds.undoInfo(state=True)
    _ctrl("ctrl")
    cmds.undo()

    assert not cmds.objExists("ctrl")


# -- replacing --------------------------------------------------------------


def test_replace_keeps_color_and_size(new_scene):
    ctrl = _ctrl(preset="square", size=4, color=6)
    radius = _radius(ctrl)

    logic.replace_shapes([ctrl], presets.BUILT_IN["circle"])

    shapes = curves.shapes(ctrl)
    assert len(shapes) == 1 and cmds.getAttr(f"{shapes[0]}.form") == 2
    assert cmds.getAttr(f"{shapes[0]}.overrideColor") == 6
    assert _radius(ctrl) == pytest.approx(radius)


def test_replace_can_use_the_presets_size(new_scene):
    ctrl = _ctrl(preset="square", size=4)

    logic.replace_shapes([ctrl], presets.BUILT_IN["circle"], keep_size=False)

    assert _radius(ctrl) == pytest.approx(_radius(_ctrl("reference", preset="circle")))


def test_replace_goes_around_the_pivot_and_leaves_other_shapes(new_scene):
    ctrl = _ctrl()
    cmds.xform(ctrl, objectSpace=True, pivots=(0, 2, 0))
    locator = cmds.createNode("locator", parent=ctrl)

    logic.replace_shapes([ctrl], presets.BUILT_IN["circle"], keep_size=False)

    points = _cvs(ctrl)
    assert all(p[1] == pytest.approx(2) for p in points)
    assert cmds.objExists(locator)


def test_replace_is_one_undo_step(new_scene):
    cmds.undoInfo(state=True)
    ctrl = _ctrl()
    before = _cvs(ctrl)

    logic.replace_shapes([ctrl], presets.BUILT_IN["sphere"])
    cmds.undo()

    _assert_points(_cvs(ctrl), before)


# -- moving CVs -------------------------------------------------------------


def test_rotate_shapes_turns_cvs_around_the_pivot(new_scene):
    ctrl = _ctrl()
    cmds.setAttr(f"{ctrl}.translateX", 10)
    cmds.xform(ctrl, objectSpace=True, pivots=(1, 0, 0))
    before = _cvs(ctrl)

    logic.rotate_shapes([ctrl], (0, 90, 0))

    # 90 degrees about Y: (x, y, z) -> (z, y, -x), around the pivot at x = 1.
    _assert_points(_cvs(ctrl), [[1 + z, y, -(x - 1)] for x, y, z in before])
    assert cmds.getAttr(f"{ctrl}.translateX") == 10
    assert cmds.getAttr(f"{ctrl}.rotate")[0] == (0, 0, 0)


def test_scale_shapes(new_scene):
    ctrl = _ctrl(preset="circle")
    before = _cvs(ctrl)

    logic.scale_shapes([ctrl], 2)

    _assert_points(_cvs(ctrl), [[2 * v for v in p] for p in before])


def test_scale_shapes_per_axis(new_scene):
    ctrl = _ctrl()
    before = _cvs(ctrl)

    logic.scale_shapes([ctrl], (1, 3, 0.5))

    _assert_points(_cvs(ctrl), [[x, 3 * y, 0.5 * z] for x, y, z in before])


def test_translate_shapes(new_scene):
    ctrl = _ctrl(preset="circle")
    before = _cvs(ctrl)

    logic.translate_shapes([ctrl], (0, 1, -2))

    _assert_points(_cvs(ctrl), [[x, y + 1, z - 2] for x, y, z in before])


def test_cv_edits_take_shapes_and_are_one_undo_step_each(new_scene):
    cmds.undoInfo(state=True)
    ctrl = _ctrl(preset="sphere")
    shape = curves.shapes(ctrl)[0]
    before = _cvs(ctrl)

    for edit in (
        lambda: logic.rotate_shapes([shape], (90, 0, 0)),
        lambda: logic.scale_shapes([shape], 2),
        lambda: logic.translate_shapes([shape], (1, 0, 0)),
    ):
        edit()
        assert _cvs(ctrl) != before
        cmds.undo()
        _assert_points(_cvs(ctrl), before)


# -- mirroring and copying --------------------------------------------------


def test_mirror_shapes_onto_the_opposite_control(new_scene):
    left = _ctrl("L_hand_ctrl", preset="arrow", color=6)
    right = _ctrl("R_hand_ctrl", preset="circle", color=13)
    cmds.xform(left, translation=(5, 2, 0), rotation=(0, 30, 10))
    cmds.xform(right, translation=(-5, 2, 0), rotation=(0, -30, -10))
    logic.translate_shapes([left], (0, 1, 0.5))

    result = logic.mirror_shapes([left])

    assert result.changed == [cmds.ls(right, long=True)[0]]
    _assert_points(_cvs(right, "world"), [[-x, y, z] for x, y, z in _cvs(left, "world")])
    assert cmds.getAttr(f"{curves.shapes(right)[0]}.overrideColor") == 13


def test_mirror_shapes_reports_controls_without_an_opposite(new_scene):
    ctrl = _ctrl("spine_ctrl")
    lonely = _ctrl("L_lonely_ctrl")

    result = logic.mirror_shapes([ctrl, lonely])

    assert result.changed == []
    assert result.skipped == ["spine_ctrl: no side in its name", "L_lonely_ctrl: no R_lonely_ctrl in the scene"]


def test_copy_shapes_from_the_first_control(new_scene):
    source = _ctrl("a", preset="cube", size=2, color=6)
    targets = [_ctrl("b", preset="circle", color=13), _ctrl("c", color=14)]

    logic.copy_shapes(source, targets)

    for target, color in zip(targets, (13, 14)):
        _assert_points(_cvs(target), _cvs(source))
        assert cmds.getAttr(f"{curves.shapes(target)[0]}.overrideColor") == color


def test_mirror_and_copy_are_one_undo_step(new_scene):
    cmds.undoInfo(state=True)
    left, right = _ctrl("L_ctrl", preset="cube"), _ctrl("R_ctrl")
    before = _cvs(right)

    for edit in (lambda: logic.mirror_shapes([left]), lambda: logic.copy_shapes(left, [right])):
        edit()
        cmds.undo()
        _assert_points(_cvs(right), before)


# -- display ----------------------------------------------------------------


def test_set_color_and_line_width(new_scene):
    ctrl = _ctrl(preset="sphere")

    logic.set_color([ctrl], 17)
    logic.set_line_width([ctrl], 2.5)

    for shape in curves.shapes(ctrl):
        assert cmds.getAttr(f"{shape}.overrideEnabled") and cmds.getAttr(f"{shape}.overrideColor") == 17
        assert not cmds.getAttr(f"{shape}.overrideRGBColors")
        assert cmds.getAttr(f"{shape}.lineWidth") == 2.5

    logic.set_color([ctrl], 0)

    assert not any(cmds.getAttr(f"{shape}.overrideEnabled") for shape in curves.shapes(ctrl))


def test_controls_takes_controls_and_curve_shapes(new_scene):
    a, b = _ctrl("a"), _ctrl("b")
    joint = cmds.createNode("joint")

    assert logic.controls([curves.shapes(a)[0], b, joint, a]) == cmds.ls([a, b], long=True)


def test_replace_and_copy_give_a_bare_joint_its_first_shape(new_scene):
    joints = [cmds.createNode("joint", name=f"jnt{i}") for i in range(2)]
    source = _ctrl("source", preset="cube")

    logic.replace_shapes([joints[0]], presets.BUILT_IN["circle"])
    logic.copy_shapes(source, [joints[1]])

    assert cmds.listRelatives(joints[0], shapes=True) == ["jnt0Shape"]
    _assert_points(_cvs(joints[1]), _cvs(source))


def test_transforms_takes_any_transform(new_scene):
    a = _ctrl("a")
    joint = cmds.createNode("joint", name="jnt")

    assert logic.transforms([curves.shapes(a)[0], joint, a]) == cmds.ls([a, joint], long=True)


# -- previews ---------------------------------------------------------------


def test_outline_of_a_circle_is_round():
    (line,) = presets.outline(presets.BUILT_IN["circle"])

    assert len(line) > 16
    for x, y, z in line:
        assert (x * x + z * z) ** 0.5 == pytest.approx(1, abs=0.01)
        assert y == 0


def test_outline_of_a_linear_curve_is_its_cvs():
    (line,) = presets.outline(presets.BUILT_IN["square"])

    assert line == presets.BUILT_IN["square"][0]["cvs"]


def test_outline_of_an_open_cubic_curve_ends_on_its_end_cvs(new_scene):
    curve = cmds.curve(degree=3, point=[(0, 0, 0), (1, 1, 0), (2, -1, 0), (3, 0, 0), (4, 2, 0)])
    record = curves.record(curves.shapes(curve)[0])

    (line,) = presets.outline([record])

    assert line[0] == pytest.approx([0, 0, 0])
    assert line[-1] == pytest.approx([4, 2, 0])
