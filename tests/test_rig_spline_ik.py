import pytest
from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite import rig


def _joint(name, parent=None, translate=(0, 0, 0)):
    node = cmds.createNode("joint", name=name, parent=parent, skipSelect=True)
    cmds.setAttr(f"{node}.translate", *translate)
    return node


@pytest.fixture
def spine(new_scene):
    """hips > spine1 > spine2 > spine3 > chest, going up +Y, arched toward +Z."""
    _joint("hips", translate=(0, 10, 0))
    _joint("spine1", "hips", translate=(0, 2, 0.5))
    _joint("spine2", "spine1", translate=(0, 2, 0.3))
    _joint("spine3", "spine2", translate=(0, 2, -0.3))
    _joint("chest", "spine3", translate=(0, 2, -0.5))
    return ("hips", "spine1", "spine2", "spine3", "chest")


@pytest.fixture
def user_curve(spine):
    """A straight curve along the spine, a little in front of it."""
    return cmds.curve(name="my_crv", degree=3, editPoint=[(0, 10, 1), (0, 14, 1), (0, 18, 1)])


def _params(**overrides):
    params = rig.get("spline_ik").defaults()
    params.update(name="body", start_joint="hips", end_joint="chest")
    params.update(overrides)
    return params


def _world(node):
    return om.MVector(cmds.xform(node, query=True, worldSpace=True, translation=True))


def _positions(nodes):
    return [_world(n) for n in nodes]


def _axis(node, row):
    """Row ``row`` of ``node``'s world matrix: its X (0), Y (1) or Z (2) axis."""
    matrix = cmds.xform(node, query=True, worldSpace=True, matrix=True)
    return om.MVector(matrix[row * 4 : row * 4 + 3]).normal()


def _nodes():
    """Every node, except the solver nodes Maya makes once per scene with the
    first IK handle and keeps after an undo."""
    return set(cmds.ls()) - set(cmds.ls(type="ikSolver"))


def _close(a, b, tolerance=1e-3):
    return all((x - y).length() < tolerance for x, y in zip(a, b))


# -- parameters -------------------------------------------------------------


def test_spline_parameters_and_defaults():
    module = rig.get("spline_ik")

    assert [p.key for p in module.params] == [
        "name",
        "start_joint",
        "end_joint",
        "curve",
        "control_size",
        "color",
        "parent",
    ]
    assert module.defaults()["name"] == "spine"
    assert module.defaults()["curve"] == ""
    assert module.defaults()["color"] == 17
    assert module.name == "Spline IK"


def test_valid_params_have_no_problems(spine):
    assert rig.get("spline_ik").problems(_params()) == []


def test_valid_params_with_a_curve_have_no_problems(user_curve):
    assert rig.get("spline_ik").problems(_params(curve="my_crv")) == []


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"name": "bad name"}, "Name"),
        ({"start_joint": ""}, "Start joint"),
        ({"start_joint": "nothing"}, "nothing"),
        ({"end_joint": "nothing"}, "nothing"),
        ({"start_joint": "loc"}, "not a joint"),
        ({"start_joint": "chest", "end_joint": "hips"}, "below"),
        ({"end_joint": "hips"}, "below"),
        ({"end_joint": "spine1"}, "3 joints"),
        ({"curve": "nothing"}, "nothing"),
        ({"curve": "loc"}, "NURBS curve"),
        ({"curve": "hips"}, "NURBS curve"),
        ({"control_size": 0.0}, "Control size"),
        ({"color": 40}, "Color"),
        ({"parent": "nothing"}, "nothing"),
    ],
)
def test_problems(spine, overrides, expected):
    cmds.spaceLocator(name="loc")

    problems = rig.get("spline_ik").problems(_params(**overrides))

    assert any(expected in p for p in problems), problems


def test_ambiguous_joint_name_is_a_problem(spine):
    cmds.group(empty=True, name="other")
    _joint("chest", "other")

    problems = rig.get("spline_ik").problems(_params())

    assert any("chest" in p and "Several" in p for p in problems), problems


def test_ambiguous_curve_name_is_a_problem(user_curve):
    cmds.group(empty=True, name="other")
    cmds.parent(cmds.curve(degree=1, point=[(0, 0, 0), (1, 0, 0)]), "other")
    cmds.rename("other|curve1", "my_crv")

    problems = rig.get("spline_ik").problems(_params(curve="my_crv"))

    assert any("my_crv" in p and "Several" in p for p in problems), problems


def test_existing_module_with_the_same_name_is_a_problem(spine):
    rig.get("spline_ik").build(_params())

    problems = rig.get("spline_ik").problems(_params())

    assert any("body_splineIk_grp" in p for p in problems), problems


# -- build ------------------------------------------------------------------


def test_build_creates_curve_handle_and_controls(spine):
    before = _positions(spine)

    created = rig.get("spline_ik").build(_params())

    assert created == {
        "group": "body_splineIk_grp",
        "handle": "body_ikHandle",
        "curve": "body_splineIk_crv",
        "hip_control": "body_hip_ctrl",
        "chest_control": "body_chest_ctrl",
    }
    assert all(isinstance(v, str) for v in created.values())
    assert cmds.ikHandle("body_ikHandle", query=True, solver=True) == "ikSplineSolver"
    assert cmds.ikHandle("body_ikHandle", query=True, startJoint=True) == "hips"
    assert cmds.ls(cmds.ikHandle("body_ikHandle", query=True, curve=True)) == ["body_splineIk_crvShape"]
    assert not cmds.getAttr("body_ikHandle.visibility")
    assert cmds.getAttr("body_ikHandle.dTwistControlEnable")
    assert cmds.listRelatives("body_ikHandle", parent=True) == ["body_splineIk_grp"]
    assert cmds.listRelatives("body_splineIk_crv", parent=True) == ["body_splineIk_grp"]
    assert cmds.listRelatives("body_hip_ctrl", parent=True) == ["body_hip_ctrl_grp"]
    assert cmds.listRelatives("body_chest_ctrl", parent=True) == ["body_chest_ctrl_grp"]
    assert cmds.listRelatives("body_hip_ctrl_grp", parent=True) == ["body_splineIk_grp"]
    assert cmds.listRelatives("body_chest_ctrl_grp", parent=True) == ["body_splineIk_grp"]
    assert cmds.listRelatives("body_hip_drv_jnt", parent=True) == ["body_hip_ctrl"]
    assert cmds.listRelatives("body_chest_drv_jnt", parent=True) == ["body_chest_ctrl"]
    assert cmds.ls(cmds.listRelatives("body_hip_ctrl", shapes=True), type="nurbsCurve")
    assert cmds.ls(cmds.listRelatives("body_chest_ctrl", shapes=True), type="nurbsCurve")
    # The driver joints bend the curve.
    skin = cmds.ls(cmds.listHistory("body_splineIk_crv"), type="skinCluster")
    assert set(cmds.skinCluster(skin[0], query=True, influence=True)) == {"body_hip_drv_jnt", "body_chest_drv_jnt"}
    # Building doesn't move the joints.
    assert _close(_positions(spine), before)


def test_controls_sit_on_the_start_and_end_joints(spine):
    rig.get("spline_ik").build(_params())

    assert _close([_world("body_hip_ctrl"), _world("body_chest_ctrl")], [_world("hips"), _world("chest")])


def test_build_with_a_curve_uses_a_copy_and_keeps_the_users_curve(user_curve):
    rig.get("spline_ik").build(_params(curve="my_crv"))

    assert cmds.ls(cmds.ikHandle("body_ikHandle", query=True, curve=True)) == ["body_splineIk_crvShape"]
    assert cmds.objExists("my_crv")
    assert not cmds.ls(cmds.listHistory("my_crv"), type="skinCluster")
    # The joints snap onto the given curve.
    assert abs(_world("spine2").z - 1) < 1e-2


def test_moving_the_chest_control_moves_the_end_joint(spine):
    rig.get("spline_ik").build(_params())
    before = _world("chest")

    cmds.move(0, 0, 2, "body_chest_ctrl", relative=True)

    assert _world("chest").z > before.z + 1


def test_rotating_the_chest_control_twists_the_upper_joints(spine):
    rig.get("spline_ik").build(_params())
    hips, upper = _axis("hips", 2), _axis("spine3", 2)

    cmds.rotate(0, 90, 0, "body_chest_ctrl", relative=True, objectSpace=True)

    assert (_axis("spine3", 2) * upper) < 0.9  # the upper spine turned
    assert (_axis("hips", 2) * hips) > 0.99  # the hips didn't


def _color(control):
    """``(overrideEnabled, overrideColor)`` of each curve shape under ``control``."""
    shapes = cmds.listRelatives(control, shapes=True, type="nurbsCurve")
    return {(cmds.getAttr(f"{s}.overrideEnabled"), cmds.getAttr(f"{s}.overrideColor")) for s in shapes}


def test_color_goes_on_both_controls(spine):
    rig.get("spline_ik").build(_params(color=13))

    assert _color("body_hip_ctrl") == {(True, 13)}
    assert _color("body_chest_ctrl") == {(True, 13)}


def test_color_0_leaves_the_controls_maya_default_color(spine):
    rig.get("spline_ik").build(_params(color=0))

    assert _color("body_hip_ctrl") == {(False, 0)}
    assert _color("body_chest_ctrl") == {(False, 0)}


def test_build_goes_under_the_parent(spine):
    cmds.group(empty=True, name="rig_grp")

    rig.get("spline_ik").build(_params(parent="rig_grp"))

    assert cmds.listRelatives("body_splineIk_grp", parent=True) == ["rig_grp"]


def test_build_is_one_undo_step(spine):
    before = _positions(spine)
    cmds.undoInfo(state=True)
    nodes_before = _nodes()

    rig.get("spline_ik").build(_params())
    cmds.move(0, 0, 2, "body_chest_ctrl", relative=True)
    cmds.undo()
    cmds.undo()

    assert _nodes() == nodes_before
    assert _close(_positions(spine), before)


def test_build_with_problems_creates_nothing(spine):
    nodes_before = _nodes()

    with pytest.raises(ValueError):
        rig.get("spline_ik").build(_params(end_joint="nothing"))

    assert _nodes() == nodes_before
