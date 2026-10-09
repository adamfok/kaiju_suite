import pytest
from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite import rig


@pytest.fixture
def elbow(new_scene):
    """shoulder > elbow, both rotated, so the elbow's world orientation is
    neither the world's nor its own joint orient alone."""
    shoulder = cmds.createNode("joint", name="shoulder", skipSelect=True)
    cmds.setAttr(f"{shoulder}.translate", 0, 10, 0)
    cmds.setAttr(f"{shoulder}.jointOrient", 0, 0, -30)
    joint = cmds.createNode("joint", name="elbow", parent=shoulder, skipSelect=True)
    cmds.setAttr(f"{joint}.translate", 5, 0, 0)
    cmds.setAttr(f"{joint}.jointOrient", 0, -40, 0)
    cmds.setAttr(f"{joint}.rotate", 10, 0, 20)
    return "elbow"


def _params(**overrides):
    params = rig.get("single_fk").defaults()
    params.update(name="L_elbow", joint="elbow")
    params.update(overrides)
    return params


def _world(node):
    return om.MVector(cmds.xform(node, query=True, worldSpace=True, translation=True))


def _matrix(node):
    return om.MMatrix(cmds.xform(node, query=True, worldSpace=True, matrix=True))


def _close(a, b, tolerance=1e-3):
    return (a - b).length() < tolerance


def _same_matrix(a, b, tolerance=1e-3):
    return a.isEquivalent(b, tolerance)


# -- parameters -------------------------------------------------------------


def test_fk_parameters_and_defaults():
    module = rig.get("single_fk")

    assert [p.key for p in module.params] == ["name", "joint", "control_size", "color", "parent"]
    assert module.defaults() == {"name": "fk", "joint": "", "control_size": 1.0, "color": 17, "parent": ""}
    assert module.name == "Single FK"


def test_valid_params_have_no_problems(elbow):
    assert rig.get("single_fk").problems(_params()) == []


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"name": "bad name"}, "Name"),
        ({"name": ""}, "Name"),
        ({"joint": ""}, "Joint"),
        ({"joint": "nothing"}, "nothing"),
        ({"joint": "loc"}, "not a joint"),
        ({"control_size": 0.0}, "Control size"),
        ({"control_size": -1.0}, "Control size"),
        ({"color": 40}, "Color"),
        ({"parent": "nothing"}, "nothing"),
    ],
)
def test_problems(elbow, overrides, expected):
    cmds.spaceLocator(name="loc")

    problems = rig.get("single_fk").problems(_params(**overrides))

    assert any(expected in p for p in problems), problems


def test_ambiguous_joint_name_is_a_problem(elbow):
    cmds.group(empty=True, name="other")
    cmds.createNode("joint", name="elbow", parent="other", skipSelect=True)

    problems = rig.get("single_fk").problems(_params())

    assert any("elbow" in p and "Several" in p for p in problems), problems


def test_existing_module_with_the_same_name_is_a_problem(elbow):
    rig.get("single_fk").build(_params())

    problems = rig.get("single_fk").problems(_params())

    assert any("L_elbow_fk_grp" in p for p in problems), problems


# -- build ------------------------------------------------------------------


def test_build_creates_groups_control_and_constraint(elbow):
    created = rig.get("single_fk").build(_params())

    assert created == {
        "group": "L_elbow_fk_grp",
        "control_group": "L_elbow_fk_ctrl_grp",
        "control": "L_elbow_fk_ctrl",
    }
    assert cmds.listRelatives("L_elbow_fk_grp", parent=True) is None
    assert cmds.listRelatives("L_elbow_fk_ctrl_grp", parent=True) == ["L_elbow_fk_grp"]
    assert cmds.listRelatives("L_elbow_fk_ctrl", parent=True) == ["L_elbow_fk_ctrl_grp"]
    assert cmds.ls(cmds.listRelatives("L_elbow_fk_ctrl", shapes=True), type="nurbsCurve")
    assert cmds.listConnections("elbow", type="parentConstraint")


def test_control_sits_on_the_joint_matching_its_orientation(elbow):
    rig.get("single_fk").build(_params())

    assert _same_matrix(_matrix("L_elbow_fk_ctrl_grp"), _matrix("elbow"))
    assert _same_matrix(_matrix("L_elbow_fk_ctrl"), _matrix("elbow"))
    # The offset group holds the placement; the control starts zeroed.
    assert cmds.getAttr("L_elbow_fk_ctrl.translate")[0] == pytest.approx((0, 0, 0), abs=1e-6)
    assert cmds.getAttr("L_elbow_fk_ctrl.rotate")[0] == pytest.approx((0, 0, 0), abs=1e-6)


def test_build_doesnt_move_or_rotate_the_joint(elbow):
    matrix = _matrix(elbow)
    rotate = cmds.getAttr(f"{elbow}.rotate")[0]

    rig.get("single_fk").build(_params())

    assert _same_matrix(_matrix(elbow), matrix)
    assert cmds.getAttr(f"{elbow}.rotate")[0] == pytest.approx(rotate, abs=1e-3)


def test_moving_and_rotating_the_control_drives_the_joint(elbow):
    rig.get("single_fk").build(_params())

    cmds.move(1, 2, 3, "L_elbow_fk_ctrl", relative=True, worldSpace=True)
    cmds.rotate(15, -25, 35, "L_elbow_fk_ctrl", relative=True, objectSpace=True)

    assert _same_matrix(_matrix(elbow), _matrix("L_elbow_fk_ctrl"))


def _color(control):
    """``(overrideEnabled, overrideColor)`` of each curve shape under ``control``."""
    shapes = cmds.listRelatives(control, shapes=True, type="nurbsCurve")
    return {(cmds.getAttr(f"{s}.overrideEnabled"), cmds.getAttr(f"{s}.overrideColor")) for s in shapes}


def test_color_goes_on_the_control(elbow):
    rig.get("single_fk").build(_params(color=13))

    assert _color("L_elbow_fk_ctrl") == {(True, 13)}


def test_color_0_leaves_the_control_maya_default_color(elbow):
    rig.get("single_fk").build(_params(color=0))

    assert _color("L_elbow_fk_ctrl") == {(False, 0)}


def test_build_goes_under_the_parent(elbow):
    cmds.group(empty=True, name="rig_grp")

    rig.get("single_fk").build(_params(parent="rig_grp"))

    assert cmds.listRelatives("L_elbow_fk_grp", parent=True) == ["rig_grp"]


def test_control_size_scales_the_control(elbow):
    rig.get("single_fk").build(_params(name="small", control_size=1.0))
    small = cmds.exactWorldBoundingBox("small_fk_ctrl")
    cmds.delete("small_fk_grp")
    rig.get("single_fk").build(_params(name="big", control_size=2.0))
    big = cmds.exactWorldBoundingBox("big_fk_ctrl")

    small_diagonal = om.MVector(small[3:]) - om.MVector(small[:3])
    big_diagonal = om.MVector(big[3:]) - om.MVector(big[:3])
    assert abs(big_diagonal.length() - 2 * small_diagonal.length()) < 1e-3


def test_build_is_one_undo_step(elbow):
    matrix = _matrix(elbow)
    cmds.undoInfo(state=True)
    nodes_before = set(cmds.ls())

    rig.get("single_fk").build(_params())
    cmds.move(1, 2, 3, "L_elbow_fk_ctrl", relative=True)
    cmds.undo()
    cmds.undo()

    assert set(cmds.ls()) == nodes_before
    assert _same_matrix(_matrix(elbow), matrix)


def test_build_with_problems_creates_nothing(elbow):
    nodes_before = set(cmds.ls())

    with pytest.raises(ValueError):
        rig.get("single_fk").build(_params(joint="nothing"))

    assert set(cmds.ls()) == nodes_before
