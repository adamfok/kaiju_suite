import pytest
from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.rigging.rig_module import get_rig_module


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
    params = get_rig_module("ik_fk").defaults()
    params.update(name="L_arm", start_joint="shoulder", end_joint="wrist")
    params.update(overrides)
    return params


def _world(node):
    return om.MVector(cmds.xform(node, query=True, worldSpace=True, translation=True))


def _positions(nodes):
    return [_world(n) for n in nodes]


def _rotations(nodes):
    return [om.MVector(cmds.xform(n, query=True, worldSpace=True, rotation=True)) for n in nodes]


def _nodes():
    """Every node, except the solver nodes Maya makes once per scene with the
    first IK handle and keeps after an undo."""
    return set(cmds.ls()) - set(cmds.ls(type="ikSolver"))


def _close(a, b, tolerance=1e-3):
    return all((x - y).length() < tolerance for x, y in zip(a, b))


IK_CONTROLS = ("L_arm_ik_ctrl", "L_arm_pv_ctrl")
FK_CONTROLS = ("L_arm_01_fk_ctrl", "L_arm_02_fk_ctrl", "L_arm_03_fk_ctrl")
SWITCH = "L_arm_switch_ctrl"


# -- parameters -------------------------------------------------------------


def test_ik_fk_parameters_and_defaults():
    rig_module = get_rig_module("ik_fk")

    assert [p.key for p in rig_module.params] == [
        "name",
        "start_joint",
        "end_joint",
        "pole_distance",
        "control_size",
        "color",
        "parent",
    ]
    assert rig_module.defaults() == {
        "name": "arm",
        "start_joint": "",
        "end_joint": "",
        "pole_distance": 5.0,
        "control_size": 1.0,
        "color": 17,
        "parent": "",
    }
    assert rig_module.name == "IK/FK"


def test_valid_params_have_no_problems(arm):
    assert get_rig_module("ik_fk").problems(_params()) == []


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"name": "bad name"}, "Name"),
        ({"name": ""}, "Name"),
        ({"start_joint": ""}, "Start joint"),
        ({"end_joint": ""}, "End joint"),
        ({"start_joint": "nothing"}, "nothing"),
        ({"end_joint": "nothing"}, "nothing"),
        ({"start_joint": "loc"}, "not a joint"),
        ({"end_joint": "loc"}, "not a joint"),
        ({"start_joint": "wrist", "end_joint": "shoulder"}, "below"),
        ({"end_joint": "shoulder"}, "below"),
        ({"end_joint": "elbow"}, "3 joints"),
        ({"control_size": 0.0}, "Control size"),
        ({"pole_distance": -1.0}, "Pole distance"),
        ({"pole_distance": 0.0}, "Pole distance"),
        ({"color": 40}, "Color"),
        ({"parent": "nothing"}, "nothing"),
    ],
)
def test_problems(arm, overrides, expected):
    cmds.spaceLocator(name="loc")

    problems = get_rig_module("ik_fk").problems(_params(**overrides))

    assert any(expected in p for p in problems), problems


def test_straight_chain_is_a_problem(new_scene):
    _joint("a")
    _joint("b", "a", translate=(5, 0, 0))
    _joint("c", "b", translate=(5, 0, 0))

    problems = get_rig_module("ik_fk").problems(_params(start_joint="a", end_joint="c"))

    assert any("straight" in p for p in problems), problems


def test_ambiguous_joint_name_is_a_problem(arm):
    cmds.group(empty=True, name="other")
    _joint("wrist", "other")

    problems = get_rig_module("ik_fk").problems(_params())

    assert any("wrist" in p and "Several" in p for p in problems), problems


def test_existing_rig_module_with_the_same_name_is_a_problem(arm):
    get_rig_module("ik_fk").build(_params())

    problems = get_rig_module("ik_fk").problems(_params())

    assert any("L_arm_ikfk_grp" in p for p in problems), problems


# -- build ------------------------------------------------------------------


def test_build_creates_the_rig(arm):
    created = get_rig_module("ik_fk").build(_params())

    assert created == {
        "group": "L_arm_ikfk_grp",
        "switch": SWITCH,
        "handle": "L_arm_ikHandle",
        "ik_control": "L_arm_ik_ctrl",
        "pole_vector": "L_arm_pv_ctrl",
        "fk_controls": ", ".join(FK_CONTROLS),
    }
    assert all(isinstance(value, str) for value in created.values())

    def parent(node):
        return (cmds.listRelatives(node, parent=True) or [None])[0]

    # The IK and FK chains: copies of the bind chain, inside the rig module group.
    for side in ("ik", "fk"):
        assert parent(f"L_arm_01_{side}_jnt") == "L_arm_jnt_grp"
        assert parent(f"L_arm_02_{side}_jnt") == f"L_arm_01_{side}_jnt"
        assert parent(f"L_arm_03_{side}_jnt") == f"L_arm_02_{side}_jnt"
        assert cmds.nodeType(f"L_arm_01_{side}_jnt") == "joint"
        assert cmds.listRelatives(f"L_arm_03_{side}_jnt", children=True, type="joint") is None
    assert parent("L_arm_jnt_grp") == "L_arm_ikfk_grp"
    assert cmds.getAttr("L_arm_jnt_grp.visibility") is False

    # IK side, as in Simple IK, on the IK chain.
    assert cmds.ikHandle("L_arm_ikHandle", query=True, solver=True) == "ikRPsolver"
    assert cmds.ikHandle("L_arm_ikHandle", query=True, startJoint=True) == "L_arm_01_ik_jnt"
    assert parent("L_arm_ikHandle") == "L_arm_ik_ctrl"
    assert parent("L_arm_ik_ctrl") == "L_arm_ik_ctrl_grp"
    assert parent("L_arm_ik_ctrl_grp") == "L_arm_ik_ctrls_grp"
    assert parent("L_arm_pv_ctrl_grp") == "L_arm_ik_ctrls_grp"
    assert parent("L_arm_ik_ctrls_grp") == "L_arm_ikfk_grp"
    assert cmds.listConnections("L_arm_03_ik_jnt", type="orientConstraint")
    assert cmds.listConnections("L_arm_ikHandle", type="poleVectorConstraint")

    # FK side: nested controls.
    assert parent("L_arm_01_fk_ctrl_grp") == "L_arm_fk_ctrls_grp"
    assert parent("L_arm_02_fk_ctrl_grp") == "L_arm_01_fk_ctrl"
    assert parent("L_arm_03_fk_ctrl_grp") == "L_arm_02_fk_ctrl"
    assert parent("L_arm_fk_ctrls_grp") == "L_arm_ikfk_grp"
    for i, control in enumerate(FK_CONTROLS, 1):
        assert parent(control) == f"{control}_grp"
        assert cmds.listConnections(f"L_arm_{i:02d}_fk_jnt", type="parentConstraint")

    # The switch.
    assert parent(SWITCH) == "L_arm_switch_ctrl_grp"
    assert parent("L_arm_switch_ctrl_grp") == "L_arm_ikfk_grp"
    assert cmds.getAttr(f"{SWITCH}.ikFk") == 0
    assert cmds.attributeQuery("ikFk", node=SWITCH, keyable=True)
    assert cmds.attributeQuery("ikFk", node=SWITCH, minimum=True) == [0.0]
    assert cmds.attributeQuery("ikFk", node=SWITCH, maximum=True) == [1.0]

    for control in IK_CONTROLS + FK_CONTROLS + (SWITCH,):
        assert cmds.ls(cmds.listRelatives(control, shapes=True), type="nurbsCurve"), control
    # Each bind joint follows its IK and FK joints.
    for joint in arm:
        assert cmds.listConnections(joint, type="parentConstraint"), joint


def test_bind_joints_keep_their_parents(arm):
    get_rig_module("ik_fk").build(_params())

    assert cmds.listRelatives("shoulder", parent=True) is None
    assert cmds.listRelatives("elbow", parent=True) == ["shoulder"]
    assert cmds.listRelatives("wrist", parent=True) == ["elbow"]


def test_building_does_not_move_the_bind_joints(arm):
    positions, rotations = _positions(arm), _rotations(arm)

    get_rig_module("ik_fk").build(_params())

    assert _close(_positions(arm), positions)
    assert _close(_rotations(arm), rotations)
    for side in ("ik", "fk"):
        assert _close(_positions([f"L_arm_{i:02d}_{side}_jnt" for i in (1, 2, 3)]), positions)


def test_ik_control_sits_on_the_end_joint(arm):
    get_rig_module("ik_fk").build(_params())

    assert _close([_world("L_arm_ik_ctrl")], [_world("wrist")])


def test_fk_controls_sit_on_their_joints(arm):
    get_rig_module("ik_fk").build(_params())

    assert _close(_positions(FK_CONTROLS), _positions(arm))


def test_pole_vector_lies_on_the_chain_plane_out_from_the_middle(arm):
    get_rig_module("ik_fk").build(_params(pole_distance=4.0))

    start, mid, end = _positions(arm)
    pole = _world("L_arm_pv_ctrl")
    normal = ((mid - start) ^ (end - start)).normal()
    assert abs((pole - start) * normal) < 1e-3
    assert abs((pole - mid).length() - 4.0) < 1e-3
    assert pole.z < mid.z


def test_at_fk_rotating_an_fk_control_rotates_the_bind_chain(arm):
    get_rig_module("ik_fk").build(_params())
    before = _world("elbow")

    cmds.setAttr("L_arm_01_fk_ctrl.rotateZ", 30)

    assert not _close([_world("elbow")], [before])
    assert _close(_positions(arm), _positions(["L_arm_01_fk_jnt", "L_arm_02_fk_jnt", "L_arm_03_fk_jnt"]))
    assert _close(_rotations(arm), _rotations(["L_arm_01_fk_jnt", "L_arm_02_fk_jnt", "L_arm_03_fk_jnt"]))


def test_at_fk_the_ik_control_does_not_move_the_bind_chain(arm):
    get_rig_module("ik_fk").build(_params())
    before = _positions(arm)

    cmds.move(-2, -2, 0, "L_arm_ik_ctrl", relative=True)

    assert _close(_positions(arm), before)


def test_at_ik_moving_the_ik_control_drives_the_bind_chain(arm):
    get_rig_module("ik_fk").build(_params())
    cmds.setAttr(f"{SWITCH}.ikFk", 1)

    cmds.move(-2, -2, 0, "L_arm_ik_ctrl", relative=True)

    assert _close([_world("wrist")], [_world("L_arm_ik_ctrl")])
    assert _close(_positions(arm), _positions(["L_arm_01_ik_jnt", "L_arm_02_ik_jnt", "L_arm_03_ik_jnt"]))
    # FK controls no longer drive it.
    cmds.setAttr("L_arm_01_fk_ctrl.rotateZ", 30)
    assert _close([_world("wrist")], [_world("L_arm_ik_ctrl")])


def test_switch_follows_the_end_joint(arm):
    get_rig_module("ik_fk").build(_params())
    offset = _world(SWITCH) - _world("wrist")

    cmds.setAttr("L_arm_01_fk_ctrl.rotateZ", 30)

    assert _close([_world(SWITCH) - _world("wrist")], [offset])


def _visible(group):
    return cmds.getAttr(f"{group}.visibility")


@pytest.mark.parametrize("ik_fk, ik_visible, fk_visible", [(0, False, True), (0.5, True, True), (1, True, False)])
def test_control_visibility_follows_the_switch(arm, ik_fk, ik_visible, fk_visible):
    get_rig_module("ik_fk").build(_params())

    cmds.setAttr(f"{SWITCH}.ikFk", ik_fk)

    assert bool(_visible("L_arm_ik_ctrls_grp")) is ik_visible
    assert bool(_visible("L_arm_fk_ctrls_grp")) is fk_visible
    assert _visible("L_arm_switch_ctrl_grp")


def _color(control):
    """``(overrideEnabled, overrideColor)`` of each curve shape under ``control``."""
    shapes = cmds.listRelatives(control, shapes=True, type="nurbsCurve")
    return {(cmds.getAttr(f"{s}.overrideEnabled"), cmds.getAttr(f"{s}.overrideColor")) for s in shapes}


def test_color_goes_on_every_control(arm):
    get_rig_module("ik_fk").build(_params(color=13))

    for control in IK_CONTROLS + FK_CONTROLS + (SWITCH,):
        assert _color(control) == {(True, 13)}, control


def test_color_0_leaves_the_controls_maya_default_color(arm):
    get_rig_module("ik_fk").build(_params(color=0))

    for control in IK_CONTROLS + FK_CONTROLS + (SWITCH,):
        assert _color(control) == {(False, 0)}, control


def test_build_goes_under_the_parent(arm):
    cmds.group(empty=True, name="rig_grp")

    get_rig_module("ik_fk").build(_params(parent="rig_grp"))

    assert cmds.listRelatives("L_arm_ikfk_grp", parent=True) == ["rig_grp"]


def test_build_keeps_the_selection(arm):
    cmds.select("elbow")

    get_rig_module("ik_fk").build(_params())

    assert cmds.ls(selection=True) == ["elbow"]


def test_build_is_one_undo_step(arm):
    positions, rotations = _positions(arm), _rotations(arm)
    cmds.undoInfo(state=True)
    nodes_before = _nodes()

    get_rig_module("ik_fk").build(_params())
    cmds.setAttr("L_arm_01_fk_ctrl.rotateZ", 30)
    cmds.undo()
    cmds.undo()

    assert _nodes() == nodes_before
    assert _close(_positions(arm), positions)
    assert _close(_rotations(arm), rotations)
    assert not cmds.listConnections("shoulder", type="parentConstraint")


def test_build_with_problems_creates_nothing(arm):
    nodes_before = _nodes()

    with pytest.raises(ValueError):
        get_rig_module("ik_fk").build(_params(end_joint="nothing"))

    assert _nodes() == nodes_before


# -- matching (switch without a pop) -------------------------------------------------

from kaiju_suite.rigging.rig_module import ik_fk_match  # noqa: E402

BIND = ("shoulder", "elbow", "wrist")


def _bind_matrices():
    return [om.MMatrix(cmds.xform(j, query=True, worldSpace=True, matrix=True)) for j in BIND]


def _same_matrices(a, b, tolerance=1e-3):
    return all(x.isEquivalent(y, tolerance) for x, y in zip(a, b))


def _pose_ik():
    cmds.xform("L_arm_ik_ctrl", worldSpace=True, translation=(7, 7, 2))
    cmds.setAttr("L_arm_ik_ctrl.rotate", 20, -30, 15)
    cmds.xform("L_arm_pv_ctrl", worldSpace=True, translation=(5, 14, -6))


def _pose_fk():
    """Any pose an IK chain can reach: the elbow only bends in the chain's
    plane (about Y, as the joints aren't oriented), like a hinge."""
    cmds.setAttr("L_arm_01_fk_ctrl.rotate", 10, 25, -40)
    cmds.setAttr("L_arm_02_fk_ctrl.rotate", 0, -35, 0)
    cmds.setAttr("L_arm_03_fk_ctrl.rotate", 30, 5, -20)


def test_the_switch_stores_what_matching_needs(arm):
    get_rig_module("ik_fk").build(_params())

    info = ik_fk_match.links(SWITCH)

    assert info.fk_controls == list(FK_CONTROLS)
    assert (info.ik_control, info.pole_control) == IK_CONTROLS
    assert info.ik_joints == ["L_arm_01_ik_jnt", "L_arm_02_ik_jnt", "L_arm_03_ik_jnt"]
    assert info.fk_joints == ["L_arm_01_fk_jnt", "L_arm_02_fk_jnt", "L_arm_03_fk_jnt"]
    assert ik_fk_match.is_switch(SWITCH) and not ik_fk_match.is_switch("L_arm_ik_ctrl")


def test_a_control_of_the_limb_finds_its_switch(arm):
    get_rig_module("ik_fk").build(_params())

    for node in FK_CONTROLS + IK_CONTROLS + (SWITCH,):
        assert ik_fk_match.find_switch(node) == SWITCH
    assert ik_fk_match.find_switch("shoulder") is None


def test_match_fk_to_ik_switches_to_fk_without_moving_the_bind_chain(arm):
    get_rig_module("ik_fk").build(_params())
    cmds.setAttr(f"{SWITCH}.ikFk", 1)
    _pose_ik()
    before = _bind_matrices()

    ik_fk_match.match_fk_to_ik(SWITCH)

    assert cmds.getAttr(f"{SWITCH}.ikFk") == 0
    assert _same_matrices(_bind_matrices(), before)


def test_match_ik_to_fk_switches_to_ik_without_moving_the_bind_chain(arm):
    get_rig_module("ik_fk").build(_params())
    _pose_fk()
    before = _bind_matrices()

    ik_fk_match.match_ik_to_fk(SWITCH)

    assert cmds.getAttr(f"{SWITCH}.ikFk") == 1
    assert _same_matrices(_bind_matrices(), before)


def test_match_ik_to_fk_of_a_pose_ik_cant_reach_still_matches_the_joint_positions(arm):
    """An elbow twisted out of its plane can't be copied by a hinge, but
    every joint still lands where it was."""
    get_rig_module("ik_fk").build(_params())
    _pose_fk()
    cmds.setAttr("L_arm_02_fk_ctrl.rotateX", 25)
    before = _positions(BIND)

    ik_fk_match.match_ik_to_fk(SWITCH)

    assert _close(_positions(BIND), before)


def test_match_ik_to_fk_puts_the_pole_vector_on_the_chain_plane(arm):
    get_rig_module("ik_fk").build(_params())
    _pose_fk()

    ik_fk_match.match_ik_to_fk(SWITCH)

    start, mid, end = _positions(BIND)
    normal = (mid - start) ^ (end - start)
    assert abs((_world("L_arm_pv_ctrl") - mid).normal() * normal.normal()) < 1e-3


def test_match_with_key_keys_both_frames_and_steps_the_switch(arm):
    get_rig_module("ik_fk").build(_params())
    cmds.setAttr(f"{SWITCH}.ikFk", 1)
    _pose_ik()
    cmds.currentTime(10)
    before = _bind_matrices()

    ik_fk_match.match_fk_to_ik(SWITCH, key=True)

    assert cmds.keyframe(f"{SWITCH}.ikFk", query=True, timeChange=True) == [9.0, 10.0]
    assert cmds.keyframe(f"{SWITCH}.ikFk", query=True, valueChange=True) == [1.0, 0.0]
    assert cmds.keyTangent(f"{SWITCH}.ikFk", query=True, outTangentType=True)[0] == "step"
    assert cmds.keyframe("L_arm_02_fk_ctrl.rotateY", query=True, timeChange=True) == [9.0, 10.0]
    assert _same_matrices(_bind_matrices(), before)
    cmds.currentTime(9)
    assert cmds.getAttr(f"{SWITCH}.ikFk") == 1


def test_matching_a_rig_built_without_the_links_says_to_rebuild(arm):
    get_rig_module("ik_fk").build(_params())
    cmds.deleteAttr(f"{SWITCH}.{ik_fk_match.FK_CONTROLS}")

    with pytest.raises(ValueError, match="rebuild"):
        ik_fk_match.match_fk_to_ik(SWITCH)


def test_match_fk_to_ik_on_an_oriented_chain(arm):
    cmds.joint("shoulder", edit=True, orientJoint="xyz", secondaryAxisOrient="yup", children=True, zeroScaleOrient=True)
    get_rig_module("ik_fk").build(_params())
    cmds.setAttr(f"{SWITCH}.ikFk", 1)
    _pose_ik()
    before = _bind_matrices()

    ik_fk_match.match_fk_to_ik(SWITCH)

    assert _same_matrices(_bind_matrices(), before)
