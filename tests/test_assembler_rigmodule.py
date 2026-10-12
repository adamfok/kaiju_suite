import os

import pytest
from maya import cmds

from kaiju_suite import rigging
from kaiju_suite.core.datafile import DataFormatError
from kaiju_suite.rigging import spec
from kaiju_suite.tools.assembler import logic, products, runlog, versions
from kaiju_suite.tools.assembler.products import rigmodule


def _joint(name, parent=None, translate=(0, 0, 0)):
    node = cmds.createNode("joint", name=name, parent=parent, skipSelect=True)
    cmds.setAttr(f"{node}.translate", *translate)


@pytest.fixture
def arm(new_scene):
    _joint("shoulder", translate=(0, 10, 0))
    _joint("elbow", "shoulder", translate=(5, 0, -1))
    _joint("wrist", "elbow", translate=(5, 0, 1))


def _creator(label):
    return next(c for p, c in filter(None, products.new_menu()) if p is rigmodule.PRODUCT and c.label == label)


def _item(tmp_path, **params):
    """A new Simple IK item, L_arm.rig, with ``params`` changed."""
    path = _creator("Simple IK").fn(str(tmp_path), "L_arm", None)
    module_key, saved = spec.read(path)
    saved.update(params)
    spec.write(path, module_key, saved)
    return path


def test_rig_items_are_rig_module_files(tmp_path):
    path = str(tmp_path / "L_arm.rig")
    spec.write(path, "simple_ik", {})

    assert products.product_for(path) is rigmodule.PRODUCT
    assert rigmodule.PRODUCT.name == "Rig Module"


def test_type_column_shows_the_module_not_rig_module(tmp_path):
    spec.write(str(tmp_path / "L_arm.rig"), "simple_ik", {})

    (entry,) = logic.scan(str(tmp_path))

    assert entry.label == "L_arm" and entry.type_label == "Simple IK"


@pytest.mark.parametrize("content", ["", "not json"])
def test_type_column_falls_back_to_rig_module_for_an_unreadable_file(tmp_path, content):
    (tmp_path / "L_arm.rig").write_text(content, encoding="utf-8")

    (entry,) = logic.scan(str(tmp_path))

    assert entry.type_label == "Rig Module"


def test_type_column_falls_back_to_rig_module_for_an_unknown_module(tmp_path):
    spec.write(str(tmp_path / "L_arm.rig"), "nope", {})

    (entry,) = logic.scan(str(tmp_path))

    assert entry.type_label == "Rig Module"


def test_publish_message_and_run_log_name_the_module(arm, tmp_path):
    path = _item(tmp_path, start_joint="shoulder", end_joint="wrist")

    message = versions.publish_action(path).fn()
    logic.run_steps([path])

    assert message == "Published Simple IK L_arm.rig v001"
    assert "Simple IK: L_arm.rig" in [line for _level, line in runlog.read(path)]


def test_rig_module_is_runnable_versioned_and_opens_the_editor():
    product = rigmodule.PRODUCT

    assert product.runnable and product.can_disable and product.versioned
    assert product.utility == "Rig Module Editor"


def test_new_menu_lists_each_rig_module(tmp_path):
    labels = [c.label for p, c in filter(None, products.new_menu()) if p is rigmodule.PRODUCT]

    assert labels == [m.name for m in rigging.all_modules()]
    assert "Simple IK" in labels


def test_new_item_holds_the_module_defaults(tmp_path):
    path = _creator("Simple IK").fn(str(tmp_path), "L_arm", None)

    assert os.path.basename(path) == "L_arm.rig"
    assert spec.read(path) == ("simple_ik", rigging.get("simple_ik").defaults())


def test_new_item_refuses_a_taken_name(tmp_path):
    _creator("Simple IK").fn(str(tmp_path), "L_arm", None)

    with pytest.raises(FileExistsError):
        _creator("Simple IK").fn(str(tmp_path), "L_arm", None)


def test_run_builds_the_module_from_the_file(arm, tmp_path):
    path = _item(tmp_path, name="L_arm", start_joint="shoulder", end_joint="wrist")

    message = rigmodule.PRODUCT.run(path)

    assert cmds.objExists("L_arm_ik_grp")
    assert "L_arm_ik_grp" in message


def test_run_steps_logs_what_was_built(arm, tmp_path):
    path = _item(tmp_path, name="L_arm", start_joint="shoulder", end_joint="wrist")

    results = logic.run_steps([path])

    assert cmds.objExists("L_arm_ikHandle")
    assert results


def test_run_with_bad_params_stops_and_names_the_problem(arm, tmp_path):
    path = _item(tmp_path, start_joint="shoulder", end_joint="nothing")
    before = set(cmds.ls())

    with pytest.raises(ValueError) as info:
        rigmodule.PRODUCT.run(path)

    assert "nothing" in str(info.value)
    assert set(cmds.ls()) == before


def test_run_with_an_unknown_module_says_so(new_scene, tmp_path):
    path = str(tmp_path / "x.rig")
    spec.write(path, "nope", {})

    with pytest.raises(LookupError) as info:
        rigmodule.PRODUCT.run(path)
    assert "nope" in str(info.value)


def test_publish_saves_the_parameters_as_a_version(tmp_path):
    path = _item(tmp_path, start_joint="shoulder")

    versions.publish_action(path).fn()
    spec.write(path, "simple_ik", {**spec.read(path)[1], "start_joint": "hip"})
    versions.publish_action(path).fn()

    assert sorted(v.number for v in versions.list_versions(path)) == [1, 2]


def test_publish_needs_no_selection(new_scene, tmp_path):
    path = _item(tmp_path)

    assert versions.publish_problems(path) == []


def test_info_shows_the_module_and_its_parameters(tmp_path):
    path = _item(tmp_path, name="L_arm", start_joint="shoulder", end_joint="wrist")

    info = rigmodule.PRODUCT.panel(path).info

    assert info[0] == "Simple IK"
    assert "Name: L_arm" in info
    assert "Start joint: shoulder" in info
    assert not any(line.startswith(("Solver", "Pole vector:")) for line in info)
    assert "Parent: (none)" in info
    assert logic.has_info(rigmodule.PRODUCT)


def test_info_on_a_broken_file_says_so(tmp_path):
    path = tmp_path / "bad.rig"
    path.write_text("not json", encoding="utf-8")

    (line,) = rigmodule.PRODUCT.panel(str(path)).info

    assert "bad.rig" in line


def test_load_reports_a_wrong_kind_of_file(tmp_path):
    path = str(tmp_path / "x.rig")
    from kaiju_suite.core import datafile

    datafile.write(path, "joints", {"joints": []})

    with pytest.raises(DataFormatError):
        rigmodule.PRODUCT.run(path)


# -- Mirror ----------------------------------------------------------------------


def _mirror_action(path):
    return next((a for a in rigmodule.PRODUCT.actions(path) if a.label == "Mirror"), None)


@pytest.fixture
def both_arms(new_scene):
    """L_ and R_ arm joints, mirrored across X."""
    for side, x in (("L", 1), ("R", -1)):
        _joint(f"{side}_shoulder", translate=(2 * x, 10, 0))
        _joint(f"{side}_elbow", f"{side}_shoulder", translate=(5 * x, 0, -1))
        _joint(f"{side}_wrist", f"{side}_elbow", translate=(5 * x, 0, 1))


def _l_arm(tmp_path, **params):
    return _item(tmp_path, name="L_arm", start_joint="L_shoulder", end_joint="L_wrist", **params)


def test_mirror_writes_the_opposite_item_with_flipped_parameters(both_arms, tmp_path):
    path = _l_arm(tmp_path, parent="main_offset_ctrl", pole_distance=7.5)

    message = _mirror_action(path).fn()

    mirrored = str(tmp_path / "R_arm.rig")
    key, params = spec.read(mirrored)
    assert key == "simple_ik"
    assert params["name"] == "R_arm"
    assert params["start_joint"] == "R_shoulder" and params["end_joint"] == "R_wrist"
    assert params["parent"] == "main_offset_ctrl"  # no side: unchanged
    assert params["pole_distance"] == 7.5
    assert "R_arm.rig" in message


def test_mirror_places_the_new_item_right_after_the_source(both_arms, tmp_path):
    spec.write(str(tmp_path / "a_first.rig"), "simple_ik", {})
    path = _l_arm(tmp_path)
    spec.write(str(tmp_path / "z_last.rig"), "simple_ik", {})
    logic.append_to_order(str(tmp_path), ["a_first.rig", "L_arm.rig", "z_last.rig"])

    _mirror_action(path).fn()

    assert logic.item_names(str(tmp_path)) == ["a_first.rig", "L_arm.rig", "R_arm.rig", "z_last.rig"]


def test_mirror_saves_the_new_item_as_its_first_version(both_arms, tmp_path):
    path = _l_arm(tmp_path)

    _mirror_action(path).fn()

    mirrored = str(tmp_path / "R_arm.rig")
    assert versions.current_version(mirrored).number == 1


def test_mirror_again_updates_the_existing_item_as_a_new_version(both_arms, tmp_path):
    path = _l_arm(tmp_path)
    _mirror_action(path).fn()
    key, params = spec.read(path)
    params["pole_distance"] = 12.0
    spec.write(path, key, params)

    _mirror_action(path).fn()

    mirrored = str(tmp_path / "R_arm.rig")
    assert spec.read(mirrored)[1]["pole_distance"] == 12.0
    assert [v.number for v in versions.list_versions(mirrored)] == [2, 1]
    assert logic.item_names(str(tmp_path)) == ["L_arm.rig", "R_arm.rig"]
    versions.restore_version(mirrored, 1)
    assert spec.read(mirrored)[1]["pole_distance"] == 5.0


def test_mirror_works_from_the_right_side_too(both_arms, tmp_path):
    path = _item(tmp_path, name="R_arm", start_joint="R_shoulder", end_joint="R_wrist")
    os.rename(path, str(tmp_path / "arm_R.rig"))

    _mirror_action(str(tmp_path / "arm_R.rig")).fn()

    params = spec.read(str(tmp_path / "arm_L.rig"))[1]
    assert (params["name"], params["start_joint"]) == ("L_arm", "L_shoulder")


def test_mirror_of_an_unsided_item_adds_mirrored(new_scene, tmp_path):
    _joint("spine_01")
    _joint("spine_02", "spine_01", translate=(0, 2, 0))
    path = _creator("FK Chain").fn(str(tmp_path), "spine", None)
    spec.write(path, "fk_chain", {"name": "spine", "start_joint": "spine_01", "end_joint": "spine_02"})

    message = _mirror_action(path).fn()

    params = spec.read(str(tmp_path / "spine_mirrored.rig"))[1]
    assert params["name"] == "spine_mirrored"
    assert (params["start_joint"], params["end_joint"]) == ("spine_01", "spine_02")
    assert "spine_01" in message and "same" in message


def test_mirror_of_a_mirrored_copy_goes_back_to_the_original(new_scene, tmp_path):
    _joint("spine_01")
    _joint("spine_02", "spine_01", translate=(0, 2, 0))
    path = _creator("FK Chain").fn(str(tmp_path), "spine", None)
    spec.write(path, "fk_chain", {"name": "spine", "start_joint": "spine_01", "end_joint": "spine_02"})
    _mirror_action(path).fn()

    _mirror_action(str(tmp_path / "spine_mirrored.rig")).fn()

    assert sorted(n for n in os.listdir(tmp_path) if not n.startswith(".")) == ["spine.rig", "spine_mirrored.rig"]


def test_root_has_no_mirror(tmp_path):
    path = _creator("Root").fn(str(tmp_path), "main", None)

    assert _mirror_action(path) is None
    assert rigging.get("root").mirrorable is False
    assert all(m.mirrorable for m in rigging.all_modules() if m.key != "root")


def test_mirror_stops_and_names_missing_opposite_joints(arm, tmp_path):
    cmds.rename("shoulder", "L_shoulder")
    path = _item(tmp_path, name="L_arm", start_joint="L_shoulder", end_joint="L_wrist")
    cmds.rename("wrist", "L_wrist")
    action = _mirror_action(path)

    problems = action.problems()

    assert any("R_shoulder" in p for p in problems) and any("R_wrist" in p for p in problems)
    with pytest.raises(ValueError, match="R_shoulder"):
        action.fn()
    assert not os.path.exists(str(tmp_path / "R_arm.rig"))


def test_mirror_refuses_to_overwrite_a_different_kind_of_item(both_arms, tmp_path):
    path = _l_arm(tmp_path)
    spec.write(str(tmp_path / "R_arm.rig"), "fk_chain", {})

    assert any("FK Chain" in p for p in _mirror_action(path).problems())


def test_mirrored_build_on_a_behavior_mirrored_skeleton_mirrors_control_behavior(new_scene, tmp_path):
    """Rotating both sides' controls by the same amount gives mirror-image poses."""
    _joint("L_upper", translate=(2, 10, 0))
    _joint("L_lower", "L_upper", translate=(4, 0, -1))
    _joint("L_tip", "L_lower", translate=(3, 0, 1))
    cmds.joint("L_upper", edit=True, orientJoint="xyz", secondaryAxisOrient="yup", children=True, zeroScaleOrient=True)
    cmds.mirrorJoint("L_upper", mirrorYZ=True, mirrorBehavior=True, searchReplace=("L_", "R_"))
    path = _creator("FK Chain").fn(str(tmp_path), "L_limb", None)
    spec.write(path, "fk_chain", {"name": "L_limb", "start_joint": "L_upper", "end_joint": "L_tip"})
    _mirror_action(path).fn()

    logic.run_steps([path, str(tmp_path / "R_limb.rig")])
    for side in "LR":
        cmds.setAttr(f"{side}_limb_01_fk_ctrl.rotate", 10, 20, 30)
        cmds.setAttr(f"{side}_limb_02_fk_ctrl.rotate", -15, 5, 25)

    for joint in ("upper", "lower", "tip"):
        lx, ly, lz = cmds.xform(f"L_{joint}", query=True, worldSpace=True, translation=True)
        rx, ry, rz = cmds.xform(f"R_{joint}", query=True, worldSpace=True, translation=True)
        assert (rx, ry, rz) == pytest.approx((-lx, ly, lz), abs=1e-4)
