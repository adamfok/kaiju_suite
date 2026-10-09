"""Rebuild (new scene, then Run All), "Run up to Here" and "Run from Here"."""

import os

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import logic


def _script(path, node):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"from maya import cmds\ncmds.createNode('transform', name='{node}')\n")
    return str(path)


@pytest.fixture
def tree(tmp_path):
    """root: 1_arms/ (l.py, r.py), 2_legs/ (off: x.py), a.py, b.py, c.py (disabled)."""
    root = str(tmp_path)
    paths = {
        "l": _script(tmp_path / "1_arms" / "l.py", "n_l"),
        "r": _script(tmp_path / "1_arms" / "r.py", "n_r"),
        "x": _script(tmp_path / "2_legs" / "x.py", "n_x"),
        "a": _script(tmp_path / "a.py", "n_a"),
        "b": _script(tmp_path / "b.py", "n_b"),
        "c": _script(tmp_path / "c.py", "n_c"),
    }
    paths["arms"] = os.path.join(root, "1_arms")
    paths["legs"] = os.path.join(root, "2_legs")
    logic.set_enabled(paths["legs"], False)
    logic.set_enabled(paths["c"], False)
    assert logic.collect_steps(root) == [paths[k] for k in ("l", "r", "a", "b")]
    return root, paths


# -- step selection -----------------------------------------------------------


def test_steps_up_to_a_file_include_it(tree):
    root, p = tree
    assert logic.steps_up_to(root, p["a"]) == [p["l"], p["r"], p["a"]]


def test_steps_from_a_file_include_it(tree):
    root, p = tree
    assert logic.steps_from(root, p["r"]) == [p["r"], p["a"], p["b"]]


def test_steps_up_to_a_folder_include_all_of_it(tree):
    root, p = tree
    assert logic.steps_up_to(root, p["arms"]) == [p["l"], p["r"]]


def test_steps_from_a_folder_include_all_of_it(tree):
    root, p = tree
    assert logic.steps_from(root, p["arms"]) == [p["l"], p["r"], p["a"], p["b"]]


def test_a_disabled_item_is_run_when_picked_directly(tree):
    root, p = tree
    assert logic.steps_up_to(root, p["c"]) == [p["l"], p["r"], p["a"], p["b"], p["c"]]
    assert logic.steps_from(root, p["c"]) == [p["c"]]


def test_an_item_in_a_disabled_folder_is_run_when_picked_directly(tree):
    root, p = tree
    assert logic.steps_up_to(root, p["x"]) == [p["l"], p["r"], p["x"]]
    assert logic.steps_from(root, p["x"]) == [p["x"], p["a"], p["b"]]
    assert logic.steps_from(root, p["legs"]) == [p["x"], p["a"], p["b"]]


def test_steps_follow_a_custom_order(tree):
    root, p = tree
    logic.place([p["b"]], root, 0)
    assert logic.steps_up_to(root, p["a"]) == [p["b"], p["l"], p["r"], p["a"]]
    assert logic.steps_from(root, p["arms"]) == [p["l"], p["r"], p["a"]]


def test_steps_for_a_path_outside_the_root_raise(tree, tmp_path_factory):
    root, _ = tree
    other = _script(tmp_path_factory.mktemp("other") / "z.py", "n_z")
    with pytest.raises(ValueError):
        logic.steps_up_to(root, other)
    with pytest.raises(ValueError):
        logic.steps_from(root, other)


# -- rebuild --------------------------------------------------------------------


def test_rebuild_starts_a_new_scene_then_runs(new_scene, tree):
    root, p = tree
    cmds.createNode("transform", name="leftover")
    cmds.file(modified=False)
    assert logic.rebuild(logic.collect_steps(root)) == [p["l"], p["r"], p["a"], p["b"]]
    assert not cmds.objExists("leftover")
    assert all(cmds.objExists(n) for n in ("n_l", "n_r", "n_a", "n_b"))
    assert not cmds.objExists("n_c")


def test_rebuild_refuses_to_discard_unsaved_changes(new_scene, tree):
    root, _ = tree
    cmds.createNode("transform", name="leftover")
    cmds.file(modified=True)
    with pytest.raises(logic.UnsavedChangesError):
        logic.rebuild(logic.collect_steps(root))
    assert cmds.objExists("leftover")
    assert not cmds.objExists("n_l")


def test_rebuild_discards_unsaved_changes_when_told(new_scene, tree):
    root, _ = tree
    cmds.createNode("transform", name="leftover")
    cmds.file(modified=True)
    logic.rebuild(logic.collect_steps(root), discard_changes=True)
    assert not cmds.objExists("leftover")
    assert cmds.objExists("n_b")


def test_rebuild_up_to_here(new_scene, tree):
    root, p = tree
    logic.rebuild(logic.steps_up_to(root, p["r"]), discard_changes=True)
    assert cmds.objExists("n_l") and cmds.objExists("n_r")
    assert not cmds.objExists("n_a")


def test_rebuild_is_one_undo_step(new_scene, tree):
    root, _ = tree
    cmds.undoInfo(state=True)
    logic.rebuild(logic.collect_steps(root), discard_changes=True)
    cmds.undo()
    assert not any(cmds.objExists(n) for n in ("n_l", "n_r", "n_a", "n_b"))


def test_rebuild_reports_status_and_stops_at_a_failure(new_scene, tree):
    root, p = tree
    with open(p["a"], "w", encoding="utf-8") as f:
        f.write("raise RuntimeError('boom')\n")
    seen = []
    with pytest.raises(logic.StepError) as info:
        logic.rebuild(logic.collect_steps(root), discard_changes=True, on_status=lambda q, s: seen.append((q, s)))
    assert info.value.path == p["a"]
    assert (p["a"], logic.ERROR) in seen
    assert cmds.objExists("n_r") and not cmds.objExists("n_b")


def test_run_from_here_keeps_the_current_scene(new_scene, tree):
    root, p = tree
    cmds.createNode("transform", name="leftover")
    logic.run_steps(logic.steps_from(root, p["a"]))
    assert cmds.objExists("leftover") and cmds.objExists("n_a") and cmds.objExists("n_b")
    assert not cmds.objExists("n_l")
