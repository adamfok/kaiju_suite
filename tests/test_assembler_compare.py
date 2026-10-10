"""The compare windows: a version with the current file, or two items.

Needs no scene, only files. The trees themselves: test_assembler_compare_tree.py.
"""

import pytest

from kaiju_suite.tools.assembler import compare, data, versions


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return str(path)


def _skin_record(mesh_name, weights, influences=("a_jnt", "b_jnt"), **extra):
    record = {
        "mesh": mesh_name,
        "skinCluster": f"{mesh_name}_skin",
        "influences": list(influences),
        "vertex_count": len(weights),
        "skinningMethod": 0,
        "normalizeWeights": 1,
        "maxInfluences": 4,
        "maintainMaxInfluences": False,
        "weights": weights,
    }
    record.update(extra)
    return record


# -- comparing versions -------------------------------------------------------


def _skin_file(path, weight):
    data.write(path, "skin", {"meshes": [_skin_record("body", [[[0, weight], [1, 1 - weight]]])]})
    return str(path)


def test_compare_a_version_with_the_current_file(tmp_path):
    path = _skin_file(tmp_path / "body.skin", 0.5)
    versions.save_version(path)
    _skin_file(path, 0.75)
    versions.save_version(path)

    assert versions.can_compare(path)
    assert [v.number for v in versions.compare_choices(path)] == [1]  # v002 is the current file
    assert [number for _label, number in versions.compare_menu(path)] == [1]
    panel = versions.compare_panel(path, 1)
    # One tree per side, titled with what it shows.
    assert panel.diff.old_title.startswith("v001  ")
    assert panel.diff.new_title == "Current file (v002)"
    assert compare.has_changes(panel.diff.rows)
    assert panel.info == []
    assert panel.actions == []


def test_compare_with_unpublished_changes_lists_every_version(tmp_path):
    path = _skin_file(tmp_path / "body.skin", 0.5)
    versions.save_version(path)
    _skin_file(path, 0.75)
    assert [v.number for v in versions.compare_choices(path)] == [1]
    assert versions.compare_panel(path, 1).diff.new_title == "Current file (not published)"


def test_compare_without_changes_says_so_above_the_trees(tmp_path):
    path = _skin_file(tmp_path / "body.skin", 0.5)
    versions.save_version(path)
    _skin_file(path, 0.5)
    panel = versions.compare_panel(path, 1)
    assert panel.info == ["No changes."]
    assert panel.diff.rows


def test_compare_with_an_empty_file(tmp_path):
    path = _skin_file(tmp_path / "body.skin", 0.5)
    versions.save_version(path)
    _write(path, "")
    panel = versions.compare_panel(path, 1)
    assert panel.info == ["The current file is empty."]
    assert panel.diff is None


# -- comparing two items -----------------------------------------------------


def test_two_items_of_the_same_data_product_can_be_compared(tmp_path):
    a = _skin_file(tmp_path / "a.skin", 0.5)
    b = _skin_file(tmp_path / "b.skin", 0.75)
    assert versions.can_compare_items([a, b])
    panel = versions.compare_items_panel(a, b)
    assert (panel.diff.old_title, panel.diff.new_title) == ("a.skin", "b.skin")
    assert compare.has_changes(panel.diff.rows)


def test_compare_items_needs_exactly_two_files_of_one_product(tmp_path):
    a = _skin_file(tmp_path / "a.skin", 0.5)
    b = _skin_file(tmp_path / "b.skin", 0.75)
    c = _skin_file(tmp_path / "c.skin", 0.25)
    other = str(tmp_path / "body.mesh")
    data.write(other, "mesh", {"meshes": []})
    script = _write(tmp_path / "build.py", "a = 1")
    script2 = _write(tmp_path / "build2.py", "a = 2")
    folder = tmp_path / "sub"
    folder.mkdir()
    assert not versions.can_compare_items([a])
    assert not versions.can_compare_items([a, b, c])
    assert not versions.can_compare_items([a, other])  # different products
    assert not versions.can_compare_items([script, script2])  # products that can't compare
    assert not versions.can_compare_items([a, str(folder)])


def test_compare_items_with_an_empty_one(tmp_path):
    a = _skin_file(tmp_path / "a.skin", 0.5)
    b = _write(tmp_path / "b.skin", "")
    assert versions.can_compare_items([a, b])
    panel = versions.compare_items_panel(a, b)
    assert panel.info == ["b.skin is empty."]
    assert panel.diff is None


def test_only_data_items_can_be_compared(tmp_path):
    script = _write(tmp_path / "build.py", "a = 1\n")
    versions.save_version(script)
    assert not versions.can_compare(script)
    folder = tmp_path / "sub"
    folder.mkdir()
    assert not versions.can_compare(str(folder))


def test_compare_with_a_missing_version_raises(tmp_path):
    path = _skin_file(tmp_path / "body.skin", 0.5)
    versions.save_version(path)
    with pytest.raises(FileNotFoundError):
        versions.compare_panel(path, 7)
