import os

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import logic, products, versions
from kaiju_suite.tools.assembler.products import folder, scene, script


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return str(path)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _numbers(path):
    return [v.number for v in versions.list_versions(path)]


# -- saving and listing -----------------------------------------------------


def test_save_version_numbers_from_one(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    assert versions.list_versions(path) == []

    first = versions.save_version(path)
    assert first.number == 1
    assert os.path.basename(first.path) == "v001.py"
    assert _read(first.path) == "a = 1\n"

    _write(path, "a = 2\n")
    assert versions.save_version(path).number == 2
    assert _numbers(path) == [2, 1]  # newest first


def test_history_lives_in_a_hidden_folder_next_to_the_item(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    versions.save_version(path)
    assert versions.history_dir(path) == os.path.join(str(tmp_path), ".versions", "build.py")
    assert os.path.isfile(os.path.join(versions.history_dir(path), "v001.py"))


def test_saving_unchanged_content_adds_no_version(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    versions.save_version(path)
    assert versions.save_version(path) is None
    assert _numbers(path) == [1]


def test_saving_content_of_an_older_version_adds_no_version(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    versions.save_version(path)
    _write(path, "a = 2\n")
    versions.save_version(path)
    _write(path, "a = 1\n")
    assert versions.save_version(path) is None
    assert _numbers(path) == [2, 1]


def test_current_version_is_the_one_matching_the_file(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    assert versions.current_version(path) is None
    versions.save_version(path)
    _write(path, "a = 2\n")
    assert versions.current_version(path) is None  # edited since
    versions.save_version(path)
    assert versions.current_version(path).number == 2
    _write(path, "a = 1\n")
    assert versions.current_version(path).number == 1


def test_saving_an_empty_file_adds_no_version(tmp_path):
    path = _write(tmp_path / "build.py", "")
    assert versions.save_version(path) is None
    assert versions.list_versions(path) == []


def test_numbering_continues_after_the_highest_version(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    _write(os.path.join(versions.history_dir(path), "v007.py"), "old\n")
    assert versions.save_version(path).number == 8


def test_list_ignores_unrelated_files(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    _write(os.path.join(versions.history_dir(path), "notes.txt"), "x")
    assert versions.list_versions(path) == []


def test_save_version_rejects_folders_and_missing_files(tmp_path):
    with pytest.raises(ValueError):
        versions.save_version(str(tmp_path))
    with pytest.raises(FileNotFoundError):
        versions.save_version(str(tmp_path / "gone.py"))


# -- restoring --------------------------------------------------------------


def test_restore_brings_back_old_content_without_adding_a_version(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    versions.save_version(path)
    _write(path, "a = 2\n")
    versions.save_version(path)

    message = versions.restore_version(path, 1)
    assert "v001" in message
    assert _read(path) == "a = 1\n"
    assert _numbers(path) == [2, 1]
    assert versions.current_version(path).number == 1


def test_restore_unknown_version_raises(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    with pytest.raises(FileNotFoundError):
        versions.restore_version(path, 3)


# -- panel ------------------------------------------------------------------


def test_versions_panel_lists_a_restore_per_other_version(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    assert "No versions" in " ".join(versions.panel(path).info)
    assert versions.panel(path).actions == []

    for n in (1, 2, 3):
        _write(path, f"a = {n}\n")
        versions.save_version(path)
    assert "Current: v003" in " ".join(versions.panel(path).info)

    # The current version has no Restore: it's already in the file.
    actions = versions.panel(path).actions
    assert [a.label.split()[1] for a in actions] == ["v002", "v001"]
    assert all(a.confirm is None for a in actions)  # nothing is lost by switching

    actions[1].fn()
    assert _read(path) == "a = 1\n"
    assert "Current: v001" in " ".join(versions.panel(path).info)
    assert [a.label.split()[1] for a in versions.panel(path).actions] == ["v003", "v002"]


def test_restore_warns_when_unsaved_changes_would_be_lost(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    versions.save_version(path)
    _write(path, "a = 2\n")

    panel = versions.panel(path)
    assert "not published" in " ".join(panel.info)
    (action,) = panel.actions
    assert "lost" in action.confirm


def test_only_files_are_versioned():
    assert script.PRODUCT.versioned
    assert scene.PRODUCT.versioned
    assert not folder.PRODUCT.versioned


# -- the tree ignores history -----------------------------------------------


def test_history_is_not_listed_or_run(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    versions.save_version(path)
    assert [e.name for e in logic.scan(str(tmp_path))] == ["build.py"]
    assert logic.collect_steps(str(tmp_path)) == [path]


# -- history follows the item -----------------------------------------------


def test_rename_keeps_history(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    versions.save_version(path)

    new = logic.rename_path(path, "setup")
    assert _numbers(new) == [1]
    assert not os.path.exists(os.path.join(str(tmp_path), ".versions", "build.py"))


def test_move_carries_history(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    versions.save_version(path)
    os.makedirs(tmp_path / "sub")

    [new] = logic.place([path], str(tmp_path / "sub"), None)
    assert _numbers(new) == [1]
    assert versions.list_versions(path) == []


def test_place_carries_history(tmp_path):
    path = _write(tmp_path / "a" / "build.py", "a = 1\n")
    versions.save_version(path)
    os.makedirs(tmp_path / "b")

    (new,) = logic.place([path], str(tmp_path / "b"), 0)
    assert _numbers(new) == [1]


def test_delete_removes_history(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    versions.save_version(path)

    logic.delete_path(path)
    assert not os.path.exists(versions.history_dir(path))


def test_pasted_file_starts_without_history(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    versions.save_version(path)

    (copy,) = logic.paste_paths([path], str(tmp_path), None)
    assert versions.list_versions(copy) == []
    assert _numbers(path) == [1]


def test_pasted_folder_keeps_its_contents_history(tmp_path):
    path = _write(tmp_path / "grp" / "build.py", "a = 1\n")
    versions.save_version(path)

    (copy,) = logic.paste_paths([str(tmp_path / "grp")], str(tmp_path), None)
    assert _numbers(os.path.join(copy, "build.py")) == [1]


# -- publish ----------------------------------------------------------------


def test_publishing_a_script_saves_it_as_it_is(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    action = versions.publish_action(path)
    assert action.label == "Publish" and action.confirm is None
    assert action.fn() == "Published Script build.py v001"
    assert action.fn() == "build.py is already published as v001"
    assert _numbers(path) == [1]

    empty = _write(tmp_path / "empty.py", "")
    assert versions.publish_action(empty).fn() == "empty.py is empty: nothing to publish"


def test_publish_check_passes_scripts(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    assert versions.publish_problems(path) == []


def test_products_have_no_publish_problems_by_default(tmp_path):
    assert products.Product().publish_problems(str(tmp_path / "x")) == []


def test_products_publish_the_file_as_it_is_by_default(tmp_path):
    assert script.PRODUCT.publish(str(tmp_path / "a.py")) is None


# -- right-click submenu ----------------------------------------------------


def _save_n(path, n):
    for i in range(1, n + 1):
        _write(path, f"a = {i}\n")
        versions.save_version(path)


def _tags(items):
    return [item.label.split()[0] for item in items]


def test_menu_lists_newest_first_marking_the_current(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    _save_n(path, 3)
    versions.restore_version(path, 2)

    items, more = versions.menu(path)
    assert _tags(items) == ["v003", "v002", "v001"]
    assert [i.current for i in items] == [False, True, False]
    assert items[1].action is None  # nothing to restore
    assert not more


def test_menu_shows_the_newest_five_and_flags_more(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    _save_n(path, 7)
    versions.restore_version(path, 1)

    items, more = versions.menu(path)
    assert _tags(items) == ["v007", "v006", "v005", "v004", "v003"]
    assert more

    _, more = versions.menu(str(_write(tmp_path / "other.py", "b\n")))
    assert not more


def test_menu_entries_show_date_and_size(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    _save_n(path, 1)
    (item,) = versions.menu(path)[0]
    assert "KB" in item.label and "-" in item.label


def test_menu_restore_entries_restore_without_asking(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    _save_n(path, 2)
    _, old = versions.menu(path)[0]
    assert old.action.confirm is None
    old.action.fn()
    assert _read(path) == "a = 1\n"


def test_menu_with_unsaved_changes_has_no_current_and_warns(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    _save_n(path, 2)
    _write(path, "edited\n")

    items, _ = versions.menu(path)
    assert _tags(items) == ["v002", "v001"]
    assert not any(i.current for i in items)
    assert all("lost" in i.action.confirm for i in items)
    assert "not published" in versions.menu_status(path)


def test_menu_is_empty_without_versions(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    assert versions.menu(path) == ([], False)
    assert "No versions" in versions.menu_status(path)
    assert versions.menu_status(_save_and_get(path)) is None


def _save_and_get(path):
    versions.save_version(path)
    return path


# -- tree column ------------------------------------------------------------


def test_tree_label_is_blank_without_versions(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    assert versions.tree_label(path) == ("", True)


def test_tree_label_shows_the_current_version(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    _save_n(path, 3)
    assert versions.tree_label(path) == ("v003", True)

    versions.restore_version(path, 1)
    assert versions.tree_label(path) == ("v001", False)  # not the latest


def test_tree_label_stars_unpublished_edits_of_the_latest(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    _save_n(path, 2)
    _write(path, "edited\n")
    assert versions.tree_label(path) == ("v002*", True)


def test_tree_label_stars_edits_of_a_restored_older_version(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    _save_n(path, 3)
    versions.restore_version(path, 1)
    _write(path, "edited\n")
    assert versions.tree_label(path) == ("v001*", False)


def test_base_version_is_the_last_published_or_restored(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    assert versions.base_version(path) is None
    _save_n(path, 3)
    assert versions.base_version(path).number == 3
    versions.restore_version(path, 2)
    assert versions.base_version(path).number == 2


def test_base_version_falls_back_to_the_latest(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    _write(os.path.join(versions.history_dir(path), "v004.py"), "old\n")  # no record of a base
    assert versions.base_version(path).number == 4


def test_base_version_follows_a_rename(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    _save_n(path, 2)
    versions.restore_version(path, 1)
    new = logic.rename_path(path, "setup")
    assert versions.base_version(new).number == 1


def test_tree_label_is_blank_for_folders(tmp_path):
    assert versions.tree_label(str(tmp_path)) == ("", True)


# -- open Script Editor tabs ------------------------------------------------


def test_restore_tells_the_product_before_replacing(monkeypatch, tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    _save_n(path, 2)
    seen = []
    monkeypatch.setattr(script.PRODUCT, "before_replace", lambda p: seen.append((p, _read(p))))

    versions.restore_version(path, 1)
    assert seen == [(path, "a = 2\n")]  # called while the old content is still there


def test_products_do_nothing_before_replace_by_default(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    folder.PRODUCT.before_replace(path)


def test_script_before_replace_is_safe_without_the_script_editor(tmp_path):
    path = _write(tmp_path / "build.py", "a = 1\n")
    script.PRODUCT.before_replace(path)  # standalone: no Script Editor, no error


def test_script_tabs_use_the_kaiju_file_changed_handler():
    from maya import mel

    mel.eval(script._FILE_CHANGED_MEL)
    assert mel.eval("exists kaijuExecuterTabFileChanged")
    assert mel.eval("exists kaijuWatchExecuterFile")
    # Maya's own handler fails when the Script Editor is docked; never bind it.
    assert "executerTabFileChanged" not in script._OPEN_IN_EDITOR_MEL.replace("kaijuExecuterTabFileChanged", "")
    assert "kaijuWatchExecuterFile" in script._OPEN_IN_EDITOR_MEL


# -- export_into: write new content, keep the old as a version --------------


def _writer(text):
    def write(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    return write


def test_export_into_writes_and_publishes(tmp_path):
    path = _write(tmp_path / "build.py", "")
    assert versions.export_into(path, _writer("a = 1\n")) == "Published Script build.py v001"
    assert _read(path) == "a = 1\n"
    assert _numbers(path) == [1]


def test_export_into_writes_through_a_file_of_the_same_name(tmp_path):
    # Maya ASCII scenes record their own file name, so the writer must see it.
    path = _write(tmp_path / "build.py", "")
    seen = []
    versions.export_into(path, lambda p: (seen.append(os.path.basename(p)), _writer("x\n")(p)))
    assert seen == ["build.py"]


def test_export_into_keeps_unversioned_content_first(tmp_path):
    path = _write(tmp_path / "build.py", "legacy\n")
    assert versions.export_into(path, _writer("fresh\n")) == "Published Script build.py v002"
    old, new = sorted(versions.list_versions(path), key=lambda v: v.number)
    assert _read(old.path) == "legacy\n" and _read(new.path) == "fresh\n"


def test_export_into_same_content_adds_no_version(tmp_path):
    path = _write(tmp_path / "build.py", "")
    versions.export_into(path, _writer("a = 1\n"))
    assert versions.export_into(path, _writer("a = 1\n")) == "Published Script build.py v001"
    assert _numbers(path) == [1]


def test_failed_export_into_changes_nothing(tmp_path):
    path = _write(tmp_path / "build.py", "legacy\n")

    def broken(p):
        _writer("half")(p)
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        versions.export_into(path, broken)
    assert _read(path) == "legacy\n"
    assert versions.list_versions(path) == []


def test_export_into_that_writes_nothing_changes_nothing(tmp_path):
    path = _write(tmp_path / "build.py", "legacy\n")
    with pytest.raises(RuntimeError):
        versions.export_into(path, lambda p: None)
    assert _read(path) == "legacy\n"
    assert versions.list_versions(path) == []


def test_products_have_no_publish_warnings_by_default(tmp_path):
    assert products.Product().publish_warnings(str(tmp_path / "x")) == []


def test_publish_warnings_are_empty_for_unclaimed_paths(tmp_path):
    assert versions.publish_warnings(str(tmp_path / "x.txt")) == []
