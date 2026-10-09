import pytest
from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite import rig


def _params(**overrides):
    params = rig.get("root").defaults()
    params.update(overrides)
    return params


def _world(node):
    return om.MVector(cmds.xform(node, query=True, worldSpace=True, translation=True))


def _cvs(control):
    """World-space positions of every CV of ``control``'s curves."""
    flat = cmds.xform(f"{control}.cv[*]", query=True, worldSpace=True, translation=True)
    return [om.MVector(flat[i : i + 3]) for i in range(0, len(flat), 3)]


def _width(control):
    box = cmds.exactWorldBoundingBox(control)
    return box[3] - box[0]


def _nodes():
    return set(cmds.ls())


def _close(a, b, tolerance=1e-3):
    return all((x - y).length() < tolerance for x, y in zip(a, b))


# -- parameters -------------------------------------------------------------


def test_root_parameters_and_defaults():
    module = rig.get("root")

    assert [p.key for p in module.params] == ["name", "control_size", "color", "parent"]
    assert module.defaults() == {"name": "main", "control_size": 10.0, "color": 17, "parent": ""}
    assert module.name == "Root"


def test_root_needs_no_joints():
    assert not [p for p in rig.get("root").params if "joint" in p.key]


def test_valid_params_have_no_problems(new_scene):
    assert rig.get("root").problems(_params()) == []


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"name": "bad name"}, "Name"),
        ({"name": ""}, "Name"),
        ({"control_size": 0.0}, "Control size"),
        ({"control_size": -1.0}, "Control size"),
        ({"color": 40}, "Color"),
        ({"parent": "nothing"}, "nothing"),
    ],
)
def test_problems(new_scene, overrides, expected):
    problems = rig.get("root").problems(_params(**overrides))

    assert any(expected in p for p in problems), problems


def test_existing_module_with_the_same_name_is_a_problem(new_scene):
    rig.get("root").build(_params())

    problems = rig.get("root").problems(_params())

    assert any("main_root_grp" in p for p in problems), problems


# -- build ------------------------------------------------------------------


def test_build_creates_group_and_controls(new_scene):
    created = rig.get("root").build(_params())

    assert created == {"group": "main_root_grp", "control": "main_root_ctrl", "offset": "main_offset_ctrl"}
    assert all(isinstance(value, str) for value in created.values())
    assert cmds.listRelatives("main_root_grp", parent=True) is None
    assert cmds.listRelatives("main_root_ctrl", parent=True) == ["main_root_grp"]
    assert cmds.listRelatives("main_offset_ctrl", parent=True) == ["main_root_ctrl"]
    assert cmds.ls(cmds.listRelatives("main_root_ctrl", shapes=True), type="nurbsCurve")
    assert cmds.ls(cmds.listRelatives("main_offset_ctrl", shapes=True), type="nurbsCurve")


def test_controls_sit_flat_at_the_origin(new_scene):
    rig.get("root").build(_params())

    origin = om.MVector(0, 0, 0)
    for control in ("main_root_grp", "main_root_ctrl", "main_offset_ctrl"):
        assert _close([_world(control)], [origin])
    for control in ("main_root_ctrl", "main_offset_ctrl"):
        # Lying on the ground: every CV is in the XZ plane, spread over X and Z.
        assert all(abs(cv.y) < 1e-4 for cv in _cvs(control))
        box = cmds.exactWorldBoundingBox(control)
        assert box[3] - box[0] > 1 and box[5] - box[2] > 1


def test_offset_control_is_smaller_than_the_root_control(new_scene):
    rig.get("root").build(_params())

    assert 0 < _width("main_offset_ctrl") < _width("main_root_ctrl")


def test_control_size_scales_the_controls(new_scene):
    rig.get("root").build(_params(name="small", control_size=5.0))
    rig.get("root").build(_params(name="big", control_size=10.0))

    assert abs(_width("big_root_ctrl") - 2 * _width("small_root_ctrl")) < 1e-3
    assert abs(_width("big_offset_ctrl") - 2 * _width("small_offset_ctrl")) < 1e-3
    assert abs(_width("big_root_ctrl") - 20.0) < 0.5  # radius = control size


def test_global_scale_scales_the_root_control_uniformly(new_scene):
    rig.get("root").build(_params())
    control = "main_root_ctrl"

    assert cmds.getAttr(f"{control}.globalScale") == 1.0
    assert cmds.attributeQuery("globalScale", node=control, keyable=True)
    assert cmds.attributeQuery("globalScale", node=control, minimum=True)[0] > 0
    cmds.setAttr(f"{control}.globalScale", 2.5)

    assert cmds.getAttr(f"{control}.scale")[0] == pytest.approx((2.5, 2.5, 2.5))
    for axis in "XYZ":
        assert cmds.getAttr(f"{control}.scale{axis}", lock=True)
        assert not cmds.getAttr(f"{control}.scale{axis}", keyable=True)
        assert not cmds.getAttr(f"{control}.scale{axis}", channelBox=True)


def test_global_scale_cannot_reach_zero(new_scene):
    rig.get("root").build(_params())

    with pytest.raises(RuntimeError):
        cmds.setAttr("main_root_ctrl.globalScale", 0)


def test_things_under_the_offset_control_follow_the_root_control(new_scene):
    created = rig.get("root").build(_params())
    cmds.spaceLocator(name="loc")
    cmds.move(1, 0, 0, "loc")
    cmds.parent("loc", created["offset"])

    cmds.move(5, 0, 3, "main_root_ctrl", relative=True)
    cmds.setAttr("main_root_ctrl.globalScale", 2)

    assert _close([_world("loc")], [om.MVector(7, 0, 3)])


def _color(control):
    """``(overrideEnabled, overrideColor)`` of each curve shape under ``control``."""
    shapes = cmds.listRelatives(control, shapes=True, type="nurbsCurve")
    return {(cmds.getAttr(f"{s}.overrideEnabled"), cmds.getAttr(f"{s}.overrideColor")) for s in shapes}


def test_color_goes_on_both_controls(new_scene):
    rig.get("root").build(_params(color=13))

    assert _color("main_root_ctrl") == {(True, 13)}
    assert _color("main_offset_ctrl") == {(True, 13)}


def test_color_0_leaves_the_controls_maya_default_color(new_scene):
    rig.get("root").build(_params(color=0))

    assert _color("main_root_ctrl") == {(False, 0)}
    assert _color("main_offset_ctrl") == {(False, 0)}


def test_build_goes_under_the_parent(new_scene):
    cmds.group(empty=True, name="rig_grp")

    rig.get("root").build(_params(parent="rig_grp"))

    assert cmds.listRelatives("main_root_grp", parent=True) == ["rig_grp"]


def test_build_keeps_the_selection(new_scene):
    cmds.spaceLocator(name="loc")
    cmds.select("loc")

    rig.get("root").build(_params())

    assert cmds.ls(selection=True) == ["loc"]


def test_build_is_one_undo_step(new_scene):
    cmds.undoInfo(state=True)
    nodes_before = _nodes()

    rig.get("root").build(_params())
    cmds.setAttr("main_root_ctrl.globalScale", 3)
    cmds.undo()
    cmds.undo()

    assert _nodes() == nodes_before


def test_build_with_problems_creates_nothing(new_scene):
    nodes_before = _nodes()

    with pytest.raises(ValueError):
        rig.get("root").build(_params(parent="nothing"))

    assert _nodes() == nodes_before
