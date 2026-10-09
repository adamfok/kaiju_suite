import os

import pytest
from maya import cmds

from kaiju_suite import rig
from kaiju_suite.core.datafile import DataFormatError
from kaiju_suite.rig import spec
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

    assert labels == [m.name for m in rig.all_modules()]
    assert "Simple IK" in labels


def test_new_item_holds_the_module_defaults(tmp_path):
    path = _creator("Simple IK").fn(str(tmp_path), "L_arm", None)

    assert os.path.basename(path) == "L_arm.rig"
    assert spec.read(path) == ("simple_ik", rig.get("simple_ik").defaults())


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
