"""Compare versions: what changed between two versions of a data item.

Comparing needs no scene, only payloads (and files for the versions part).
"""

import pytest

from kaiju_suite.tools.assembler import compare, data, versions
from kaiju_suite.tools.assembler.products import deltamush, joints, mesh, skin


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return str(path)


# -- the generic structural summary -----------------------------------------


def test_same_payload_has_no_changes():
    payload = {"a": 1, "b": [1, 2, {"c": "x"}]}
    assert compare.structural(payload, dict(payload)) == ["No changes."]


def test_added_removed_and_changed_keys():
    lines = compare.structural({"a": 1, "b": "x", "gone": 3}, {"a": 2, "b": "y", "new": 4})
    assert "a: 1 → 2" in lines
    assert "b: 'x' → 'y'" in lines
    assert "Removed gone" in lines
    assert "Added new" in lines


def test_records_are_matched_by_name():
    old = {"items": [{"name": "a", "v": 1}, {"name": "b", "v": 1}]}
    new = {"items": [{"name": "b", "v": 2}, {"name": "c", "v": 1}]}
    lines = compare.structural(old, new)
    assert "items: added c" in lines
    assert "items: removed a" in lines
    assert "items[b].v: 1 → 2" in lines


def test_numeric_lists_are_summarized_with_the_largest_change():
    old = {"points": [[0, 0, 0], [1, 1, 1], [2, 2, 2]]}
    new = {"points": [[0, 0, 0], [1, 1.5, 1], [2, 2, 2.25]]}
    assert compare.structural(old, new) == ["points: 2 of 9 values changed (largest change 0.5)"]


def test_lists_of_another_length_report_the_count():
    assert compare.structural({"x": [1, 2]}, {"x": [1, 2, 3]}) == ["x: 2 → 3 entries"]


def test_long_summaries_are_cut_short():
    old = {f"k{i}": 0 for i in range(50)}
    new = {f"k{i}": 1 for i in range(50)}
    lines = compare.structural(old, new)
    assert len(lines) == compare.MAX_LINES + 1
    assert lines[-1] == f"... and {50 - compare.MAX_LINES} more changes"


def test_data_products_compare_structurally_by_default():
    class _Plain(data.DataProduct):
        name = "Plain"
        kind = "plain"
        extension = ".plain"

    assert _Plain().compare({"a": 1}, {"a": 2}) == ["a: 1 → 2"]


# -- product summaries --------------------------------------------------------


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


def test_skin_counts_vertices_whose_weights_changed():
    old = {"meshes": [_skin_record("body", [[[0, 1.0]], [[0, 0.5], [1, 0.5]], [[1, 1.0]]])]}
    new = {"meshes": [_skin_record("body", [[[0, 1.0]], [[0, 0.25], [1, 0.75]], [[1, 1.0]]])]}
    assert skin.PRODUCT.compare(old, new) == ["body: weights changed on 1 of 3 vertices (largest change 0.25)"]


def test_skin_matches_weights_by_influence_name_not_index():
    old = {"meshes": [_skin_record("body", [[[0, 1.0]], [[1, 1.0]]])]}
    new = {"meshes": [_skin_record("body", [[[1, 1.0]], [[0, 1.0]]], influences=("b_jnt", "a_jnt"))]}
    assert skin.PRODUCT.compare(old, new) == ["No changes."]


def test_skin_reports_meshes_influences_and_settings():
    old = {"meshes": [_skin_record("body", [[[0, 1.0]]]), _skin_record("hat", [[[0, 1.0]]])]}
    new = {
        "meshes": [
            _skin_record("body", [[[0, 0.5], [2, 0.5]]], influences=("a_jnt", "b_jnt", "c_jnt"), maxInfluences=3),
            _skin_record("shoe", [[[0, 1.0]]]),
        ]
    }
    lines = skin.PRODUCT.compare(old, new)
    assert "Added meshes: shoe" in lines
    assert "Removed meshes: hat" in lines
    assert "body: added influences c_jnt" in lines
    assert "body: weights changed on 1 of 1 vertex (largest change 0.5)" in lines
    assert "body: maxInfluences: 4 → 3" in lines


def test_skin_reports_a_changed_vertex_count():
    old = {"meshes": [_skin_record("body", [[[0, 1.0]]])]}
    new = {"meshes": [_skin_record("body", [[[0, 1.0]], [[0, 1.0]]])]}
    assert skin.PRODUCT.compare(old, new) == ["body: vertex count 1 → 2, weights not compared"]


def _mush(weights, **extra):
    record = {"name": "body_dm", "mesh": "body", "vertex_count": 4, "envelope": 1.0, "weights": weights}
    record.update(extra)
    return record


def test_deltamush_counts_vertices_whose_weights_changed():
    old = {"deltamush": [_mush([[0, 0.5]])]}
    new = {"deltamush": [_mush([[0, 0.25], [3, 0.0]], envelope=0.5)]}
    lines = deltamush.PRODUCT.compare(old, new)
    assert "body_dm on body: weights changed on 2 of 4 vertices (largest change 1)" in lines
    assert "body_dm on body: envelope: 1 → 0.5" in lines


def test_deltamush_reports_added_and_removed_nodes():
    old = {"deltamush": [_mush([])]}
    new = {"deltamush": [_mush([], mesh="head")]}
    lines = deltamush.PRODUCT.compare(old, new)
    assert "Added: body_dm on head" in lines
    assert "Removed: body_dm on body" in lines


def _joint(name, parent=None, translate=(0, 0, 0)):
    return {"name": name, "parent": parent, "parent_index": None, "translate": list(translate), "radius": 1.0}


def test_joints_report_added_removed_and_changed_joints():
    old = {"joints": [_joint("root"), _joint("spine", "root"), _joint("tail", "root")]}
    new = {"joints": [_joint("root"), _joint("spine", "root", (0, 1, 0)), _joint("neck", "spine")]}
    lines = joints.PRODUCT.compare(old, new)
    assert lines == ["Added joints: neck", "Removed joints: tail", "Changed joints: spine (translate)"]


def _mesh(name, points, faces=(3,), connects=(0, 1, 2), **extra):
    record = {
        "name": name,
        "parent": None,
        "translate": [0, 0, 0],
        "points": [list(p) for p in points],
        "face_counts": list(faces),
        "face_connects": list(connects),
        "uv_sets": [],
        "hard_edges": [],
    }
    record.update(extra)
    return record


def test_mesh_reports_added_removed_and_moved_points():
    tri = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    old = {"meshes": [_mesh("body", tri), _mesh("hat", tri)]}
    new = {"meshes": [_mesh("body", [(0, 0, 0), (1, 0, 0.5), (0, 1, 0)], translate=[0, 2, 0]), _mesh("shoe", tri)]}
    lines = mesh.PRODUCT.compare(old, new)
    assert "Added meshes: shoe" in lines
    assert "Removed meshes: hat" in lines
    assert "body: 1 of 3 points moved (largest move 0.5)" in lines
    assert "body: translate changed" in lines


def test_mesh_reports_changed_topology():
    old = {"meshes": [_mesh("body", [(0, 0, 0), (1, 0, 0), (0, 1, 0)])]}
    new = {"meshes": [_mesh("body", [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)], (4,), (0, 1, 3, 2))]}
    assert mesh.PRODUCT.compare(old, new) == ["body: topology changed (3 → 4 vertices, 1 → 1 faces)"]


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
    assert panel.info[0] == "v001 → current (v002)"
    assert "body: weights changed on 1 of 1 vertex (largest change 0.25)" in panel.info
    assert panel.actions == []


def test_compare_with_unpublished_changes_lists_every_version(tmp_path):
    path = _skin_file(tmp_path / "body.skin", 0.5)
    versions.save_version(path)
    _skin_file(path, 0.75)
    assert [v.number for v in versions.compare_choices(path)] == [1]
    assert versions.compare_panel(path, 1).info[0] == "v001 → current (not published)"


def test_compare_with_an_empty_file(tmp_path):
    path = _skin_file(tmp_path / "body.skin", 0.5)
    versions.save_version(path)
    _write(path, "")
    assert versions.compare_panel(path, 1).info[1:] == ["The current file is empty."]


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
