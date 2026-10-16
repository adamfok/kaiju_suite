"""Kaiju Builder version history: Publish, Versions, Restore, descriptions."""

import os

import pytest

from kaiju_suite.tools.builder import logic, versions


def _set(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def script(tmp_path):
    path = logic.create_item(logic.SCRIPT, str(tmp_path), "setup")
    _set(path, "print('one')\n")
    return path


def test_a_new_item_has_no_versions(script):
    assert versions.list_versions(script) == []
    assert versions.label(script) == ""


def test_publish_saves_numbered_versions_with_descriptions(script):
    assert versions.publish(script, "First") == 1
    _set(script, "print('two')\n")
    assert versions.publish(script, "") == 2

    found = versions.list_versions(script)
    assert [v.number for v in found] == [1, 2]
    assert [v.description for v in found] == ["First", versions.NO_DESCRIPTION]
    assert _text(found[0].path) == "print('one')\n"
    assert found[0].path == os.path.join(
        os.path.dirname(script), ".builder", "versions", "setup.py", "v001.py"
    )


def test_publishing_without_changes_is_refused(script):
    versions.publish(script, "First")
    with pytest.raises(ValueError, match="No changes"):
        versions.publish(script, "Again")


def test_unchanged_since_names_the_version_publish_would_repeat(script):
    assert versions.unchanged_since(script) is None  # never published: there's something to publish
    versions.publish(script, "First")
    assert versions.unchanged_since(script) == 1
    _set(script, "print('edited')\n")
    assert versions.unchanged_since(script) is None
    versions.publish(script, "Second")
    versions.restore(script, 1)
    assert versions.unchanged_since(script) == 1  # the version it's at, not the newest


def test_the_label_shows_the_version_and_unpublished_edits(script):
    versions.publish(script, "First")
    assert versions.label(script) == "v001"
    _set(script, "print('edited')\n")
    assert versions.label(script) == "v001*"
    versions.publish(script, "Second")
    assert versions.label(script) == "v002"


def test_restore_puts_a_version_back(script):
    versions.publish(script, "First")
    _set(script, "print('two')\n")
    versions.publish(script, "Second")

    versions.restore(script, 1)

    assert _text(script) == "print('one')\n"
    assert versions.label(script) == "v001"
    assert len(versions.list_versions(script)) == 2


def test_restore_discards_unpublished_edits_without_saving_them(script):
    versions.publish(script, "First")
    _set(script, "print('unsaved work')\n")
    assert versions.has_unpublished(script)

    versions.restore(script, 1)

    assert [v.number for v in versions.list_versions(script)] == [1]
    assert _text(script) == "print('one')\n"
    assert not versions.has_unpublished(script)


def test_is_latest_only_at_the_newest_version(script):
    assert versions.is_latest(script)  # never published: nothing newer
    versions.publish(script, "First")
    _set(script, "print('two')\n")
    assert versions.is_latest(script)  # edited, but still based on the newest
    versions.publish(script, "Second")
    assert versions.is_latest(script)

    versions.restore(script, 1)
    assert not versions.is_latest(script)
    _set(script, "print('edited old')\n")
    assert not versions.is_latest(script)
    assert versions.label(script) == "v001*"


def test_current_number_is_the_version_it_is_at(script):
    assert versions.current_number(script) is None  # never published
    versions.publish(script, "First")
    _set(script, "print('two')\n")
    versions.publish(script, "Second")
    assert versions.current_number(script) == 2

    versions.restore(script, 1)
    assert versions.current_number(script) == 1
    _set(script, "print('edited old')\n")
    assert versions.current_number(script) == 1  # still based on it


def test_restore_of_a_missing_version_raises(script):
    with pytest.raises(ValueError):
        versions.restore(script, 7)


def test_only_scripts_are_versioned_for_now(tmp_path, script):
    assert versions.is_versioned(script)
    assert not versions.is_versioned(logic.create_item(logic.SEPARATOR, str(tmp_path), "s"))
    assert not versions.is_versioned(logic.create_item(logic.BREAKPOINT, str(tmp_path), "b"))
    assert not versions.is_versioned(logic.create_item(logic.FOLDER, str(tmp_path), "f"))


# -- history follows the item -----------------------------------------------


def test_rename_carries_the_history(script):
    versions.publish(script, "First")
    new = logic.rename_path(script, "build")
    assert [v.description for v in versions.list_versions(new)] == ["First"]
    assert versions.label(new) == "v001"


def test_moving_carries_the_history(tmp_path, script):
    versions.publish(script, "First")
    arms = logic.create_item(logic.FOLDER, str(tmp_path), "arms")
    [moved] = logic.place([script], arms, None)
    assert versions.label(moved) == "v001"
    assert versions.list_versions(script) == []


def test_delete_removes_the_history(tmp_path, script):
    versions.publish(script, "First")
    _set(script, "x = 2\n")
    versions.publish(script, "Second")
    assert versions.count(script) == 2

    logic.delete_paths([script])
    again = logic.create_item(logic.SCRIPT, str(tmp_path), "setup")

    assert versions.list_versions(again) == []
