import pytest
from maya import cmds

from kaiju_suite import rig
from kaiju_suite.rig import space_switch


def _params(**overrides):
    params = rig.get("space_switch").defaults()
    params.update(
        {
            "control": "hand_ctrl",
            "driven": "hand_ctrl_grp",
            "spaces": "world=world_space, chest=chest_ctrl, head=head_ctrl",
            "default_space": "",
        }
    )
    params.update(overrides)
    return params


def _scene():
    """Three space targets and a control under an offset group, all apart."""
    for name, position in (("world_space", (0, 0, 0)), ("chest_ctrl", (0, 10, 0)), ("head_ctrl", (0, 15, 2))):
        node = cmds.createNode("transform", name=name)
        cmds.xform(node, worldSpace=True, translation=position)
    group = cmds.createNode("transform", name="hand_ctrl_grp")
    cmds.xform(group, worldSpace=True, translation=(5, 8, 1))
    control = cmds.createNode("transform", name="hand_ctrl", parent=group)
    cmds.setAttr(f"{control}.translateX", 1)
    cmds.setAttr(f"{control}.rotateZ", 30)


def _world(node):
    return cmds.xform(node, query=True, worldSpace=True, matrix=True)


def _nodes():
    return set(cmds.ls())


# -- parsing spaces -----------------------------------------------------------


def test_parse_spaces_reads_labels_and_targets():
    assert space_switch.parse_spaces("world=world_space, chest = chest_ctrl\nhead_ctrl") == [
        ("world", "world_space"),
        ("chest", "chest_ctrl"),
        ("head_ctrl", "head_ctrl"),
    ]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("", "at least one"),
        (" , ", "at least one"),
        ("a=b=c", "a=b=c"),
        ("=chest_ctrl", "label"),
        ("chest=", "chest"),
        ("bad label=chest_ctrl", "bad label"),
        ("a=chest_ctrl, a=head_ctrl", "twice"),
        ("a=chest_ctrl, b=chest_ctrl", "chest_ctrl"),
    ],
)
def test_spaces_problems(text, expected):
    problems = space_switch.spaces_problems(text)

    assert any(expected in p for p in problems), problems


# -- parameters ---------------------------------------------------------------


def test_space_switch_parameters():
    module = rig.get("space_switch")

    assert module.name == "Space Switch"
    assert [p.key for p in module.params] == ["control", "driven", "spaces", "default_space"]
    assert {p.key: p.kind for p in module.params} == {
        "control": "node",
        "driven": "node",
        "spaces": "string",
        "default_space": "string",
    }


def test_valid_params_have_no_problems(new_scene):
    _scene()

    assert rig.get("space_switch").problems(_params()) == []


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"control": ""}, "Control"),
        ({"control": "nothing"}, "nothing"),
        ({"driven": "nothing"}, "nothing"),
        ({"driven": "world_space"}, "above"),
        ({"spaces": ""}, "Spaces"),
        ({"spaces": " , "}, "at least one"),
        ({"spaces": "world=nothing"}, "nothing"),
        ({"spaces": "self=hand_ctrl"}, "hand_ctrl"),
        ({"spaces": "grp=hand_ctrl_grp"}, "hand_ctrl_grp"),
        ({"default_space": "moon"}, "moon"),
    ],
)
def test_problems(new_scene, overrides, expected):
    _scene()

    problems = rig.get("space_switch").problems(_params(**overrides))

    assert any(expected in p for p in problems), problems


def test_a_control_that_already_has_a_space_is_a_problem(new_scene):
    _scene()
    rig.get("space_switch").build(_params())

    problems = rig.get("space_switch").problems(_params())

    assert any("space" in p and "hand_ctrl" in p for p in problems), problems


def test_a_driven_group_with_connected_channels_is_a_problem(new_scene):
    _scene()
    cmds.connectAttr("chest_ctrl.translateX", "hand_ctrl_grp.translateY")

    problems = rig.get("space_switch").problems(_params())

    assert any("hand_ctrl_grp" in p for p in problems), problems


# -- build --------------------------------------------------------------------


def test_build_adds_a_space_enum_and_a_parent_constraint(new_scene):
    _scene()

    created = rig.get("space_switch").build(_params())

    assert created["control"] == "hand_ctrl"
    assert created["driven"] == "hand_ctrl_grp"
    assert created["spaces"] == ["world", "chest", "head"]
    assert space_switch.spaces("hand_ctrl") == ["world", "chest", "head"]
    assert cmds.attributeQuery("space", node="hand_ctrl", keyable=True)
    constraint = created["constraint"]
    assert cmds.nodeType(constraint) == "parentConstraint"
    assert cmds.listRelatives(constraint, parent=True) == ["hand_ctrl_grp"]
    assert cmds.parentConstraint(constraint, query=True, targetList=True) == ["world_space", "chest_ctrl", "head_ctrl"]


def test_build_does_not_move_the_control(new_scene):
    _scene()
    before = _world("hand_ctrl")

    rig.get("space_switch").build(_params())

    assert _world("hand_ctrl") == pytest.approx(before, abs=1e-4)


def test_default_space_is_the_first_unless_set(new_scene):
    _scene()
    rig.get("space_switch").build(_params(default_space="chest"))

    assert cmds.getAttr("hand_ctrl.space") == 1
    assert cmds.addAttr("hand_ctrl.space", query=True, defaultValue=True) == 1


def test_the_enum_drives_the_constraint_weights(new_scene):
    _scene()
    created = rig.get("space_switch").build(_params())
    constraint = created["constraint"]
    aliases = cmds.parentConstraint(constraint, query=True, weightAliasList=True)

    for index in range(3):
        cmds.setAttr("hand_ctrl.space", index)
        weights = [cmds.getAttr(f"{constraint}.{alias}") for alias in aliases]
        assert weights == [1.0 if i == index else 0.0 for i in range(3)]


def test_the_control_follows_its_current_space(new_scene):
    _scene()
    rig.get("space_switch").build(_params())
    cmds.setAttr("hand_ctrl.space", 1)  # chest
    before = cmds.xform("hand_ctrl", query=True, worldSpace=True, translation=True)

    cmds.move(0, 3, 0, "head_ctrl", relative=True)
    after_head = cmds.xform("hand_ctrl", query=True, worldSpace=True, translation=True)
    cmds.move(4, 0, 0, "chest_ctrl", relative=True)
    after_chest = cmds.xform("hand_ctrl", query=True, worldSpace=True, translation=True)

    assert after_head == pytest.approx(before, abs=1e-4)
    assert after_chest == pytest.approx([before[0] + 4, before[1], before[2]], abs=1e-4)


def test_blank_driven_inserts_a_group_above_the_control(new_scene):
    _scene()
    before = _world("hand_ctrl")

    created = rig.get("space_switch").build(_params(driven=""))

    assert created["driven"] == "hand_ctrl_space_grp"
    assert cmds.listRelatives("hand_ctrl", parent=True) == ["hand_ctrl_space_grp"]
    assert cmds.listRelatives("hand_ctrl_space_grp", parent=True) == ["hand_ctrl_grp"]
    assert _world("hand_ctrl_space_grp") == pytest.approx(_world("hand_ctrl_grp"), abs=1e-4)
    assert _world("hand_ctrl") == pytest.approx(before, abs=1e-4)


def test_build_keeps_the_selection(new_scene):
    _scene()
    cmds.select("head_ctrl")

    rig.get("space_switch").build(_params(driven=""))

    assert cmds.ls(selection=True) == ["head_ctrl"]


def test_build_is_one_undo_step(new_scene):
    _scene()
    cmds.undoInfo(state=True)
    nodes_before = _nodes()

    rig.get("space_switch").build(_params(driven=""))
    cmds.undo()

    assert _nodes() == nodes_before
    assert not cmds.attributeQuery("space", node="hand_ctrl", exists=True)
    assert cmds.listRelatives("hand_ctrl", parent=True) == ["hand_ctrl_grp"]


def test_build_with_problems_creates_nothing(new_scene):
    _scene()
    nodes_before = _nodes()

    with pytest.raises(ValueError):
        rig.get("space_switch").build(_params(spaces="world=nothing"))

    assert _nodes() == nodes_before


# -- switching without a pop --------------------------------------------------


def test_switch_keeps_the_world_transform(new_scene):
    _scene()
    rig.get("space_switch").build(_params())
    cmds.move(0, 5, 0, "chest_ctrl", relative=True)  # so spaces disagree
    cmds.rotate(0, 45, 0, "head_ctrl", relative=True)
    before = _world("hand_ctrl")

    space_switch.switch("hand_ctrl", "head")

    assert cmds.getAttr("hand_ctrl.space") == 2
    assert _world("hand_ctrl") == pytest.approx(before, abs=1e-4)


def test_switch_takes_an_index(new_scene):
    _scene()
    rig.get("space_switch").build(_params())

    space_switch.switch("hand_ctrl", 1)

    assert cmds.getAttr("hand_ctrl.space") == 1


def test_switch_rejects_an_unknown_space(new_scene):
    _scene()
    rig.get("space_switch").build(_params())

    with pytest.raises(ValueError):
        space_switch.switch("hand_ctrl", "moon")


def test_spaces_of_a_node_without_a_space_is_empty(new_scene):
    _scene()

    assert space_switch.spaces("hand_ctrl") == []
