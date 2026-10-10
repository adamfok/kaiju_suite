"""The side-by-side compare window's rows: both payloads walked together.

Needs no scene, only payloads (and files for the product part).
"""

from kaiju_suite.tools.assembler import compare, data
from kaiju_suite.tools.assembler.compare import ADDED, CHANGED, REMOVED, SAME
from kaiju_suite.tools.assembler.products import deltamush, joints, mesh, skin


def _by_label(rows):
    return {row.label: row for row in rows}


def _sides(row):
    return row.old, row.new, row.status


# -- the tree -----------------------------------------------------------------


def test_keys_are_matched_and_absent_sides_are_none():
    rows = compare.tree({"a": 1, "b": "x", "gone": 3}, {"a": 2, "b": "x", "new": 4})
    assert [row.label for row in rows] == ["a", "b", "gone", "new"]
    found = _by_label(rows)
    assert _sides(found["a"]) == ("1", "2", CHANGED)
    assert _sides(found["b"]) == ("x", "x", SAME)
    assert _sides(found["gone"]) == ("3", None, REMOVED)
    assert _sides(found["new"]) == (None, "4", ADDED)


def test_records_are_matched_by_name_and_hold_their_fields():
    old = {"joints": [{"name": "root", "tx": 0}, {"name": "arm", "tx": 1}]}
    new = {"joints": [{"name": "arm", "tx": 2}, {"name": "leg", "tx": 0}]}
    (joints,) = compare.tree(old, new)
    assert _sides(joints) == ("2 items", "2 items", CHANGED)
    assert [row.label for row in joints.children] == ["root", "arm", "leg"]
    root, arm, leg = joints.children
    assert root.status == REMOVED and leg.status == ADDED
    # The name is the row's label, not a field row of its own.
    assert [(c.label, c.old, c.new, c.status) for c in arm.children] == [("tx", "1", "2", CHANGED)]
    assert [(c.label, c.old, c.new) for c in leg.children] == [("tx", None, "0")]
    assert all(c.status == ADDED for c in leg.children)


def test_long_number_lists_fold_into_one_row():
    old = {"points": [[0, 0, 0], [1, 1, 1], [2, 2, 2]]}
    new = {"points": [[0, 0, 0], [1, 1.5, 1], [2, 2, 2]]}
    (points,) = compare.tree(old, new)
    assert points.children == []
    assert _sides(points) == ("3 items", "3 items (1 changed, largest change 0.5)", CHANGED)
    (same,) = compare.tree(old, old)
    assert _sides(same) == ("3 items", "3 items", SAME)


def test_folded_lists_of_another_length_show_their_counts():
    (row,) = compare.tree({"x": [[1], [2]]}, {"x": [[1], [2], [3]]})
    assert _sides(row) == ("2 items", "3 items", CHANGED)


def test_folded_entries_can_be_number_dicts_missing_keys_count_as_zero():
    (row,) = compare.tree({"w": [{"a": 1.0}, {"a": 1.0}]}, {"w": [{"a": 0.75, "b": 0.25}, {"a": 1.0}]})
    assert _sides(row) == ("2 items", "2 items (1 changed, largest change 0.25)", CHANGED)


def test_short_number_lists_show_their_values():
    (row,) = compare.tree({"translate": [0, 1, 2]}, {"translate": [0, 1.5, 2]})
    assert _sides(row) == ("0, 1, 2", "0, 1.5, 2", CHANGED)
    assert row.children == []


def test_lists_of_names_are_matched_by_value():
    (row,) = compare.tree({"influences": ["a", "b", "c"]}, {"influences": ["b", "a", "d"]})
    assert _sides(row) == ("3 items", "3 items", CHANGED)
    assert [(c.label, c.old, c.new, c.status) for c in row.children] == [
        ("a", "", "", SAME),
        ("b", "", "", SAME),
        ("c", "", None, REMOVED),
        ("d", None, "", ADDED),
    ]


def test_other_lists_are_matched_by_position():
    (row,) = compare.tree({"x": [["a"], ["b"]]}, {"x": [["a"]]})
    assert [(c.label, c.status) for c in row.children] == [("[0]", SAME), ("[1]", REMOVED)]


def test_a_value_that_changes_kind_is_one_row():
    (row,) = compare.tree({"a": 1}, {"a": {"b": 1}})
    assert (row.old, row.status, row.children) == ("1", CHANGED, [])


def test_has_changes():
    assert not compare.has_changes(compare.tree({"a": [1, 2]}, {"a": [1, 2]}))
    assert compare.has_changes(compare.tree({"a": 1}, {"a": 2}))


# -- products tidy their payloads first ---------------------------------------


def _skin(influences, weights):
    record = {"mesh": "body", "influences": list(influences), "vertex_count": len(weights), "weights": weights}
    return {"meshes": [record]}


def _compare(product, tmp_path, old, new):
    a, b = str(tmp_path / f"a{product.extension}"), str(tmp_path / f"b{product.extension}")
    data.write(a, product.kind, old)
    data.write(b, product.kind, new)
    return product.compare_files(a, b)


def test_skin_weights_match_by_influence_name(tmp_path):
    old = _skin(["a_jnt", "b_jnt"], [[[0, 1.0]], [[1, 1.0]]])
    new = _skin(["b_jnt", "a_jnt"], [[[1, 1.0]], [[0, 1.0]]])
    assert not compare.has_changes(_compare(skin.PRODUCT, tmp_path, old, new))


def test_skin_weight_changes_fold_into_one_row(tmp_path):
    old = _skin(["a_jnt", "b_jnt"], [[[0, 1.0]], [[0, 0.5], [1, 0.5]]])
    new = _skin(["a_jnt", "b_jnt"], [[[0, 1.0]], [[0, 0.25], [1, 0.75]]])
    (meshes,) = _compare(skin.PRODUCT, tmp_path, old, new)
    (body,) = meshes.children
    weights = _by_label(body.children)["weights"]
    assert _sides(weights) == ("2 items", "2 items (1 changed, largest change 0.25)", CHANGED)


def _mush(weights):
    return {"deltamush": [{"name": "body_dm", "mesh": "body", "vertex_count": 4, "weights": weights}]}


def test_deltamush_weights_not_saved_count_as_one(tmp_path):
    assert not compare.has_changes(_compare(deltamush.PRODUCT, tmp_path, _mush([[0, 0.5]]), _mush([[0, 0.5], [3, 1.0]])))
    (nodes,) = _compare(deltamush.PRODUCT, tmp_path, _mush([[0, 0.5]]), _mush([]))
    (node,) = nodes.children
    weights = _by_label(node.children)["weights"]
    assert _sides(weights) == ("0.5, 1, 1, 1", "1, 1, 1, 1", CHANGED)  # short enough to show


def test_skin_and_deltamush_skip_the_rest_points_saved_for_topology_changes(tmp_path):
    old = _skin(["a_jnt"], [[[0, 1.0]]])
    new = _skin(["a_jnt"], [[[0, 1.0]]])
    new["meshes"][0]["points"] = [[0.0, 1.0, 0.0]]
    assert not compare.has_changes(_compare(skin.PRODUCT, tmp_path, old, new))
    new = _mush([[0, 0.5]])
    new["deltamush"][0]["points"] = [[0.0, 1.0, 0.0]]
    assert not compare.has_changes(_compare(deltamush.PRODUCT, tmp_path, _mush([[0, 0.5]]), new))


def _joint(name, parent=None, parent_index=None):
    return {"name": name, "parent": parent, "parent_index": parent_index, "radius": 1.0}


def test_joints_skip_parent_index_which_shifts_when_joints_are_added(tmp_path):
    old = {"joints": [_joint("root"), _joint("spine", "root", 0)]}
    new = {"joints": [_joint("hips"), _joint("root"), _joint("spine", "root", 1)]}
    (rows,) = _compare(joints.PRODUCT, tmp_path, old, new)
    assert [(r.label, r.status) for r in rows.children] == [("root", SAME), ("spine", SAME), ("hips", ADDED)]
    assert "parent_index" not in [r.label for r in rows.children[1].children]


def _mesh(**extra):
    record = {"name": "body", "points": [[0, 0, 0]], "face_counts": [], "face_connects": []}
    record.update(extra)
    return {"meshes": [record]}


def test_mesh_saved_without_normals_or_colors_has_none(tmp_path):
    rows = _compare(mesh.PRODUCT, tmp_path, _mesh(), _mesh(normals=[], color_sets=[]))
    assert not compare.has_changes(rows)
