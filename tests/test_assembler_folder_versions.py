"""Folder versions: a published folder records the version of every item in it."""

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


def test_publish_saves_the_version_of_every_child(rig):
    version = versions.save_version(rig)
    assert version.number == 1
    assert os.path.dirname(version.path) == versions.history_dir(rig)
    with open(version.path, encoding="utf-8") as f:
        record = json.load(f)
    assert record["items"] == {"a.py": 1, "sub": None, "sub/b.py": 1}


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


def test_restore_leaves_children_added_since_alone(two_versions):
    rig = two_versions
    later = _write(os.path.join(rig, "later.py"), "x = 1\n")
    message = versions.restore_version(rig, 1)
    assert _read(later) == "x = 1\n"
    assert "later.py" in message
    assert versions.tree_label(rig) == ("v001*", False)


def test_restore_reports_children_deleted_since(two_versions):
    rig = two_versions
    logic.delete_path(os.path.join(rig, "sub", "b.py"))
    message = versions.restore_version(rig, 1)
    assert _read(os.path.join(rig, "a.py")) == "a = 1\n"
    assert "sub/b.py" in message


def test_restore_changes_nothing_if_a_child_version_is_missing(two_versions):
    rig = two_versions
    os.remove(versions.list_versions(os.path.join(rig, "sub", "b.py"))[-1].path)  # b's v001
    with pytest.raises(FileNotFoundError):
        versions.restore_version(rig, 1)
    assert _read(os.path.join(rig, "a.py")) == "a = 2\n"


def test_restore_unknown_folder_version_raises(rig):
    with pytest.raises(FileNotFoundError):
        versions.restore_version(rig, 5)


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


def test_deleting_a_folder_deletes_its_history(two_versions):
    logic.delete_path(two_versions)
    assert not os.path.exists(versions.history_dir(two_versions))


def test_folder_history_is_not_listed(two_versions, tmp_path):
    assert [e.name for e in logic.scan(str(tmp_path))] == ["rig"]
