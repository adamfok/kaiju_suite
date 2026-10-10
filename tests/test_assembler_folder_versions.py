"""Folder versions: a published folder records a build plan of what's in it,
with the version every item was at, and restoring one rebuilds the folder."""

import json
import os

import pytest

from kaiju_suite.tools.assembler import logic, versions
from kaiju_suite.tools.assembler.products import folder


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return str(path)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _published(path, text):
    """Write ``text`` to ``path`` and publish it; returns the path."""
    _write(path, text)
    versions.save_version(str(path))
    return str(path)


@pytest.fixture
def rig(tmp_path):
    """A folder with two published scripts, one in a subfolder."""
    root = tmp_path / "rig"
    _published(root / "a.py", "a = 1\n")
    _published(root / "sub" / "b.py", "b = 1\n")
    return str(root)


def _numbers(path):
    return [v.number for v in versions.list_versions(path)]


# -- publishing ---------------------------------------------------------------


def test_folders_are_versioned():
    assert folder.PRODUCT.versioned


def test_publish_saves_a_build_plan_with_every_childs_version(rig):
    version = versions.save_version(rig)
    assert version.number == 1
    assert os.path.dirname(version.path) == versions.history_dir(rig)
    with open(version.path, encoding="utf-8") as f:
        record = json.load(f)
    assert record["plan"] == {
        "items": [
            {"name": "sub", "items": [{"name": "b.py", "content": "b = 1\n", "version": 1}]},
            {"name": "a.py", "content": "a = 1\n", "version": 1},
        ]
    }


def test_the_saved_plan_records_order_and_disabled_items(rig):
    logic.append_to_order(rig, ["sub"])  # a.py first now
    logic.set_enabled(os.path.join(rig, "a.py"), False)
    version = versions.save_version(rig)
    with open(version.path, encoding="utf-8") as f:
        items = json.load(f)["plan"]["items"]
    assert [i["name"] for i in items] == ["a.py", "sub"]
    assert items[0]["enabled"] is False


def test_publish_message_names_the_folder(rig):
    assert versions.publish(rig) == "Published Folder rig v001"


def test_publishing_an_unchanged_folder_adds_no_version(rig):
    versions.save_version(rig)
    assert versions.save_version(rig) is None
    assert "already published as v001" in versions.publish(rig)


def test_publishing_an_empty_folder_adds_no_version(tmp_path):
    os.makedirs(tmp_path / "empty")
    assert versions.save_version(str(tmp_path / "empty")) is None
    assert versions.list_versions(str(tmp_path / "empty")) == []


def test_publish_problems_name_children_with_unpublished_changes(rig):
    _write(os.path.join(rig, "sub", "b.py"), "b = 2\n")
    _write(os.path.join(rig, "new.py"), "n = 1\n")
    (problem,) = versions.publish_problems(rig)
    assert "sub/b.py" in problem and "new.py" in problem
    assert "a.py" not in problem
    with pytest.raises(ValueError):
        versions.save_version(rig)


def test_empty_children_dont_stop_a_publish(rig):
    _write(os.path.join(rig, "later.py"), "")
    assert versions.publish_problems(rig) == []
    assert versions.save_version(rig).number == 1


# -- the * --------------------------------------------------------------------


def test_tree_label_shows_the_published_version(rig):
    assert versions.tree_label(rig) == ("", True)
    versions.save_version(rig)
    assert versions.tree_label(rig) == ("v001", True)


def test_adding_a_child_stars_the_folder(rig):
    versions.save_version(rig)
    _write(os.path.join(rig, "later.py"), "")
    assert versions.tree_label(rig) == ("v001*", True)


def test_adding_a_subfolder_stars_the_folder(rig):
    versions.save_version(rig)
    os.makedirs(os.path.join(rig, "extra"))
    assert versions.tree_label(rig) == ("v001*", True)


def test_removing_a_child_stars_the_folder(rig):
    versions.save_version(rig)
    logic.delete_path(os.path.join(rig, "sub", "b.py"))
    assert versions.tree_label(rig) == ("v001*", True)


def test_renaming_a_child_stars_the_folder(rig):
    versions.save_version(rig)
    logic.rename_path(os.path.join(rig, "a.py"), "c")
    assert versions.tree_label(rig) == ("v001*", True)


def test_a_child_changing_version_stars_the_folder(rig):
    versions.save_version(rig)
    _published(os.path.join(rig, "a.py"), "a = 2\n")
    assert versions.tree_label(rig) == ("v001*", True)


def test_unpublished_edits_in_a_child_star_the_folder(rig):
    versions.save_version(rig)
    _write(os.path.join(rig, "a.py"), "a = 2\n")
    assert versions.tree_label(rig) == ("v001*", True)
    assert versions.menu_status(rig) == "Has changes not published yet"


def test_reordering_children_stars_the_folder(rig):
    versions.save_version(rig)
    logic.append_to_order(rig, ["sub"])
    assert versions.tree_label(rig) == ("v001*", True)


def test_disabling_a_child_stars_the_folder(rig):
    versions.save_version(rig)
    logic.set_enabled(os.path.join(rig, "a.py"), False)
    assert versions.tree_label(rig) == ("v001*", True)


def test_an_unreadable_record_is_never_current(rig):
    version = versions.save_version(rig)
    _write(version.path, "not json")
    assert versions.current_version(rig) is None
    assert versions.tree_label(rig) == ("v001*", True)


def test_a_folder_stays_on_its_version_instead_of_jumping_to_a_matching_one(rig):
    child = os.path.join(rig, "sub")
    versions.save_version(child)  # child v001
    versions.save_version(rig)  # rig v001
    _published(os.path.join(child, "b.py"), "b = 2\n")
    versions.save_version(child)  # child v002
    versions.save_version(rig)  # rig v002
    versions.restore_version(child, 1)
    # Everything under rig matches its v001 again, but it was on v002.
    assert versions.tree_label(rig) == ("v002*", True)
    assert versions.menu_status(rig) == "Has changes not published yet"
    versions.restore_version(child, 2)
    assert versions.tree_label(rig) == ("v002", True)


def test_publishing_a_folder_that_matches_an_older_version_saves_a_copy(two_versions):
    rig = two_versions
    versions.restore_version(os.path.join(rig, "a.py"), 1)
    versions.restore_version(os.path.join(rig, "sub", "b.py"), 1)
    assert versions.tree_label(rig) == ("v002*", True)
    assert versions.publish(rig) == "Published Folder rig v003"
    assert _numbers(rig) == [3, 2, 1]
    assert versions.tree_label(rig) == ("v003", True)


def test_undoing_the_change_clears_the_star(rig):
    versions.save_version(rig)
    later = _write(os.path.join(rig, "later.py"), "")
    logic.delete_path(later)
    assert versions.tree_label(rig) == ("v001", True)


def test_republishing_after_a_change_adds_a_version(rig):
    versions.save_version(rig)
    _write(os.path.join(rig, "later.py"), "")
    assert versions.save_version(rig).number == 2
    assert versions.tree_label(rig) == ("v002", True)


# -- switching versions -------------------------------------------------------


@pytest.fixture
def two_versions(rig):
    """``rig`` published as v001 (a v1, b v1), then v002 (a v2, b v2)."""
    versions.save_version(rig)
    _published(os.path.join(rig, "a.py"), "a = 2\n")
    _published(os.path.join(rig, "sub", "b.py"), "b = 2\n")
    versions.save_version(rig)
    return rig


def test_restore_sets_every_child_to_its_published_version(two_versions):
    rig = two_versions
    message = versions.restore_version(rig, 1)
    assert _read(os.path.join(rig, "a.py")) == "a = 1\n"
    assert _read(os.path.join(rig, "sub", "b.py")) == "b = 1\n"
    assert versions.tree_label(rig) == ("v001", False)
    assert versions.tree_label(os.path.join(rig, "a.py")) == ("v001", False)
    assert "Restored rig to v001" in message
    # Switching back.
    versions.restore_version(rig, 2)
    assert _read(os.path.join(rig, "a.py")) == "a = 2\n"
    assert versions.tree_label(rig) == ("v002", True)


def test_restore_adds_no_version(two_versions):
    versions.restore_version(two_versions, 1)
    assert _numbers(two_versions) == [2, 1]
    assert _numbers(os.path.join(two_versions, "a.py")) == [2, 1]


def test_publishing_an_older_folder_version_saves_it_as_the_latest(two_versions):
    versions.restore_version(two_versions, 1)
    assert versions.publish(two_versions) == "Published Folder rig v003"
    assert _numbers(two_versions) == [3, 2, 1]
    assert versions.tree_label(two_versions) == ("v003", True)
    assert "already published as v003" in versions.publish(two_versions)


def _names(folder):
    return [e.name for e in logic.scan(folder)]


def test_restore_removes_children_added_since_and_brings_them_back(two_versions):
    rig = two_versions
    _published(os.path.join(rig, "later.py"), "x = 1\n")
    versions.save_version(rig)  # v003 has later.py
    message = versions.restore_version(rig, 1)
    assert _names(rig) == ["sub", "a.py"]
    assert versions.tree_label(rig) == ("v001", False)
    assert "Restored rig to v001" in message
    # Version up again: later.py comes back from its kept history.
    versions.restore_version(rig, 3)
    assert _names(rig) == ["sub", "a.py", "later.py"]
    assert _read(os.path.join(rig, "later.py")) == "x = 1\n"
    assert versions.tree_label(os.path.join(rig, "later.py")) == ("v001", True)
    assert versions.tree_label(rig) == ("v003", True)


def test_restore_brings_back_children_deleted_since(two_versions):
    rig = two_versions
    logic.delete_path(os.path.join(rig, "sub", "b.py"))  # deletes its history too
    message = versions.restore_version(rig, 2)
    # Its plan content brings it back, though not its versions.
    assert _read(os.path.join(rig, "sub", "b.py")) == "b = 2\n"
    assert "sub/b.py" in message


def test_restore_creates_deleted_data_items_empty_and_says_so(rig):
    _published(os.path.join(rig, "body.mesh"), "mesh data")
    versions.save_version(rig)
    logic.delete_path(os.path.join(rig, "body.mesh"))
    message = versions.restore_version(rig, 1)
    assert _read(os.path.join(rig, "body.mesh")) == ""
    assert "body.mesh" in message


def test_restore_switches_between_versions_with_different_subfolders(tmp_path):
    root = str(tmp_path / "rig")
    _published(os.path.join(root, "a.py"), "a = 1\n")
    _published(os.path.join(root, "arms", "L.py"), "l = 1\n")
    _published(os.path.join(root, "arms", "L.py"), "l = 2\n")
    versions.save_version(root)  # v001: a.py, arms/L.py v2
    logic.delete_path(os.path.join(root, "arms"))
    _published(os.path.join(root, "legs", "R.py"), "r = 1\n")
    versions.save_version(root)  # v002: a.py, legs/R.py

    versions.restore_version(root, 1)
    assert _names(root) == ["arms", "a.py"]
    assert _read(os.path.join(root, "arms", "L.py")) == "l = 2\n"

    versions.restore_version(root, 2)
    assert _names(root) == ["legs", "a.py"]
    assert _read(os.path.join(root, "legs", "R.py")) == "r = 1\n"
    assert versions.tree_label(os.path.join(root, "legs", "R.py")) == ("v001", True)


def test_a_removed_subfolder_keeps_its_items_histories(tmp_path):
    root = str(tmp_path / "rig")
    _published(os.path.join(root, "a.py"), "a = 1\n")
    versions.save_version(root)  # v001 has no arms
    _published(os.path.join(root, "arms", "L.py"), "l = 1\n")
    _published(os.path.join(root, "arms", "L.py"), "l = 2\n")
    versions.save_version(root)  # v002 has
    versions.restore_version(root, 1)
    assert not os.path.exists(os.path.join(root, "arms"))
    versions.restore_version(root, 2)
    assert _numbers(os.path.join(root, "arms", "L.py")) == [2, 1]
    assert _read(os.path.join(root, "arms", "L.py")) == "l = 2\n"


def test_restore_undoes_a_rename(rig):
    versions.save_version(rig)
    logic.rename_path(os.path.join(rig, "a.py"), "c")
    versions.save_version(rig)
    versions.restore_version(rig, 1)
    assert _names(rig) == ["sub", "a.py"]
    assert _read(os.path.join(rig, "a.py")) == "a = 1\n"
    versions.restore_version(rig, 2)
    assert _names(rig) == ["sub", "c.py"]
    assert _numbers(os.path.join(rig, "c.py")) == [1]


def test_restore_puts_back_order_and_disabled_state(rig):
    versions.save_version(rig)
    logic.append_to_order(rig, ["sub"])
    logic.set_enabled(os.path.join(rig, "a.py"), False)
    versions.save_version(rig)
    versions.restore_version(rig, 1)
    assert _names(rig) == ["sub", "a.py"]
    assert logic.is_enabled(os.path.join(rig, "a.py"))
    versions.restore_version(rig, 2)
    assert _names(rig) == ["a.py", "sub"]
    assert not logic.is_enabled(os.path.join(rig, "a.py"))


def test_restore_resets_a_child_that_was_empty_then(rig):
    _write(os.path.join(rig, "body.mesh"), "")
    versions.save_version(rig)
    _published(os.path.join(rig, "body.mesh"), "mesh data")
    versions.save_version(rig)
    versions.restore_version(rig, 1)
    assert _read(os.path.join(rig, "body.mesh")) == ""
    versions.restore_version(rig, 2)
    assert _read(os.path.join(rig, "body.mesh")) == "mesh data"


def test_restore_leaves_files_that_arent_items_alone(two_versions):
    notes = _write(os.path.join(two_versions, "notes.txt"), "keep me")
    versions.restore_version(two_versions, 1)
    assert _read(notes) == "keep me"


def test_restore_changes_nothing_if_a_child_version_is_missing(two_versions):
    rig = two_versions
    os.remove(versions.list_versions(os.path.join(rig, "sub", "b.py"))[-1].path)  # b's v001
    with pytest.raises(FileNotFoundError):
        versions.restore_version(rig, 1)
    assert _read(os.path.join(rig, "a.py")) == "a = 2\n"


def test_restore_unknown_folder_version_raises(rig):
    with pytest.raises(FileNotFoundError):
        versions.restore_version(rig, 5)


def test_switching_asks_when_a_removed_child_has_unpublished_edits(two_versions):
    rig = two_versions
    _write(os.path.join(rig, "later.py"), "x = 1\n")
    for action in versions.panel(rig).actions:
        assert "later.py" in action.confirm and "lost" in action.confirm


def test_switching_asks_only_when_child_edits_would_be_lost(two_versions):
    rig = two_versions
    (item,) = [i for i in versions.menu(rig)[0] if not i.current]
    assert item.action.confirm is None

    _write(os.path.join(rig, "a.py"), "a = 3\n")
    actions = versions.panel(rig).actions  # no version is current now, so both are listed
    assert len(actions) == 2
    for action in actions:
        assert "a.py" in action.confirm and "lost" in action.confirm


def test_menu_marks_the_current_folder_version(two_versions):
    items, more = versions.menu(two_versions)
    assert [i.current for i in items] == [True, False]
    assert "2 items" in items[0].label
    assert not more


def test_summary_of_a_folder(two_versions):
    assert versions.summary(two_versions) == "Current: v002 (2 versions)"


# -- history follows the folder -----------------------------------------------


def test_folder_history_follows_a_rename(two_versions):
    new = logic.rename_path(two_versions, "body")
    assert _numbers(new) == [2, 1]
    assert versions.tree_label(new) == ("v002", True)


def test_folder_history_follows_a_move(two_versions, tmp_path):
    os.makedirs(tmp_path / "chars")
    (new,) = logic.place([two_versions], str(tmp_path / "chars"), None)
    assert versions.tree_label(new) == ("v002", True)


def test_pasted_folder_keeps_its_own_history(two_versions):
    versions.restore_version(two_versions, 1)
    (copy,) = logic.paste_paths([two_versions], os.path.dirname(two_versions), None)
    assert os.path.basename(copy) == "rig_copy"
    assert _numbers(copy) == [2, 1]
    assert versions.tree_label(copy) == ("v001", False)
    assert versions.tree_label(os.path.join(copy, "a.py")) == ("v001", False)


def test_pasted_folder_can_switch_to_its_other_versions(two_versions):
    versions.restore_version(two_versions, 1)
    (copy,) = logic.paste_paths([two_versions], os.path.dirname(two_versions), None)

    assert versions.restore_version(copy, 2) == "Restored rig_copy to v002"
    assert _read(os.path.join(copy, "a.py")) == "a = 2\n"
    assert _read(os.path.join(copy, "sub", "b.py")) == "b = 2\n"
    assert versions.tree_label(copy) == ("v002", True)
    assert _read(os.path.join(two_versions, "a.py")) == "a = 1\n"  # the original stays


def test_deleting_a_folder_deletes_its_history(two_versions):
    logic.delete_path(two_versions)
    assert not os.path.exists(versions.history_dir(two_versions))


def test_folder_history_is_not_listed(two_versions, tmp_path):
    assert [e.name for e in logic.scan(str(tmp_path))] == ["rig"]
