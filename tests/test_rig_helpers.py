import pytest
from maya import cmds

from kaiju_suite.rig import helpers


def _joint(name, parent=None, translate=(0, 0, 0)):
    node = cmds.createNode("joint", name=name, parent=parent, skipSelect=True)
    cmds.setAttr(f"{node}.translate", *translate)
    return node


@pytest.fixture
def leg(new_scene):
    _joint("hip")
    _joint("knee", "hip", translate=(0, -5, 1))
    _joint("ankle", "knee", translate=(0, -5, -1))
    return ("hip", "knee", "ankle")


# -- names ------------------------------------------------------------------


@pytest.mark.parametrize("name", ["bad name", "1arm", "", "a-b"])
def test_name_problems_reject_names_maya_cant_use(new_scene, name):
    problems = helpers.name_problems(name, f"{name}_grp", "Thing")

    assert any("Name" in p for p in problems), problems


def test_name_problems_report_an_existing_group(new_scene):
    cmds.group(empty=True, name="L_leg_fk_grp")

    problems = helpers.name_problems("L_leg", "L_leg_fk_grp", "FK Chain")

    assert any("L_leg_fk_grp" in p and "FK Chain" in p for p in problems), problems


def test_name_problems_pass_a_free_name(new_scene):
    assert helpers.name_problems("L_leg", "L_leg_fk_grp", "FK Chain") == []


# -- nodes and chains -------------------------------------------------------


def test_node_problems(leg):
    cmds.spaceLocator(name="loc")
    cmds.group(empty=True, name="other")
    _joint("knee", "other")

    assert helpers.node_problems("Joint", "hip", joint=True) == []
    assert "isn't in the scene" in helpers.node_problems("Joint", "nope", joint=True)[0]
    assert "not a joint" in helpers.node_problems("Joint", "loc", joint=True)[0]
    assert "Several" in helpers.node_problems("Joint", "knee", joint=True)[0]
    assert helpers.node_problems("Parent", "loc") == []


def test_parent_problems_allow_blank(leg):
    assert helpers.parent_problems("") == []
    assert helpers.parent_problems("  ") == []
    assert "nope" in helpers.parent_problems("nope")[0]


def test_chain_runs_from_start_to_end(leg):
    chain = helpers.chain("hip", "ankle")

    assert [helpers.short(n) for n in chain] == ["hip", "knee", "ankle"]
    assert helpers.chain("ankle", "hip") is None
    assert [helpers.short(n) for n in helpers.chain("knee", "knee")] == ["knee"]


@pytest.mark.parametrize(
    "start, end, minimum, expected",
    [
        ("hip", "nope", 2, "isn't in the scene"),
        ("ankle", "hip", 2, "not below"),
        ("hip", "knee", 3, "at least 3 joints"),
        ("knee", "knee", 2, "not below"),
    ],
)
def test_chain_problems(leg, start, end, minimum, expected):
    problems = helpers.chain_problems(start, end, minimum)

    assert any(expected in p for p in problems), problems


def test_chain_problems_pass_a_good_chain(leg):
    assert helpers.chain_problems("hip", "ankle", 3) == []
    assert helpers.chain_problems("knee", "knee", 1) == []


def test_chain_problems_reject_a_non_joint_in_the_chain(new_scene):
    _joint("a")
    cmds.group(empty=True, name="gap", parent="a")
    _joint("b", "gap")

    problems = helpers.chain_problems("a", "b", 2)

    assert any("gap" in p for p in problems), problems


# -- building ---------------------------------------------------------------


def test_group_goes_under_the_parent_or_the_world(new_scene):
    cmds.group(empty=True, name="rig")

    assert helpers.group("a_grp") == "a_grp"
    assert not cmds.listRelatives("a_grp", parent=True)
    assert helpers.group("b_grp", "rig") == "b_grp"
    assert cmds.listRelatives("b_grp", parent=True) == ["rig"]


@pytest.mark.parametrize("shape", ["circle", "diamond", "box"])
def test_control_shapes_are_curves_under_the_parent(new_scene, shape):
    cmds.group(empty=True, name="ctrl_grp")

    control = getattr(helpers, shape)("ctrl", 2.0, "ctrl_grp")

    assert control == "ctrl"
    assert cmds.listRelatives(control, parent=True) == ["ctrl_grp"]
    assert cmds.listRelatives(control, shapes=True, type="nurbsCurve")


def test_set_color_overrides_every_curve_shape(new_scene):
    control = helpers.circle("ctrl", 1.0, cmds.group(empty=True, name="g"))

    helpers.set_color(control, 6)

    (shape,) = cmds.listRelatives(control, shapes=True)
    assert cmds.getAttr(f"{shape}.overrideEnabled") is True
    assert cmds.getAttr(f"{shape}.overrideColor") == 6


def test_set_color_0_leaves_the_default(new_scene):
    control = helpers.circle("ctrl", 1.0, cmds.group(empty=True, name="g"))

    helpers.set_color(control, 0)

    (shape,) = cmds.listRelatives(control, shapes=True)
    assert cmds.getAttr(f"{shape}.overrideEnabled") is False


def test_kept_selection_restores_the_selection(new_scene):
    cmds.group(empty=True, name="a")
    cmds.select("a")

    with helpers.kept_selection():
        cmds.group(empty=True, name="b")
        cmds.select("b")

    assert cmds.ls(selection=True) == ["a"]


def test_pole_position_is_out_from_the_middle_joint_on_the_bend_side(leg):
    pole = helpers.pole_position(helpers.chain("hip", "ankle"), 3.0)

    knee = helpers.world("knee")
    assert abs((pole - knee).length() - 3.0) < 1e-6
    assert abs(pole.x) < 1e-6 and pole.z > knee.z  # the knee bends toward +Z


def test_pole_position_is_none_for_a_straight_chain(new_scene):
    _joint("a")
    _joint("b", "a", translate=(5, 0, 0))
    _joint("c", "b", translate=(5, 0, 0))

    assert helpers.pole_position(helpers.chain("a", "c"), 3.0) is None
