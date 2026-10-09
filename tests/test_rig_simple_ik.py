import pytest
from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite import rig


def _joint(name, parent=None, translate=(0, 0, 0)):
    node = cmds.createNode("joint", name=name, parent=parent, skipSelect=True)
    cmds.setAttr(f"{node}.translate", *translate)
    return node


@pytest.fixture
def arm(new_scene):
    """shoulder > elbow > wrist, bent at the elbow toward -Z."""
    _joint("shoulder", translate=(0, 10, 0))
    _joint("elbow", "shoulder", translate=(5, 0, -1))
    _joint("wrist", "elbow", translate=(5, 0, 1))
    return ("shoulder", "elbow", "wrist")


def _params(**overrides):
    params = rig.get("simple_ik").defaults()
    params.update(name="L_arm", start_joint="shoulder", end_joint="wrist")
    params.update(overrides)
    return params


def _world(node):
    return om.MVector(cmds.xform(node, query=True, worldSpace=True, translation=True))


def _positions(nodes):
    return [_world(n) for n in nodes]


def _nodes():
    """Every node, except the solver nodes Maya makes once per scene with the
    first IK handle and keeps after an undo."""
    return set(cmds.ls()) - set(cmds.ls(type="ikSolver"))


def _close(a, b, tolerance=1e-3):
    return all((x - y).length() < tolerance for x, y in zip(a, b))


# -- parameters -------------------------------------------------------------


def test_ik_parameters_and_defaults():
    module = rig.get("simple_ik")

    assert [p.key for p in module.params] == [
        "name",
        "start_joint",
        "end_joint",
        "pole_distance",
        "control_size",
        "color",
        "parent",
    ]
    assert module.defaults()["color"] == 17
    assert module.name == "Simple IK"


def test_valid_params_have_no_problems(arm):
    assert rig.get("simple_ik").problems(_params()) == []


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"name": "bad name"}, "Name"),
        ({"start_joint": ""}, "Start joint"),
        ({"start_joint": "nothing"}, "nothing"),
        ({"end_joint": "nothing"}, "nothing"),
        ({"start_joint": "loc"}, "not a joint"),
        ({"start_joint": "wrist", "end_joint": "shoulder"}, "below"),
        ({"end_joint": "shoulder"}, "below"),
        ({"control_size": 0.0}, "Control size"),
        ({"pole_distance": -1.0}, "Pole distance"),
        ({"color": 40}, "Color"),
        ({"parent": "nothing"}, "nothing"),
        ({"end_joint": "elbow"}, "3 joints"),
    ],
)
def test_problems(arm, overrides, expected):
    cmds.spaceLocator(name="loc")

    problems = rig.get("simple_ik").problems(_params(**overrides))

    assert any(expected in p for p in problems), problems


def test_straight_chain_has_no_pole_vector_direction(new_scene):
    _joint("a")
    _joint("b", "a", translate=(5, 0, 0))
    _joint("c", "b", translate=(5, 0, 0))

    problems = rig.get("simple_ik").problems(_params(start_joint="a", end_joint="c"))

    assert any("straight" in p for p in problems), problems


def test_ambiguous_joint_name_is_a_problem(arm):
    cmds.group(empty=True, name="other")
    _joint("wrist", "other")

    problems = rig.get("simple_ik").problems(_params())

    assert any("wrist" in p and "Several" in p for p in problems), problems


def test_existing_module_with_the_same_name_is_a_problem(arm):
    rig.get("simple_ik").build(_params())

    problems = rig.get("simple_ik").problems(_params())

    assert any("L_arm_ik_grp" in p for p in problems), problems


# -- build ------------------------------------------------------------------


def test_build_creates_handle_controls_and_constraints(arm):
    before = _positions(arm)

    created = rig.get("simple_ik").build(_params())

    assert created == {
        "group": "L_arm_ik_grp",
        "handle": "L_arm_ikHandle",
        "control": "L_arm_ik_ctrl",
        "pole_vector": "L_arm_pv_ctrl",
    }
    # Always the rotate-plane solver, always with a pole vector.
    assert cmds.ikHandle("L_arm_ikHandle", query=True, solver=True) == "ikRPsolver"
    assert cmds.ikHandle("L_arm_ikHandle", query=True, startJoint=True) == "shoulder"
    assert cmds.listRelatives("L_arm_ikHandle", parent=True) == ["L_arm_ik_ctrl"]
    assert cmds.listRelatives("L_arm_ik_ctrl", parent=True) == ["L_arm_ik_ctrl_grp"]
    assert cmds.listRelatives("L_arm_ik_ctrl_grp", parent=True) == ["L_arm_ik_grp"]
    assert cmds.listRelatives("L_arm_pv_ctrl_grp", parent=True) == ["L_arm_ik_grp"]
    assert cmds.ls(cmds.listRelatives("L_arm_ik_ctrl", shapes=True), type="nurbsCurve")
    assert cmds.ls(cmds.listRelatives("L_arm_pv_ctrl", shapes=True), type="nurbsCurve")
    assert cmds.listConnections("wrist", type="orientConstraint")
    assert cmds.listConnections("L_arm_ikHandle", type="poleVectorConstraint")
    # Building doesn't move the chain.
    assert _close(_positions(arm), before)


def test_ik_control_sits_on_the_end_joint(arm):
    rig.get("simple_ik").build(_params())

    assert _close([_world("L_arm_ik_ctrl")], [_world("wrist")])


def test_pole_vector_lies_on_the_chain_plane_out_from_the_middle(arm):
    rig.get("simple_ik").build(_params(pole_distance=4.0))

    start, mid, end = _positions(arm)
    pole = _world("L_arm_pv_ctrl")
    normal = ((mid - start) ^ (end - start)).normal()
    assert abs((pole - start) * normal) < 1e-3
    assert abs((pole - mid).length() - 4.0) < 1e-3
    # Out on the side the elbow bends to (-Z), not across the chain.
    assert pole.z < mid.z


def test_moving_the_control_drives_the_chain(arm):
    rig.get("simple_ik").build(_params())

    cmds.move(-2, -2, 0, "L_arm_ik_ctrl", relative=True)

    assert _close([_world("wrist")], [_world("L_arm_ik_ctrl")])


def _color(control):
    """``(overrideEnabled, overrideColor)`` of each curve shape under ``control``."""
    shapes = cmds.listRelatives(control, shapes=True, type="nurbsCurve")
    return {(cmds.getAttr(f"{s}.overrideEnabled"), cmds.getAttr(f"{s}.overrideColor")) for s in shapes}


def test_color_goes_on_both_controls(arm):
    rig.get("simple_ik").build(_params(color=13))

    assert _color("L_arm_ik_ctrl") == {(True, 13)}
    assert _color("L_arm_pv_ctrl") == {(True, 13)}


def test_color_0_leaves_the_controls_maya_default_color(arm):
    rig.get("simple_ik").build(_params(color=0))

    assert _color("L_arm_ik_ctrl") == {(False, 0)}
    assert _color("L_arm_pv_ctrl") == {(False, 0)}


def test_build_goes_under_the_parent(arm):
    cmds.group(empty=True, name="rig_grp")

    rig.get("simple_ik").build(_params(parent="rig_grp"))

    assert cmds.listRelatives("L_arm_ik_grp", parent=True) == ["rig_grp"]


def test_control_size_scales_the_control(arm):
    rig.get("simple_ik").build(_params(name="small", control_size=1.0))
    small = cmds.exactWorldBoundingBox("small_ik_ctrl")
    cmds.delete("small_ik_grp")
    rig.get("simple_ik").build(_params(name="big", control_size=2.0))
    big = cmds.exactWorldBoundingBox("big_ik_ctrl")

    assert abs((big[4] - big[1]) - 2 * (small[4] - small[1])) < 1e-3


def test_build_is_one_undo_step(arm):
    before = _positions(arm)
    cmds.undoInfo(state=True)
    nodes_before = _nodes()

    rig.get("simple_ik").build(_params())
    cmds.move(-2, -2, 0, "L_arm_ik_ctrl", relative=True)
    cmds.undo()
    cmds.undo()

    assert _nodes() == nodes_before
    assert _close(_positions(arm), before)


def test_build_with_problems_creates_nothing(arm):
    nodes_before = _nodes()

    with pytest.raises(ValueError):
        rig.get("simple_ik").build(_params(end_joint="nothing"))

    assert _nodes() == nodes_before
