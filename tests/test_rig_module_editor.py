import pytest
from maya import cmds

from kaiju_suite import rigging
from kaiju_suite.rigging import spec
from kaiju_suite.tools.rig_module_editor import logic


@pytest.fixture
def ik_file(tmp_path):
    path = str(tmp_path / "L_arm.rig")
    spec.write(path, "simple_ik", {"name": "L_arm", "start_joint": "shoulder"})
    return path


def test_load_gives_the_rig_module_and_complete_params(ik_file):
    rig_module, params = logic.load(ik_file)

    assert rig_module is rigging.get_rig_module("simple_ik")
    assert params["name"] == "L_arm"
    assert params["pole_distance"] == 5.0


def test_save_writes_the_params(ik_file):
    rig_module, params = logic.load(ik_file)
    params["end_joint"] = "wrist"

    logic.save(ik_file, rig_module, params)

    assert spec.read(ik_file)[1]["end_joint"] == "wrist"


def test_save_keeps_params_the_editor_does_not_know(ik_file):
    spec.write(ik_file, "simple_ik", {"name": "L_arm", "from_the_future": 1})
    rig_module, params = logic.load(ik_file)

    logic.save(ik_file, rig_module, params)

    assert spec.read(ik_file)[1]["from_the_future"] == 1


def test_matches_file_tells_unsaved_edits_apart(ik_file):
    rig_module, params = logic.load(ik_file)
    assert logic.matches_file(ik_file, rig_module, params)

    params["name"] = "R_arm"
    assert not logic.matches_file(ik_file, rig_module, params)


def test_matches_file_is_false_for_an_unreadable_file(tmp_path):
    path = tmp_path / "bad.rig"
    path.write_text("not json", encoding="utf-8")

    assert not logic.matches_file(str(path), rigging.get_rig_module("simple_ik"), rigging.get_rig_module("simple_ik").defaults())


def test_pick_selection_gives_the_selected_nodes_name(new_scene):
    cmds.select(cmds.createNode("joint", name="shoulder"))

    assert logic.pick_selection() == "shoulder"


def test_pick_selection_gives_a_unique_name_when_names_clash(new_scene):
    cmds.createNode("joint", name="wrist")
    group = cmds.group(empty=True, name="other")
    cmds.select(cmds.createNode("joint", name="wrist", parent=group))

    assert logic.pick_selection() == "other|wrist"


def test_pick_selection_needs_a_selection(new_scene):
    with pytest.raises(ValueError) as info:
        logic.pick_selection()
    assert "Nothing selected" in str(info.value)


def test_problems_come_from_the_rig_module(new_scene, ik_file):
    rig_module, params = logic.load(ik_file)

    assert any("End joint is required" in p for p in logic.problems(rig_module, params))

    params["end_joint"] = "wrist"
    assert any("shoulder" in p for p in logic.problems(rig_module, params))


def test_colors_are_maya_index_colors_with_their_rgb():
    assert list(logic.COLORS) == list(range(32))
    assert logic.color_rgb(13) == pytest.approx((1.0, 0.0, 0.0))
    assert logic.color_rgb(6) == pytest.approx((0.0, 0.0, 1.0))
