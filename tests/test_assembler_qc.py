"""QC items (.qc): a build step that reports scene problems and changes nothing."""

import json
import os

import pytest
from maya import cmds

from kaiju_suite.core import checks
from kaiju_suite.tools.assembler import logic, plan, products, runlog, versions
from kaiju_suite.tools.assembler.products import qc


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


def test_qc_items_are_qc_files(tmp_path):
    path = qc.create_qc(str(tmp_path), "rig")
    assert path == str(tmp_path / "rig.qc")
    assert products.product_for(path) is qc.PRODUCT
    (entry,) = logic.scan(str(tmp_path))
    assert entry.label == "rig" and entry.type_label == "QC"
    with pytest.raises(FileExistsError):
        qc.create_qc(str(tmp_path), "rig")


def test_qc_is_runnable_and_versioned():
    assert qc.PRODUCT.runnable and qc.PRODUCT.versioned and qc.PRODUCT.can_disable
    assert qc.PRODUCT.utility is None


def test_qc_is_in_the_last_new_menu_group_before_output(tmp_path):
    entries = products.new_menu()
    labels = [None if e is None else e[1].label for e in entries]
    assert labels[-3:] == [None, "QC", "Output"]
    (creator,) = qc.PRODUCT.creators
    assert creator.choices is None and not creator.open_after
    assert creator.fn(str(tmp_path), "rig", None) == str(tmp_path / "rig.qc")


def test_a_new_check_turns_every_check_on(tmp_path):
    path = qc.create_qc(str(tmp_path), "rig")
    assert qc.read_settings(path) == checks.defaults()
    with open(path, encoding="utf-8") as f:
        assert json.load(f)["kaiju"] == "qc"


def test_an_empty_file_uses_the_defaults(tmp_path):
    path = _script(tmp_path, "rig.qc")
    assert qc.read_settings(path) == checks.defaults()


def test_stored_settings_are_read_back_with_defaults_filled_in(tmp_path):
    path = qc.create_qc(str(tmp_path), "rig")
    qc.write_settings(path, {"history": {"enabled": False}, "naming": {"enabled": True, "pattern": ".*_ctrl"}})
    settings = qc.read_settings(path)
    assert settings["history"] == {"enabled": False}
    assert settings["naming"] == {"enabled": True, "pattern": ".*_ctrl"}
    assert settings["unknown"] == {"enabled": True}


def test_bad_settings_are_refused(tmp_path):
    path = qc.create_qc(str(tmp_path), "rig")
    with pytest.raises(ValueError):
        qc.write_settings(path, {"naming": {"pattern": "("}})
    assert qc.read_settings(path) == checks.defaults()


# -- run --------------------------------------------------------------------


def test_run_on_a_clean_scene_succeeds(new_scene, tmp_path):
    path = qc.create_qc(str(tmp_path), "rig")
    assert _statuses([path]) == [("rig.qc", logic.RUNNING), ("rig.qc", logic.SUCCESS)]
    assert "no problems found" in _log_text(path)


def test_run_with_problems_ends_as_warning_and_the_build_goes_on(new_scene, tmp_path):
    _messy_scene()
    path = qc.create_qc(str(tmp_path), "rig")
    after = _script(tmp_path, "z_after.py", "from maya import cmds\ncmds.createNode('transform', name='after_grp')\n")
    assert _statuses([path, after]) == [
        ("rig.qc", logic.RUNNING),
        ("rig.qc", logic.WARNING),
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
    path = qc.create_qc(str(tmp_path), "rig")
    before = _snapshot()
    qc.PRODUCT.run(path)
    logic.run_steps([path])
    assert _snapshot() == before


def test_turned_off_checks_are_not_run(new_scene, tmp_path):
    cmds.createNode("unknown", name="leftover")
    path = qc.create_qc(str(tmp_path), "rig")
    settings = qc.read_settings(path)
    settings["unknown"]["enabled"] = False
    qc.write_settings(path, settings)
    assert _statuses([path])[-1] == ("rig.qc", logic.SUCCESS)


def test_run_uses_the_stored_naming_pattern(new_scene, tmp_path):
    cmds.group(empty=True, name="arm_grp")
    path = qc.create_qc(str(tmp_path), "rig")
    qc.write_settings(path, {"naming": {"enabled": True, "pattern": ".*_ctrl$"}})
    assert _statuses([path])[-1] == ("rig.qc", logic.WARNING)
    assert "arm_grp: doesn't match .*_ctrl$" in _log_text(path)


def test_a_broken_file_stops_the_build(new_scene, tmp_path):
    path = _script(tmp_path, "rig.qc", "not json")
    with pytest.raises(logic.StepError):
        logic.run_steps([path])


# -- double-click panel -----------------------------------------------------


def test_panel_is_a_checklist_with_the_details_on_hover(tmp_path):
    path = qc.create_qc(str(tmp_path), "rig")
    panel = qc.PRODUCT.panel(path)
    assert [t.label for t in panel.toggles] == [c.label for c in checks.CHECKS]
    assert all(t.checked for t in panel.toggles)
    for toggle, check in zip(panel.toggles, checks.CHECKS):
        assert check.description in toggle.tooltip
    naming = panel.toggles[0]
    assert checks.DEFAULT_PATTERN in naming.tooltip
    # The details live in the tooltips, not as lines or per-check buttons.
    assert not any(c.description in line for c in checks.CHECKS for line in panel.info)
    # Editors sit on their check's row, not as buttons below the list.
    assert panel.actions == []
    assert naming.edit.label == "Set Naming Pattern..."
    assert all(t.edit is None for t in panel.toggles[1:])
    # Run and Show Log buttons at the bottom of the window.
    assert panel.run_buttons is True


def test_panel_checkboxes_turn_checks_on_and_off(tmp_path):
    path = qc.create_qc(str(tmp_path), "rig")
    unknown = next(t for t in qc.PRODUCT.panel(path).toggles if t.label == "Unknown nodes")
    assert unknown.fn(False) == "Turned off Unknown nodes in rig.qc"
    assert qc.read_settings(path)["unknown"]["enabled"] is False
    assert qc.read_settings(path)["naming"]["enabled"] is True
    unknown = next(t for t in qc.PRODUCT.panel(path).toggles if t.label == "Unknown nodes")
    assert unknown.checked is False
    unknown.fn(True)
    assert qc.read_settings(path)["unknown"]["enabled"] is True


def test_panel_sets_the_naming_pattern(tmp_path, monkeypatch):
    path = qc.create_qc(str(tmp_path), "rig")
    answers = iter([".*_ctrl$", None, "("])
    monkeypatch.setattr(qc, "ask_pattern", lambda current: next(answers))
    action = next(t for t in qc.PRODUCT.panel(path).toggles if t.label == "Naming").edit

    action.fn()
    assert qc.read_settings(path)["naming"]["pattern"] == ".*_ctrl$"
    assert action.fn() is None  # cancelled: nothing changes
    assert qc.read_settings(path)["naming"]["pattern"] == ".*_ctrl$"
    with pytest.raises(ValueError):
        action.fn()
    assert qc.read_settings(path)["naming"]["pattern"] == ".*_ctrl$"


def test_panel_on_a_broken_file_says_so(tmp_path):
    path = _script(tmp_path, "rig.qc", "not json")
    panel = qc.PRODUCT.panel(path)
    assert "not a Kaiju data file" in " ".join(panel.info)
    assert panel.actions == [] and panel.toggles == []
    assert panel.run_buttons is False  # nothing to run until the file is fixed


def test_publish_saves_the_settings_as_a_version(tmp_path):
    path = qc.create_qc(str(tmp_path), "rig")
    versions.publish_action(path).fn()
    assert [v.number for v in versions.list_versions(path)] == [1]


# -- build plans ------------------------------------------------------------


def test_build_plan_round_trip(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    path = qc.create_qc(str(source), "rig")
    qc.write_settings(path, {"history": {"enabled": False}})
    exported = plan.export_plan(str(source))
    (item,) = exported["items"]
    assert item["name"] == "rig.qc"
    assert item["checks"]["history"] == {"enabled": False}

    target = tmp_path / "target"
    target.mkdir()
    plan.import_plan(exported, str(target))
    assert qc.read_settings(str(target / "rig.qc")) == qc.read_settings(path)


def test_build_plan_item_with_no_checks_gets_the_defaults(tmp_path):
    plan.import_plan({"items": [{"name": "rig.qc"}]}, str(tmp_path))
    assert qc.read_settings(str(tmp_path / "rig.qc")) == checks.defaults()


def test_build_plan_problems():
    assert qc.PRODUCT.plan_problems({"name": "rig.qc"}) == []
    assert qc.PRODUCT.plan_problems({"name": "rig.qc", "checks": {"nope": {}}}) == [
        "no check 'nope'; use one of naming, transforms, history, unknown"
    ]
