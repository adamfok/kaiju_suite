"""Version descriptions: every version keeps a short note of what changed,
typed on Publish or written automatically, shown in the Versions submenu and
the Versions window (the changelog)."""

import json
import os

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import data, logic, products, versions
from kaiju_suite.tools.assembler.products import output


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return str(path)


def _writer(text):
    return lambda target: _write(target, text)


def _descriptions(path):
    return {v.number: v.description for v in versions.list_versions(path)}


# -- storing and reading --------------------------------------------------------


def test_save_version_stores_its_description(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    version = versions.save_version(path, description="First pass")
    assert version.description == "First pass"
    assert versions.list_versions(path)[0].description == "First pass"


def test_versions_saved_without_one_have_no_description(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    versions.save_version(path)
    assert versions.list_versions(path)[0].description == ""
    assert versions.description_text(versions.list_versions(path)[0]) == versions.NO_DESCRIPTION


def test_descriptions_live_next_to_the_base_file(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    versions.save_version(path, description="First pass")
    stored = os.path.join(versions.history_dir(path), versions.DESCRIPTIONS_FILE)
    with open(stored, encoding="utf-8") as f:
        assert json.load(f) == {"1": "First pass"}
    # The descriptions file isn't taken for a version.
    assert [v.number for v in versions.list_versions(path)] == [1]


def test_an_unreadable_descriptions_file_reads_as_none(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    versions.save_version(path, description="First pass")
    _write(os.path.join(versions.history_dir(path), versions.DESCRIPTIONS_FILE), "not json")
    assert versions.list_versions(path)[0].description == ""


def test_description_is_trimmed(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    assert versions.save_version(path, description="  Fixed the knee \n").description == "Fixed the knee"


def test_publish_takes_a_description(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    versions.publish(path, description="Knee fix")
    assert _descriptions(path) == {1: "Knee fix"}


def test_describing_applies_to_versions_saved_inside_it(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    with versions.describing("From the prompt"):
        versions.publish_action(path).fn()
    _write(path, "a = 2\n")
    versions.save_version(path)  # outside: none
    assert _descriptions(path) == {2: "", 1: "From the prompt"}


def test_publish_left_blank_reads_no_description(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    with versions.describing(""):
        versions.publish(path)
    assert versions.description_text(versions.list_versions(path)[0]) == versions.NO_DESCRIPTION


def test_a_given_description_wins_over_describing(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    with versions.describing("From the prompt"):
        versions.save_version(path, description="Given")
    assert _descriptions(path) == {1: "Given"}


# -- versions made without the user publishing ------------------------------------


def test_export_into_describes_the_new_version(tmp_path):
    path = _write(tmp_path / "build.py", "")
    versions.export_into(path, _writer("a = 1\n"), description="Weights from scene")
    assert _descriptions(path) == {1: "Weights from scene"}


def test_export_into_keeps_unpublished_content_with_an_automatic_description(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    versions.save_version(path, description="First")
    _write(path, "a = 2\n")  # edited by hand, not published
    with versions.describing("New weights"):
        versions.export_into(path, _writer("a = 3\n"))
    assert _descriptions(path) == {3: "New weights", 2: versions.KEPT_UNPUBLISHED, 1: "First"}


def test_publishing_an_older_version_says_which_one(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    versions.save_version(path, description="One")
    _write(path, "a = 2\n")
    versions.save_version(path, description="Two")
    versions.restore_version(path, 1)

    versions.publish(path)
    assert _descriptions(path)[3] == "Republished v001"

    versions.restore_version(path, 2)
    versions.publish(path, description="Back to two")
    assert _descriptions(path)[4] == "Back to two (republished v002)"


def test_export_into_matching_an_older_version_says_which_one(tmp_path):
    path = _write(tmp_path / "build.py", "")
    versions.export_into(path, _writer("a = 1\n"))
    versions.export_into(path, _writer("a = 2\n"))
    versions.export_into(path, _writer("a = 1\n"), description="Undo the change")
    assert _descriptions(path)[3] == "Undo the change (republished v001)"


def test_nothing_new_published_stores_no_description(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    versions.publish(path, description="First")
    versions.publish(path, description="Again")
    assert _descriptions(path) == {1: "First"}


# -- descriptions go with the history -------------------------------------------


def test_descriptions_move_with_a_renamed_item(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    versions.save_version(path, description="First")
    new = logic.rename_path(path, "setup.py")
    assert _descriptions(new) == {1: "First"}


def test_descriptions_are_copied_with_a_pasted_item(tmp_path):
    path = _write(tmp_path / "a" / "build.py", "a = 1\n")
    versions.save_version(path, description="First")
    os.makedirs(tmp_path / "b")
    (copy,) = logic.paste_paths([path], str(tmp_path / "b"), 0)
    assert _descriptions(copy) == {1: "First"}
    assert _descriptions(path) == {1: "First"}


def test_descriptions_are_deleted_with_the_item(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    versions.save_version(path, description="First")
    logic.delete_path(path)
    assert not os.path.exists(os.path.join(tmp_path, versions.HISTORY_DIR))


# -- folders ----------------------------------------------------------------------


@pytest.fixture
def rig(tmp_path):
    root = tmp_path / "rig"
    for rel in ("a.py", "sub/b.py"):
        versions.save_version(_write(root / rel, "x = 1\n"))
    return str(root)


def test_a_folder_version_keeps_its_description(rig):
    versions.publish(rig, description="Arms in")
    assert _descriptions(rig) == {1: "Arms in"}


def test_folder_suggestion_lists_every_item_before_the_first_publish(rig):
    assert versions.suggested_description(rig) == "a.py v001, sub/b.py v001"


def test_folder_suggestion_lists_the_item_versions_that_changed(rig):
    versions.publish(rig)
    assert versions.suggested_description(rig) == ""
    versions.save_version(_write(os.path.join(rig, "sub", "b.py"), "x = 2\n"))
    versions.save_version(_write(os.path.join(rig, "c.py"), "c = 1\n"))
    assert versions.suggested_description(rig) == "c.py v001, sub/b.py v002"


def test_folder_suggestion_names_removed_items(rig):
    versions.publish(rig)
    logic.delete_path(os.path.join(rig, "a.py"))
    assert versions.suggested_description(rig) == "removed a.py"


def test_files_have_no_suggestion(tmp_path):
    assert versions.suggested_description(_write(tmp_path / "build.py", "a = 1\n")) == ""


# -- asking for one ---------------------------------------------------------------


def test_publish_action_asks_for_a_description(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    assert versions.publish_action(path).describe


class _Tags(data.DataProduct):
    name = "DescTags"
    kind = "desctags"
    extension = ".desctag"
    order = 903

    def gather(self, selection):
        return {"tags": [{"name": cmds.ls(n)[0], "tx": cmds.getAttr(f"{n}.tx")} for n in selection]}

    def apply(self, payload):
        pass

    def nodes(self, payload):
        return [t["name"] for t in payload["tags"]]


@pytest.fixture
def tags(monkeypatch):
    product = _Tags()
    monkeypatch.setattr(products, "_cache", sorted(products.discover() + [product], key=lambda p: p.order))
    return product


def test_republish_asks_for_a_description_and_keeps_it(new_scene, tags, tmp_path):
    cmds.polyCube(name="box")
    path = tags.create(str(tmp_path), "item")
    cmds.select("box")
    with versions.describing("First"):
        versions.publish_action(path).fn()
    cmds.select(clear=True)
    cmds.setAttr("box.tx", 2)

    (republish,) = [a for a in tags.actions(path) if a.label == "Republish"]
    assert republish.describe
    with versions.describing("Moved the box"):
        republish.fn()
    assert _descriptions(path) == {2: "Moved the box", 1: "First"}


def test_output_option_toggles_describe_themselves(tmp_path):
    path = output.create_output(str(tmp_path), "rig")
    output.set_output(path, str(tmp_path / "rig.ma"), description="Save to rig.ma")
    output.set_option(path, "hide_joints", True)
    output.set_option(path, "delete_unused", True)
    output.set_option(path, "hide_joints", False)
    assert _descriptions(path) == {
        4: "Output: hide joints off",
        3: "Output: delete unused nodes on",
        2: "Output: hide joints on",
        1: "Save to rig.ma",
    }


def test_output_option_buttons_dont_ask(tmp_path):
    path = output.create_output(str(tmp_path), "rig")
    output.set_output(path, str(tmp_path / "rig.ma"))
    assert not any(a.describe for a in output.PRODUCT.panel(path).actions)


# -- the Versions window ----------------------------------------------------------


def test_changelog_lists_every_version_newest_first(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    versions.save_version(path, description="One")
    _write(path, "a = 2\n")
    versions.save_version(path)

    log = versions.changelog(path)
    assert [(r.tag, r.description, r.current) for r in log.rows] == [
        ("v002", versions.NO_DESCRIPTION, True),
        ("v001", "One", False),
    ]
    assert all(r.when for r in log.rows)
    assert "Current: v002" in log.summary
    # The current version needs no Restore: it's already in the file.
    assert log.rows[0].restore is None
    assert log.rows[1].restore.confirm is None
    assert log.can_compare == versions.can_compare(path)

    log.rows[1].restore.fn()
    assert [r.current for r in versions.changelog(path).rows] == [False, True]


def test_changelog_restore_warns_when_unpublished_changes_would_be_lost(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    versions.save_version(path)
    _write(path, "a = 2\n")
    log = versions.changelog(path)
    assert "not published" in log.summary
    assert "lost" in log.rows[0].restore.confirm


def test_changelog_of_an_item_with_no_versions(tmp_path):
    log = versions.changelog(_write(tmp_path / "build.py", "a = 1\n"))
    assert log.rows == [] and "No versions" in log.summary


def test_folders_cant_be_compared_in_the_changelog(rig):
    versions.publish(rig, description="Arms in")
    log = versions.changelog(rig)
    assert not log.can_compare
    assert log.rows[0].description == "Arms in"
