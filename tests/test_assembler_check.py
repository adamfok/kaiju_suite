"""Check items (.chk): a build step that reports scene problems and changes nothing."""

import json
import os

import pytest
from maya import cmds

from kaiju_suite.core import checks
from kaiju_suite.tools.assembler import logic, plan, products, runlog, versions
from kaiju_suite.tools.assembler.products import check


def _snapshot():
    nodes = sorted(cmds.ls(long=True))
    values = {
        node: [cmds.getAttr(f"{node}.{attr}")[0] for attr in ("translate", "rotate", "scale")]
        for node in cmds.ls(type="transform", long=True)
    }
    return nodes, values, cmds.ls(selection=True, long=True)


def _messy_scene():
    cmds.polyCube(name="pCube1")
    cmds.setAttr("pCube1.translateX", 1)
    cmds.createNode("unknown", name="leftover")


def _script(folder, name, code=""):
    path = os.path.join(str(folder), name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    return path


def _statuses(paths):
    seen = []
    logic.run_steps(paths, on_status=lambda path, status: seen.append((os.path.basename(path), status)))
    return seen


def _log_text(path):
    return "\n".join(line for _, line in runlog.read(path))


# -- the item ---------------------------------------------------------------


def test_check_items_are_chk_files(tmp_path):
    path = check.create_check(str(tmp_path), "rig")
    assert path == str(tmp_path / "rig.chk")
    assert products.product_for(path) is check.PRODUCT
    (entry,) = logic.scan(str(tmp_path))
    assert entry.label == "rig" and entry.type_label == "Check"
    with pytest.raises(FileExistsError):
        check.create_check(str(tmp_path), "rig")


def test_check_is_runnable_and_versioned():
    assert check.PRODUCT.runnable and check.PRODUCT.versioned and check.PRODUCT.can_disable
    assert check.PRODUCT.utility is None


def test_check_is_in_the_last_new_menu_group_before_output(tmp_path):
    entries = products.new_menu()
    labels = [None if e is None else e[1].label for e in entries]
    assert labels[-3:] == [None, "Check", "Output"]
    (creator,) = check.PRODUCT.creators
    assert creator.choices is None and not creator.open_after
    assert creator.fn(str(tmp_path), "rig", None) == str(tmp_path / "rig.chk")


def test_a_new_check_turns_every_check_on(tmp_path):
    path = check.create_check(str(tmp_path), "rig")
    assert check.read_settings(path) == checks.defaults()
    with open(path, encoding="utf-8") as f:
        assert json.load(f)["kaiju"] == "check"


def test_an_empty_file_uses_the_defaults(tmp_path):
    path = _script(tmp_path, "rig.chk")
    assert check.read_settings(path) == checks.defaults()


def test_stored_settings_are_read_back_with_defaults_filled_in(tmp_path):
    path = check.create_check(str(tmp_path), "rig")
    check.write_settings(path, {"history": {"enabled": False}, "naming": {"enabled": True, "pattern": ".*_ctrl"}})
    settings = check.read_settings(path)
    assert settings["history"] == {"enabled": False}
    assert settings["naming"] == {"enabled": True, "pattern": ".*_ctrl"}
    assert settings["unknown"] == {"enabled": True}


def test_bad_settings_are_refused(tmp_path):
    path = check.create_check(str(tmp_path), "rig")
    with pytest.raises(ValueError):
        check.write_settings(path, {"naming": {"pattern": "("}})
    assert check.read_settings(path) == checks.defaults()


# -- run --------------------------------------------------------------------


def test_run_on_a_clean_scene_succeeds(new_scene, tmp_path):
    path = check.create_check(str(tmp_path), "rig")
    assert _statuses([path]) == [("rig.chk", logic.RUNNING), ("rig.chk", logic.SUCCESS)]
    assert "no problems found" in _log_text(path)


def test_run_with_problems_ends_as_warning_and_the_build_goes_on(new_scene, tmp_path):
    _messy_scene()
    path = check.create_check(str(tmp_path), "rig")
    after = _script(tmp_path, "z_after.py", "from maya import cmds\ncmds.createNode('transform', name='after_grp')\n")
    assert _statuses([path, after]) == [
        ("rig.chk", logic.RUNNING),
        ("rig.chk", logic.WARNING),
        ("z_after.py", logic.RUNNING),
        ("z_after.py", logic.SUCCESS),
    ]
    assert cmds.objExists("after_grp")
    lines = runlog.read(path)
    warnings = [text for level, text in lines if level == runlog.WARNING]
    text = "\n".join(warnings)
    assert "Naming" in text and "pCube1" in text
    assert "Unfrozen transforms" in text
    assert "Construction history" in text and "polyCube" in text
    assert "Unknown nodes" in text and "leftover" in text
    assert not any(level == runlog.ERROR for level, _ in lines)
    assert (None, "Status: warning") in lines


def test_run_changes_nothing_in_the_scene(new_scene, tmp_path):
    _messy_scene()
    cmds.circle(name="arm_ctrl")
    cmds.select("pCube1")
    path = check.create_check(str(tmp_path), "rig")
    before = _snapshot()
    check.PRODUCT.run(path)
    logic.run_steps([path])
    assert _snapshot() == before


def test_turned_off_checks_are_not_run(new_scene, tmp_path):
    cmds.createNode("unknown", name="leftover")
    path = check.create_check(str(tmp_path), "rig")
    settings = check.read_settings(path)
    settings["unknown"]["enabled"] = False
    check.write_settings(path, settings)
    assert _statuses([path])[-1] == ("rig.chk", logic.SUCCESS)


def test_run_uses_the_stored_naming_pattern(new_scene, tmp_path):
    cmds.group(empty=True, name="arm_grp")
    path = check.create_check(str(tmp_path), "rig")
    check.write_settings(path, {"naming": {"enabled": True, "pattern": ".*_ctrl$"}})
    assert _statuses([path])[-1] == ("rig.chk", logic.WARNING)
    assert "arm_grp: doesn't match .*_ctrl$" in _log_text(path)


def test_a_broken_file_stops_the_build(new_scene, tmp_path):
    path = _script(tmp_path, "rig.chk", "not json")
    with pytest.raises(logic.StepError):
        logic.run_steps([path])


# -- double-click panel -----------------------------------------------------


def test_panel_lists_the_checks_and_toggles_them(tmp_path):
    path = check.create_check(str(tmp_path), "rig")
    panel = check.PRODUCT.panel(path)
    info = "\n".join(panel.info)
    assert "Naming: on" in info and checks.DEFAULT_PATTERN in info
    assert "Unknown nodes: on" in info

    toggle = next(a for a in panel.actions if a.label == "Turn Off Unknown nodes")
    toggle.fn()
    assert check.read_settings(path)["unknown"]["enabled"] is False
    panel = check.PRODUCT.panel(path)
    assert "Unknown nodes: off" in "\n".join(panel.info)
    assert any(a.label == "Turn On Unknown nodes" for a in panel.actions)


def test_panel_sets_the_naming_pattern(tmp_path, monkeypatch):
    path = check.create_check(str(tmp_path), "rig")
    answers = iter([".*_ctrl$", None, "("])
    monkeypatch.setattr(check, "ask_pattern", lambda current: next(answers))
    action = next(a for a in check.PRODUCT.panel(path).actions if a.label == "Set Naming Pattern...")

    action.fn()
    assert check.read_settings(path)["naming"]["pattern"] == ".*_ctrl$"
    assert action.fn() is None  # cancelled: nothing changes
    assert check.read_settings(path)["naming"]["pattern"] == ".*_ctrl$"
    with pytest.raises(ValueError):
        action.fn()
    assert check.read_settings(path)["naming"]["pattern"] == ".*_ctrl$"


def test_panel_on_a_broken_file_says_so(tmp_path):
    path = _script(tmp_path, "rig.chk", "not json")
    panel = check.PRODUCT.panel(path)
    assert "not a Kaiju data file" in " ".join(panel.info)
    assert panel.actions == []


def test_publish_saves_the_settings_as_a_version(tmp_path):
    path = check.create_check(str(tmp_path), "rig")
    versions.publish_action(path).fn()
    assert [v.number for v in versions.list_versions(path)] == [1]


# -- build plans ------------------------------------------------------------


def test_build_plan_round_trip(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    path = check.create_check(str(source), "rig")
    check.write_settings(path, {"history": {"enabled": False}})
    exported = plan.export_plan(str(source))
    (item,) = exported["items"]
    assert item["name"] == "rig.chk"
    assert item["checks"]["history"] == {"enabled": False}

    target = tmp_path / "target"
    target.mkdir()
    plan.import_plan(exported, str(target))
    assert check.read_settings(str(target / "rig.chk")) == check.read_settings(path)


def test_build_plan_item_with_no_checks_gets_the_defaults(tmp_path):
    plan.import_plan({"items": [{"name": "rig.chk"}]}, str(tmp_path))
    assert check.read_settings(str(tmp_path / "rig.chk")) == checks.defaults()


def test_build_plan_problems():
    assert check.PRODUCT.plan_problems({"name": "rig.chk"}) == []
    assert check.PRODUCT.plan_problems({"name": "rig.chk", "checks": {"nope": {}}}) == [
        "no check 'nope'; use one of naming, transforms, history, unknown"
    ]
