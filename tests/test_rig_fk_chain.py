import pytest
from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite import rig

CONTROLS = ["L_finger_01_fk_ctrl", "L_finger_02_fk_ctrl", "L_finger_03_fk_ctrl", "L_finger_04_fk_ctrl"]


def _joint(name, parent=None, translate=(0, 0, 0), orient=(0, 0, 0)):
    node = cmds.createNode("joint", name=name, parent=parent, skipSelect=True)
    cmds.setAttr(f"{node}.translate", *translate)
    cmds.setAttr(f"{node}.jointOrient", *orient)
    return node


@pytest.fixture
def finger(new_scene):
    """knuckle > middle > tip_base > tip, each joint oriented differently, so
    a control that ignored orientation would show."""
    _joint("knuckle", translate=(0, 10, 0), orient=(10, 0, -20))
    _joint("middle", "knuckle", translate=(3, 0, 0), orient=(0, 15, -30))
    _joint("tip_base", "middle", translate=(2, 0, 0), orient=(5, 0, -25))
    _joint("tip", "tip_base", translate=(1.5, 0, 0))
    return ("knuckle", "middle", "tip_base", "tip")


def _params(**overrides):
    params = rig.get("fk_chain").defaults()
    params.update(name="L_finger", start_joint="knuckle", end_joint="tip")
    params.update(overrides)
    return params


def _world(node):
    return om.MVector(cmds.xform(node, query=True, worldSpace=True, translation=True))


def _positions(nodes):
    return [_world(n) for n in nodes]


def _rotation(node):
    """``node``'s world orientation, as a quaternion."""
    matrix = om.MMatrix(cmds.xform(node, query=True, worldSpace=True, matrix=True))
    return om.MTransformationMatrix(matrix).rotation(asQuaternion=True)


def _same_orientation(a, b, tolerance=1e-4):
    return _rotation(a).isEquivalent(_rotation(b), tolerance)


def _close(a, b, tolerance=1e-3):
    return all((x - y).length() < tolerance for x, y in zip(a, b))


def _nodes():
    return set(cmds.ls())


# -- parameters -------------------------------------------------------------


def test_fk_parameters_and_defaults():
    module = rig.get("fk_chain")

    assert [p.key for p in module.params] == [
        "name",
        "start_joint",
        "end_joint",
        "end_control",
        "control_size",
        "color",
        "parent",
    ]
    assert module.defaults() == {
        "name": "fk",
        "start_joint": "",
        "end_joint": "",
        "end_control": True,
        "control_size": 1.0,
        "color": 17,
        "parent": "",
    }
    assert module.name == "FK Chain"


def test_valid_params_have_no_problems(finger):
    assert rig.get("fk_chain").problems(_params()) == []


def test_a_two_joint_chain_is_enough(finger):
    assert rig.get("fk_chain").problems(_params(start_joint="tip_base")) == []


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"name": "bad name"}, "Name"),
        ({"name": "1st"}, "Name"),
        ({"start_joint": ""}, "Start joint"),
        ({"end_joint": ""}, "End joint"),
        ({"start_joint": "nothing"}, "nothing"),
        ({"end_joint": "nothing"}, "nothing"),
        ({"start_joint": "loc"}, "not a joint"),
        ({"start_joint": "tip", "end_joint": "knuckle"}, "below"),
        ({"end_joint": "knuckle"}, "below"),
        ({"control_size": 0.0}, "Control size"),
        ({"control_size": -1.0}, "Control size"),
        ({"color": 40}, "Color"),
        ({"end_control": "yes"}, "End control"),
        ({"parent": "nothing"}, "nothing"),
    ],
)
def test_problems(finger, overrides, expected):
    cmds.spaceLocator(name="loc")

    problems = rig.get("fk_chain").problems(_params(**overrides))

    assert any(expected in p for p in problems), problems


def test_ambiguous_joint_name_is_a_problem(finger):
    cmds.group(empty=True, name="other")
    _joint("tip", "other")

    problems = rig.get("fk_chain").problems(_params())

    assert any("tip" in p and "Several" in p for p in problems), problems


def test_a_non_joint_in_the_chain_is_a_problem(new_scene):
    _joint("a")
    cmds.group(empty=True, name="between", parent="a")
    _joint("b", "between", translate=(5, 0, 0))

    problems = rig.get("fk_chain").problems(_params(start_joint="a", end_joint="b"))

    assert any("between" in p for p in problems), problems


def test_existing_module_with_the_same_name_is_a_problem(finger):
    rig.get("fk_chain").build(_params())

    problems = rig.get("fk_chain").problems(_params())

    assert any("L_finger_fkChain_grp" in p for p in problems), problems


# -- build ------------------------------------------------------------------


def test_build_creates_nested_controls(finger):
    created = rig.get("fk_chain").build(_params())

    assert created == {"group": "L_finger_fkChain_grp", "controls": ", ".join(CONTROLS)}
    # The Assembler prints the values joined, so they must all be text.
    assert all(isinstance(value, str) for value in created.values())
    assert cmds.listRelatives("L_finger_fkChain_grp", parent=True) is None
    assert cmds.listRelatives("L_finger_01_fk_ctrl_grp", parent=True) == ["L_finger_fkChain_grp"]
    for control in CONTROLS:
        assert cmds.listRelatives(control, parent=True) == [f"{control}_grp"]
        assert cmds.ls(cmds.listRelatives(control, shapes=True), type="nurbsCurve")
    # Each offset group sits under the previous control.
    for above, control in zip(CONTROLS, CONTROLS[1:]):
        assert cmds.listRelatives(f"{control}_grp", parent=True) == [above]
    for joint in finger:
        assert cmds.listConnections(joint, type="parentConstraint")


def test_end_control_off_leaves_the_end_joint_without_a_control(finger):
    created = rig.get("fk_chain").build(_params(end_control=False))

    assert created["controls"] == ", ".join(CONTROLS[:3])
    assert not cmds.objExists("L_finger_04_fk_ctrl")
    assert not cmds.objExists("L_finger_04_fk_ctrl_grp")
    assert not cmds.listConnections("tip", type="parentConstraint")


def test_two_joint_chain_without_end_control_still_gets_one_control(finger):
    created = rig.get("fk_chain").build(_params(start_joint="tip_base", end_control=False))

    assert created["controls"] == "L_finger_01_fk_ctrl"
    assert not cmds.objExists("L_finger_02_fk_ctrl")


def test_each_control_sits_on_its_joint_matching_its_orientation(finger):
    rig.get("fk_chain").build(_params())

    for control, joint in zip(CONTROLS, finger):
        assert _close([_world(f"{control}_grp"), _world(control)], [_world(joint)] * 2)
        assert _same_orientation(f"{control}_grp", joint), control
        assert _same_orientation(control, joint), control


def test_build_does_not_move_or_rotate_the_joints(finger):
    before = _positions(finger)
    rotations = [_rotation(j) for j in finger]
    local = [cmds.getAttr(f"{j}.rotate")[0] for j in finger]

    rig.get("fk_chain").build(_params())

    assert _close(_positions(finger), before)
    assert all(_rotation(j).isEquivalent(r, 1e-4) for j, r in zip(finger, rotations))
    assert _close([om.MVector(*cmds.getAttr(f"{j}.rotate")[0]) for j in finger], [om.MVector(*r) for r in local])


def test_rotating_the_first_control_carries_the_chain(finger):
    rig.get("fk_chain").build(_params())
    tip_before = _world("tip")

    cmds.rotate(0, 0, 40, CONTROLS[0], relative=True, objectSpace=True)

    assert _close([_world("knuckle")], [_world(CONTROLS[0])])
    assert (_world("tip") - tip_before).length() > 1.0
    # The controls below went with it and still sit on their joints.
    for control, joint in zip(CONTROLS, finger):
        assert _close([_world(control)], [_world(joint)])
        assert _same_orientation(control, joint), control


def test_rotating_a_middle_control_rotates_its_joint_only_from_there_down(finger):
    rig.get("fk_chain").build(_params())
    knuckle = _rotation("knuckle")
    middle_position = _world("middle")
    tip_before = _world("tip")

    cmds.rotate(0, 30, 0, CONTROLS[1], relative=True, objectSpace=True)

    assert _same_orientation("middle", CONTROLS[1])
    assert not _rotation("middle").isEquivalent(_rotation("knuckle"), 1e-4)
    assert _rotation("knuckle").isEquivalent(knuckle, 1e-4)
    assert _close([_world("middle")], [middle_position])
    assert (_world("tip") - tip_before).length() > 0.5


def _color(control):
    """``(overrideEnabled, overrideColor)`` of each curve shape under ``control``."""
    shapes = cmds.listRelatives(control, shapes=True, type="nurbsCurve")
    return {(cmds.getAttr(f"{s}.overrideEnabled"), cmds.getAttr(f"{s}.overrideColor")) for s in shapes}


def test_color_goes_on_every_control(finger):
    rig.get("fk_chain").build(_params(color=13))

    for control in CONTROLS:
        assert _color(control) == {(True, 13)}, control


def test_color_0_leaves_the_controls_maya_default_color(finger):
    rig.get("fk_chain").build(_params(color=0))

    for control in CONTROLS:
        assert _color(control) == {(False, 0)}, control


def test_build_goes_under_the_parent(finger):
    cmds.group(empty=True, name="rig_grp")

    rig.get("fk_chain").build(_params(parent="rig_grp"))

    assert cmds.listRelatives("L_finger_fkChain_grp", parent=True) == ["rig_grp"]


def _shape_box(control):
    """World bounding box of ``control``'s own curve, without the controls below it."""
    return cmds.exactWorldBoundingBox(cmds.listRelatives(control, shapes=True, fullPath=True))


def test_control_size_scales_the_controls(finger):
    rig.get("fk_chain").build(_params(name="small", control_size=1.0))
    small = _shape_box("small_01_fk_ctrl")
    cmds.delete("small_fkChain_grp")
    rig.get("fk_chain").build(_params(name="big", control_size=2.0))
    big = _shape_box("big_01_fk_ctrl")

    big_size = max(big[i + 3] - big[i] for i in range(3))
    small_size = max(small[i + 3] - small[i] for i in range(3))
    assert abs(big_size - 2 * small_size) < 1e-3


def test_build_keeps_the_selection(finger):
    cmds.select("middle")

    rig.get("fk_chain").build(_params())

    assert cmds.ls(selection=True) == ["middle"]


def test_build_is_one_undo_step(finger):
    before = _positions(finger)
    cmds.undoInfo(state=True)
    nodes_before = _nodes()

    rig.get("fk_chain").build(_params())
    cmds.rotate(0, 0, 40, CONTROLS[0], relative=True)
    cmds.undo()
    cmds.undo()

    assert _nodes() == nodes_before
    assert _close(_positions(finger), before)


def test_build_with_problems_creates_nothing(finger):
    nodes_before = _nodes()

    with pytest.raises(ValueError):
        rig.get("fk_chain").build(_params(end_joint="nothing"))

    assert _nodes() == nodes_before
