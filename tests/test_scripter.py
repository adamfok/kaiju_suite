"""Kaiju Scripter logic: the tree, its order and enabled flags, and Run."""

import json
import os

import __main__
import pytest
from maya import cmds

from kaiju_suite.core import settings
from kaiju_suite.tools.scripter import logic


def _write(path, text=""):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return str(path)


def _script(folder, name, text=None):
    """A script that appends its name to ``__main__.ran`` (plus ``text``)."""
    body = f"import __main__\n__main__.ran.append({name!r})\n" if text is None else text
    return _write(os.path.join(str(folder), f"{name}.py"), body)


@pytest.fixture
def ran():
    __main__.ran = []
    yield __main__.ran
    del __main__.ran


def _names(entries):
    return [e.name for e in entries]


# -- the tree ---------------------------------------------------------------


def test_scan_lists_scripts_folders_separators_and_breakpoints(tmp_path):
    _script(tmp_path, "b")
    _script(tmp_path, "a")
    _write(tmp_path / "rig.sep")
    _write(tmp_path / "stop.brk")
    _write(tmp_path / "notes.txt")
    _write(tmp_path / "old.mel")
    (tmp_path / "arms").mkdir()
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / ".hidden").mkdir()

    entries = logic.scan(str(tmp_path))

    assert _names(entries) == ["a.py", "arms", "b.py", "rig.sep", "stop.brk"]
    kinds = {e.name: e.kind for e in entries}
    assert kinds == {
        "a.py": logic.SCRIPT,
        "arms": logic.FOLDER,
        "b.py": logic.SCRIPT,
        "rig.sep": logic.SEPARATOR,
        "stop.brk": logic.BREAKPOINT,
    }
    assert [e.label for e in entries] == ["a", "arms", "b", "rig", "stop"]


def test_scan_nests_folders(tmp_path):
    (tmp_path / "arms").mkdir()
    _script(tmp_path / "arms", "left")
    [arms] = logic.scan(str(tmp_path))
    assert _names(arms.children) == ["left.py"]


def test_new_items_go_where_asked_and_the_order_is_kept_in_scripter_folder(tmp_path):
    first = logic.create_item(logic.SCRIPT, str(tmp_path), "first")
    logic.create_item(logic.SCRIPT, str(tmp_path), "last")
    logic.create_item(logic.SEPARATOR, str(tmp_path), "zzz", index=1)

    assert _names(logic.scan(str(tmp_path))) == ["first.py", "zzz.sep", "last.py"]
    assert first == os.path.join(str(tmp_path), "first.py")
    with open(tmp_path / ".scripter" / "order.json", encoding="utf-8") as f:
        assert json.load(f)["order"] == ["first.py", "zzz.sep", "last.py"]
    assert not (tmp_path / ".assembler.json").exists()


def test_create_each_kind(tmp_path):
    folder = logic.create_item(logic.FOLDER, str(tmp_path), "arms")
    script = logic.create_item(logic.SCRIPT, str(tmp_path), "setup.py")
    assert os.path.isdir(folder)
    assert script.endswith("setup.py")  # the extension isn't doubled
    assert logic.create_item(logic.BREAKPOINT, str(tmp_path), "stop").endswith("stop.brk")
    assert logic.create_item(logic.SEPARATOR, str(tmp_path), "rig").endswith("rig.sep")


def test_create_refuses_bad_or_taken_names(tmp_path):
    logic.create_item(logic.SCRIPT, str(tmp_path), "setup")
    with pytest.raises(FileExistsError):
        logic.create_item(logic.SCRIPT, str(tmp_path), "setup")
    with pytest.raises(ValueError):
        logic.create_item(logic.SCRIPT, str(tmp_path), "  ")
    with pytest.raises(ValueError):
        logic.create_item(logic.SCRIPT, str(tmp_path), "a/b")


def test_default_name_is_the_kind_then_numbered(tmp_path):
    assert logic.default_name(logic.SCRIPT, str(tmp_path)) == "Script"
    logic.create_item(logic.SCRIPT, str(tmp_path), "Script")
    assert logic.default_name(logic.SCRIPT, str(tmp_path)) == "Script_2"
    assert logic.default_name(logic.BREAKPOINT, str(tmp_path)) == "Breakpoint"


def test_disable_and_enable(tmp_path):
    path = _script(tmp_path, "a")
    assert logic.is_enabled(path)
    logic.set_enabled([path], False)
    assert not logic.is_enabled(path)
    assert [e.enabled for e in logic.scan(str(tmp_path))] == [False]
    logic.set_enabled([path], True)
    assert logic.is_enabled(path)


def test_rename_keeps_place_extension_and_disabled(tmp_path):
    a = logic.create_item(logic.SCRIPT, str(tmp_path), "a")
    logic.create_item(logic.SCRIPT, str(tmp_path), "b")
    logic.set_enabled([a], False)

    new = logic.rename_path(a, "zz")

    assert new == os.path.join(str(tmp_path), "zz.py")
    entries = logic.scan(str(tmp_path))
    assert _names(entries) == ["zz.py", "b.py"]
    assert not entries[0].enabled


def test_place_moves_into_a_folder_keeping_disabled(tmp_path):
    arms = logic.create_item(logic.FOLDER, str(tmp_path), "arms")
    inside = logic.create_item(logic.SCRIPT, arms, "inside")
    a = logic.create_item(logic.SCRIPT, str(tmp_path), "a")
    logic.set_enabled([a], False)

    [moved] = logic.place([a], arms, 0)

    assert moved == os.path.join(arms, "a.py")
    assert _names(logic.scan(arms)) == ["a.py", "inside.py"]
    assert not logic.is_enabled(moved)
    assert _names(logic.scan(str(tmp_path))) == ["arms"]
    assert os.path.isfile(inside)


def test_place_reorders_within_a_folder(tmp_path):
    a, b, c = (logic.create_item(logic.SCRIPT, str(tmp_path), n) for n in "abc")
    logic.place([c], str(tmp_path), 0)
    assert _names(logic.scan(str(tmp_path))) == ["c.py", "a.py", "b.py"]


def test_place_refuses_a_folder_into_itself(tmp_path):
    arms = logic.create_item(logic.FOLDER, str(tmp_path), "arms")
    with pytest.raises(ValueError):
        logic.place([arms], arms, None)


def test_delete_removes_items_and_forgets_them(tmp_path):
    a = logic.create_item(logic.SCRIPT, str(tmp_path), "a")
    arms = logic.create_item(logic.FOLDER, str(tmp_path), "arms")
    logic.create_item(logic.SCRIPT, arms, "inside")
    logic.set_enabled([a], False)

    logic.delete_paths([a, arms])

    assert logic.scan(str(tmp_path)) == []
    logic.create_item(logic.SCRIPT, str(tmp_path), "a")
    assert logic.is_enabled(os.path.join(str(tmp_path), "a.py"))


# -- recent folders ---------------------------------------------------------


@pytest.fixture
def no_recent():
    settings.remove(logic.SETTINGS_KEY, "recent_folders")
    yield
    settings.remove(logic.SETTINGS_KEY, "recent_folders")


def test_recent_folders_newest_first_without_duplicates(tmp_path, no_recent):
    folders = []
    for i in range(12):
        folder = tmp_path / f"f{i}"
        folder.mkdir()
        folders.append(str(folder))
        logic.remember_folder(str(folder))
    logic.remember_folder(folders[5])

    recent = logic.recent_folders()

    assert len(recent) == logic.MAX_RECENT == 10
    assert recent[0] == folders[5]
    assert recent[1] == folders[11]
    assert recent.count(folders[5]) == 1


def test_recent_folders_drop_missing_ones(tmp_path, no_recent):
    gone = tmp_path / "gone"
    gone.mkdir()
    logic.remember_folder(str(gone))
    gone.rmdir()
    assert logic.recent_folders() == []


# -- run --------------------------------------------------------------------


def test_run_goes_in_tree_order_whatever_the_selection_order(tmp_path, ran):
    a, b = _script(tmp_path, "a"), _script(tmp_path, "b")
    runner = logic.Runner()

    assert runner.run([b, a]) == logic.DONE

    assert ran == ["a", "b"]
    assert runner.status(a) == (logic.RAN, "")
    assert runner.status(b) == (logic.RAN, "")


def test_running_a_folder_runs_its_enabled_items_in_order(tmp_path, ran):
    arms = logic.create_item(logic.FOLDER, str(tmp_path), "arms")
    for name in ("one", "two", "three"):
        logic.create_item(logic.SCRIPT, arms, name)
    for name in ("one", "two", "three"):
        _script(arms, name)
    logic.set_enabled([os.path.join(arms, "two.py")], False)
    logic.create_item(logic.SEPARATOR, arms, "divider")

    logic.Runner().run([arms])

    assert ran == ["one", "three"]


def test_a_disabled_folder_inside_is_skipped(tmp_path, ran):
    inner = logic.create_item(logic.FOLDER, str(tmp_path), "inner")
    _script(inner, "x")
    logic.set_enabled([inner], False)
    _script(tmp_path, "y")

    logic.Runner().run([str(tmp_path / "inner"), str(tmp_path / "y.py")])
    # Selected directly, the disabled folder still runs its items.
    assert ran == ["x", "y"]

    ran.clear()
    outer = str(tmp_path)
    logic.Runner().run([outer])
    assert ran == ["y"]


def test_a_selected_disabled_item_still_runs(tmp_path, ran):
    a = _script(tmp_path, "a")
    logic.set_enabled([a], False)
    logic.Runner().run([a])
    assert ran == ["a"]


def test_an_item_in_a_selected_folder_runs_once(tmp_path, ran):
    arms = logic.create_item(logic.FOLDER, str(tmp_path), "arms")
    a = _script(arms, "a")
    logic.Runner().run([arms, a])
    assert ran == ["a"]


def test_run_with_nothing_selected_raises(tmp_path):
    with pytest.raises(ValueError, match="Select items to run"):
        logic.Runner().run([])


def test_scripts_share_main_and_see_their_file(tmp_path, ran):
    _script(tmp_path, "a", "shared_value = 42\n")
    b = _script(tmp_path, "b", "import __main__\n__main__.ran.append((shared_value, __file__))\n")
    __main__.__file__ = "before"
    try:
        logic.Runner().run([str(tmp_path / "a.py"), b])
        assert ran == [(42, b)]
        assert __main__.__file__ == "before"
    finally:
        del __main__.__file__
        __main__.__dict__.pop("shared_value", None)


def test_a_failure_stops_the_run(tmp_path, ran, capsys):
    a = _script(tmp_path, "a")
    bad = _script(tmp_path, "b_bad", "raise RuntimeError('boom')\n")
    c = _script(tmp_path, "c")
    runner = logic.Runner()

    result = runner.run([str(tmp_path)])

    assert result == logic.FAILED
    assert runner.status(a)[0] == logic.RAN
    assert runner.status(bad) == (logic.FAILED, "RuntimeError: boom")
    assert runner.status(c) == (None, "")
    assert "Traceback" in capsys.readouterr().err


def test_one_undo_reverts_the_whole_run(tmp_path, new_scene):
    _script(tmp_path, "a", "from maya import cmds\ncmds.createNode('transform', name='made_a')\n")
    _script(tmp_path, "b", "from maya import cmds\ncmds.createNode('transform', name='made_b')\n")
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    logic.Runner().run([str(tmp_path / "a.py"), str(tmp_path / "b.py")])
    assert cmds.objExists("made_a") and cmds.objExists("made_b")

    cmds.undo()
    assert not cmds.objExists("made_a")
    assert not cmds.objExists("made_b")


# -- breakpoints ------------------------------------------------------------


def _with_breakpoint(folder):
    logic.create_item(logic.SCRIPT, str(folder), "a")
    stop = logic.create_item(logic.BREAKPOINT, str(folder), "stop")
    logic.create_item(logic.SCRIPT, str(folder), "b")
    a, b = _script(folder, "a"), _script(folder, "b")
    return a, stop, b


def test_a_breakpoint_pauses_and_continue_runs_the_rest(tmp_path, ran):
    a, stop, b = _with_breakpoint(tmp_path)
    runner = logic.Runner()

    assert runner.run([a, stop, b]) == logic.DONE  # selected directly: ignored
    assert ran == ["a", "b"]

    ran.clear()
    assert runner.run([str(tmp_path)]) == logic.PAUSED
    assert ran == ["a"]
    assert runner.status(stop) == (logic.PAUSED, "")
    assert runner.paused_at == stop

    # Continue reads the files again: edits made while paused are used.
    _script(tmp_path, "b", "import __main__\n__main__.ran.append('b edited')\n")
    assert runner.continue_run(stop) == logic.DONE
    assert ran == ["a", "b edited"]
    assert runner.paused_at is None
    assert runner.status(stop) == (logic.RAN, "")


def test_continue_only_on_the_paused_breakpoint(tmp_path, ran):
    a, stop, b = _with_breakpoint(tmp_path)
    other = logic.create_item(logic.BREAKPOINT, str(tmp_path), "other")
    runner = logic.Runner()
    with pytest.raises(ValueError):
        runner.continue_run(stop)

    runner.run([str(tmp_path)])
    assert runner.can_continue(stop)
    assert not runner.can_continue(other)
    with pytest.raises(ValueError):
        runner.continue_run(other)


def test_running_only_a_breakpoint_does_nothing_and_keeps_the_pause(tmp_path, ran):
    a, stop, b = _with_breakpoint(tmp_path)
    runner = logic.Runner()
    runner.run([str(tmp_path)])
    ran.clear()

    assert runner.run([stop]) is None

    assert ran == []
    assert runner.paused_at == stop
    assert runner.status(a) == (logic.RAN, "")
    assert runner.status(stop) == (logic.PAUSED, "")
    assert runner.continue_run(stop) == logic.DONE
    assert ran == ["b"]


def test_a_new_run_drops_the_pause_and_the_old_statuses(tmp_path, ran):
    a, stop, b = _with_breakpoint(tmp_path)
    runner = logic.Runner()
    runner.run([str(tmp_path)])

    runner.run([b])

    assert runner.paused_at is None
    assert runner.status(a) == (None, "")
    assert runner.status(stop) == (None, "")
    assert runner.status(b) == (logic.RAN, "")


def test_a_disabled_breakpoint_doesnt_pause(tmp_path, ran):
    a, stop, b = _with_breakpoint(tmp_path)
    logic.set_enabled([stop], False)
    assert logic.Runner().run([str(tmp_path)]) == logic.DONE
    assert ran == ["a", "b"]


# -- the tool ---------------------------------------------------------------


def test_only_python_opens_in_the_script_editor(tmp_path):
    from kaiju_suite.tools.scripter import script_editor

    with pytest.raises(ValueError):
        script_editor.open_in_script_editor(_write(tmp_path / "old.mel"))


def test_the_tool_is_registered_without_loading_qt():
    import sys

    from kaiju_suite import registry

    tool = registry.find("Scripter")
    assert tool is not None and callable(tool["launch"])
    assert "kaiju_suite.tools.scripter.widget" not in sys.modules


def test_type_column_text(tmp_path):
    logic.create_item(logic.SCRIPT, str(tmp_path), "a")
    logic.create_item(logic.FOLDER, str(tmp_path), "b")
    logic.create_item(logic.SEPARATOR, str(tmp_path), "c")
    logic.create_item(logic.BREAKPOINT, str(tmp_path), "d")
    labels = [e.type_label for e in logic.scan(str(tmp_path))]
    assert labels == ["Script", "", logic.SEPARATOR_TEXT, "Breakpoint"]
    assert logic.SEPARATOR_TEXT == "====="
