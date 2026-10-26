import random

import pytest
from maya import cmds

from kaiju_suite.core import matching


def _plane(name, sx=1, x=0.0):
    plane = cmds.polyPlane(name=name, width=2, height=2, sx=sx, sy=1, constructionHistory=False)[0]
    cmds.setAttr(f"{plane}.translateX", x)
    return plane


def _brute(source, target):
    def nearest(p):
        return min(range(len(source)), key=lambda i: sum((a - b) ** 2 for a, b in zip(source[i], p)))

    return [nearest(p) for p in target]


# -- closest_indices -------------------------------------------------------


def test_closest_indices_in_3d():
    source = [(0, 0, 0), (10, 0, 0), (0, 10, 0)]
    target = [(9, 1, 0), (0.1, 0, 0), (1, 8, 0), (0, 0, 0)]

    assert matching.closest_indices(source, target) == [1, 0, 2, 0]


def test_closest_indices_in_2d_for_uvs():
    source = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]
    target = [(0.9, 0.95), (0.1, 0.8), (0.6, 0.2)]

    assert matching.closest_indices(source, target) == [3, 2, 1]


def test_closest_indices_matches_brute_force():
    rng = random.Random(7)
    source = [tuple(rng.uniform(-5, 5) for _ in range(3)) for _ in range(400)]
    target = [tuple(rng.uniform(-6, 6) for _ in range(3)) for _ in range(300)]

    assert matching.closest_indices(source, target) == _brute(source, target)


def test_closest_indices_needs_source_points():
    with pytest.raises(ValueError):
        matching.closest_indices([], [(0, 0, 0)])


# -- modes ------------------------------------------------------------------


def test_modes_and_labels():
    assert matching.MODES == ("closest_point", "uv", "topology")
    assert set(matching.MODE_LABELS) == set(matching.MODES)


def test_check_mode_refuses_an_unknown_mode():
    matching.check_mode("uv")
    with pytest.raises(ValueError) as info:
        matching.check_mode("nearest")
    assert "nearest" in str(info.value)


# -- meshes -----------------------------------------------------------------


def test_rest_points_are_in_object_space(new_scene):
    plane = _plane("a", x=10)

    points = matching.rest_points(plane)

    assert len(points) == 4
    assert sorted(round(p[0], 4) for p in points) == [-1, -1, 1, 1]


def test_rest_points_ignore_deformation(new_scene):
    plane = _plane("a")
    before = matching.rest_points(plane)
    cmds.select(clear=True)
    joint = cmds.joint()
    cmds.skinCluster(joint, plane)
    cmds.setAttr(f"{joint}.translateY", 5)

    assert matching.rest_points(plane) == before


def test_vertex_uvs(new_scene):
    plane = _plane("a")

    uvs = matching.vertex_uvs(plane)

    assert len(uvs) == 4
    assert sorted((round(u, 4), round(v, 4)) for u, v in uvs) == [(0, 0), (0, 1), (1, 0), (1, 1)]


def test_vertex_map_by_topology_is_the_identity(new_scene):
    a, b = _plane("a"), _plane("b", x=50)

    assert matching.vertex_map(a, b, "topology") == [0, 1, 2, 3]


def test_vertex_map_by_topology_needs_the_same_count(new_scene):
    with pytest.raises(ValueError):
        matching.vertex_map(_plane("a"), _plane("b", sx=4), "topology")


def test_vertex_map_by_closest_point_uses_world_space(new_scene):
    a = _plane("a", sx=2)  # x at -1, 0, 1
    b = _plane("b", sx=1, x=1)  # x at 0 and 2

    mapping = matching.vertex_map(a, b, "closest_point")

    a_x = [round(v, 4) for v in cmds.xform(f"{a}.vtx[*]", q=True, ws=True, t=True)[::3]]
    b_x = [round(v, 4) for v in cmds.xform(f"{b}.vtx[*]", q=True, ws=True, t=True)[::3]]
    for target, source in enumerate(mapping):
        assert a_x[source] == min(b_x[target], 1)


def test_vertex_map_by_uv_ignores_where_the_target_is(new_scene):
    a, b = _plane("a"), _plane("b", x=50)

    assert matching.vertex_map(a, b, "uv") == [0, 1, 2, 3]


def test_count_mismatches_names_the_wrong_meshes(new_scene):
    a, b, c = _plane("a"), _plane("b"), _plane("c", sx=4)

    assert matching.count_mismatches(a, [b, c]) == ["c (10)"]
