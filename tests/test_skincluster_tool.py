import pytest
from maya import cmds

from kaiju_suite.datatypes import skin
from kaiju_suite.tools.skincluster_tool import logic


def _joint(name, x):
    cmds.select(clear=True)
    return cmds.joint(name=name, position=(x, 0, 0))


def _plane(name, sx=1, x=0.0):
    plane = cmds.polyPlane(name=name, width=2, height=2, sx=sx, sy=1, constructionHistory=False)[0]
    cmds.setAttr(f"{plane}.translateX", x)
    return plane


def _skinned_source():
    """A 2x2 plane: its -X half on ``left``, its +X half on ``right``."""
    left, right = _joint("left", -1), _joint("right", 1)
    plane = _plane("src")
    cluster = cmds.skinCluster(left, right, plane, toSelectedBones=True)[0]
    for v in range(cmds.polyEvaluate(plane, vertex=True)):
        x = cmds.pointPosition(f"{plane}.vtx[{v}]", world=True)[0]
        cmds.skinPercent(cluster, f"{plane}.vtx[{v}]", transformValue=[(left if x < 0 else right, 1.0)])
    return plane, cluster


def _weights(mesh, vertex):
    cluster = logic.skin_cluster(mesh)
    influences = cmds.skinCluster(cluster, query=True, influence=True)
    values = cmds.skinPercent(cluster, f"{mesh}.vtx[{vertex}]", query=True, value=True)
    return {name: round(w, 4) for name, w in zip(influences, values) if w > 1e-6}


def _all_weights(mesh):
    return [_weights(mesh, v) for v in range(cmds.polyEvaluate(mesh, vertex=True))]


# -- copy skin --------------------------------------------------------------


def test_copy_by_closest_point_binds_an_unskinned_target(new_scene):
    src, _ = _skinned_source()
    target = _plane("dst", sx=4)

    clusters = logic.copy_skin(src, [target], "closest_point")

    assert clusters == [logic.skin_cluster(target)]
    assert sorted(cmds.skinCluster(clusters[0], query=True, influence=True)) == ["left", "right"]
    for v in range(cmds.polyEvaluate(target, vertex=True)):
        x = cmds.pointPosition(f"{target}.vtx[{v}]", world=True)[0]
        if abs(x) > 0.6:
            assert _weights(target, v) == {"left" if x < 0 else "right": 1.0}


def test_copy_by_uv_ignores_where_the_target_is(new_scene):
    src, _ = _skinned_source()
    target = _plane("dst")
    cmds.setAttr(f"{target}.translateX", 50)

    logic.copy_skin(src, [target], "uv")

    assert _all_weights(target) == _all_weights(src)


def test_copy_by_topology_matches_vertex_ids(new_scene):
    src, _ = _skinned_source()
    target = _plane("dst")
    cmds.move(30, 5, 0, f"{target}.vtx[0]", relative=True)
    cmds.setAttr(f"{target}.translateX", 50)

    logic.copy_skin(src, [target], "topology")

    assert _all_weights(target) == _all_weights(src)


def test_copy_by_topology_needs_the_same_vertex_count(new_scene):
    src, _ = _skinned_source()
    target = _plane("dst", sx=4)

    with pytest.raises(ValueError) as info:
        logic.copy_skin(src, [target], "topology")

    assert "dst" in str(info.value)
    assert logic.skin_cluster(target) is None


def test_copy_adds_missing_influences_to_a_skinned_target(new_scene):
    src, _ = _skinned_source()
    other = _joint("other", 0)
    target = _plane("dst")
    cmds.skinCluster("left", other, target, toSelectedBones=True)

    logic.copy_skin(src, [target], "topology")

    assert sorted(cmds.skinCluster(logic.skin_cluster(target), query=True, influence=True)) == [
        "left",
        "other",
        "right",
    ]
    assert _all_weights(target) == _all_weights(src)


def test_copy_to_several_targets(new_scene):
    src, _ = _skinned_source()
    targets = [_plane(f"dst{i}") for i in range(2)]

    clusters = logic.copy_skin(src, targets, "topology")

    assert len(clusters) == 2
    for target in targets:
        assert _all_weights(target) == _all_weights(src)


def test_copy_needs_a_skinned_source(new_scene):
    with pytest.raises(ValueError) as info:
        logic.copy_skin(_plane("src"), [_plane("dst")], "closest_point")

    assert "src" in str(info.value)


def test_copy_refuses_an_unknown_mode(new_scene):
    src, _ = _skinned_source()

    with pytest.raises(ValueError):
        logic.copy_skin(src, [_plane("dst")], "nearest")


@pytest.mark.parametrize("mode", logic.MODES)
def test_copy_is_one_undo_step(new_scene, mode):
    cmds.undoInfo(state=True)
    src, _ = _skinned_source()
    target = _plane("dst")

    logic.copy_skin(src, [target], mode)
    cmds.undo()

    assert logic.skin_cluster(target) is None


# -- mirror -----------------------------------------------------------------


def test_mirror_skin_copies_one_side_onto_the_other(new_scene):
    left, right = _joint("L_jnt", -1), _joint("R_jnt", 1)
    plane = _plane("body", sx=2)
    cluster = cmds.skinCluster(left, right, plane, toSelectedBones=True)[0]
    positive = [v for v in range(6) if cmds.pointPosition(f"{plane}.vtx[{v}]")[0] > 0.5]
    negative = [v for v in range(6) if cmds.pointPosition(f"{plane}.vtx[{v}]")[0] < -0.5]
    cmds.skinPercent(cluster, [f"{plane}.vtx[{v}]" for v in positive], transformValue=[(right, 1.0)])
    cmds.skinPercent(cluster, [f"{plane}.vtx[{v}]" for v in negative], transformValue=[(right, 1.0)])

    logic.mirror_skin([plane], positive_to_negative=True)

    for v in negative:
        assert _weights(plane, v) == {"L_jnt": 1.0}
    for v in positive:
        assert _weights(plane, v) == {"R_jnt": 1.0}


# -- clean up ---------------------------------------------------------------


def test_prune_removes_small_weights(new_scene):
    src, cluster = _skinned_source()
    cmds.skinPercent(cluster, f"{src}.vtx[0]", transformValue=[("left", 0.995), ("right", 0.005)])

    logic.prune([src], 0.01)

    assert _weights(src, 0) == {"left": 1.0}


def test_remove_unused_influences(new_scene):
    src, cluster = _skinned_source()
    unused = _joint("unused", 0)
    cmds.skinCluster(cluster, edit=True, addInfluence=unused, weight=0)

    removed = logic.remove_unused([src])

    assert removed == ["unused"]
    assert sorted(cmds.skinCluster(cluster, query=True, influence=True)) == ["left", "right"]


def test_influences(new_scene):
    src, _ = _skinned_source()

    assert sorted(logic.influences([src])) == sorted(cmds.ls(["left", "right"], long=True))


def test_meshes_takes_shapes_and_components(new_scene):
    a, b = _plane("a"), _plane("b")
    shape = cmds.listRelatives(b, shapes=True, fullPath=True)[0]

    assert logic.meshes([f"{a}.vtx[0]", shape, a]) == cmds.ls([a, b], long=True)


def test_clean_up_and_mirror_are_one_undo_step_each(new_scene):
    cmds.undoInfo(state=True)
    src, cluster = _skinned_source()
    unused = _joint("unused", 0)
    cmds.skinCluster(cluster, edit=True, addInfluence=unused, weight=0)
    cmds.skinPercent(cluster, f"{src}.vtx[0]", transformValue=[("left", 0.995), ("right", 0.005)])
    before = _all_weights(src)

    edits = (lambda: logic.prune([src], 0.01), lambda: logic.mirror_skin([src]), lambda: logic.remove_unused([src]))
    for edit in edits:
        edit()
        cmds.undo()

        assert _all_weights(src) == before
        assert len(cmds.skinCluster(cluster, query=True, influence=True)) == 3


# -- skin weights -----------------------------------------------------------


def _three_joint_plane():
    """A 2x1-face plane (6 vertices) on joints ``a``, ``b`` and ``c``.
    Vertices 0-2 are at x = -1, 0, 1 (z = 1); vertices 3-5 behind them (z = -1)."""
    joints = [_joint(name, x) for name, x in (("a", -1), ("b", 0), ("c", 1))]
    plane = _plane("body", sx=2)
    cluster = cmds.skinCluster(*joints, plane, toSelectedBones=True, maximumInfluences=3, obeyMaxInfluences=False)[0]
    for v in range(6):
        cmds.skinPercent(cluster, f"{plane}.vtx[{v}]", transformValue=[("a", 1.0)])
    return plane, cluster


def test_limit_influences_keeps_the_largest_and_renormalizes(new_scene):
    plane, cluster = _three_joint_plane()
    cmds.skinPercent(cluster, f"{plane}.vtx[0]", transformValue=[("a", 0.5), ("b", 0.3), ("c", 0.2)])
    cmds.skinPercent(cluster, f"{plane}.vtx[1]", transformValue=[("a", 0.6), ("b", 0.4)])

    logic.limit_influences([plane], 2)

    assert _weights(plane, 0) == {"a": 0.625, "b": 0.375}
    assert _weights(plane, 1) == {"a": 0.6, "b": 0.4}
    assert _weights(plane, 2) == {"a": 1.0}


def test_limit_influences_needs_at_least_one(new_scene):
    plane, _ = _three_joint_plane()

    with pytest.raises(ValueError):
        logic.limit_influences([plane], 0)


def test_normalize_makes_each_vertex_sum_to_one(new_scene):
    plane, cluster = _three_joint_plane()
    cmds.setAttr(f"{cluster}.normalizeWeights", 0)
    cmds.skinPercent(cluster, f"{plane}.vtx[0]", transformValue=[("a", 0.2), ("b", 0.2)], normalize=False)
    assert sum(_weights(plane, 0).values()) == pytest.approx(0.4)

    logic.normalize([plane])

    assert _weights(plane, 0) == {"a": 0.5, "b": 0.5}
    assert _weights(plane, 1) == {"a": 1.0}


def test_normalize_is_one_undo_step(new_scene):
    cmds.undoInfo(state=True)
    plane, cluster = _three_joint_plane()
    cmds.setAttr(f"{cluster}.normalizeWeights", 0)
    cmds.skinPercent(cluster, f"{plane}.vtx[0]", transformValue=[("a", 0.2), ("b", 0.2)], normalize=False)
    before = _all_weights(plane)

    logic.normalize([plane])
    cmds.undo()

    assert _all_weights(plane) == before


def test_hammer_averages_each_vertex_from_its_neighbors(new_scene):
    plane, cluster = _three_joint_plane()
    # Vertex 1's neighbors are 0, 2 and 4.
    cmds.skinPercent(cluster, f"{plane}.vtx[2]", transformValue=[("c", 1.0)])
    cmds.skinPercent(cluster, f"{plane}.vtx[4]", transformValue=[("b", 1.0)])
    cmds.skinPercent(cluster, f"{plane}.vtx[1]", transformValue=[("c", 1.0)])

    logic.hammer([f"{plane}.vtx[1]"])

    assert _weights(plane, 1) == {"a": 0.3333, "b": 0.3333, "c": 0.3333}
    assert _weights(plane, 2) == {"c": 1.0}


def test_hammer_needs_vertices(new_scene):
    plane, _ = _three_joint_plane()

    with pytest.raises(ValueError):
        logic.hammer([plane])


def test_copy_and_paste_a_vertex_weights(new_scene):
    plane, cluster = _three_joint_plane()
    cmds.skinPercent(cluster, f"{plane}.vtx[0]", transformValue=[("b", 0.7), ("c", 0.3)])

    copied = logic.copy_vertex_weights(f"{plane}.vtx[0]")
    logic.paste_vertex_weights(copied, [f"{plane}.vtx[3:4]", f"{plane}.e[2]"])

    assert {k: round(w, 4) for k, w in copied.items()} == {"b": 0.7, "c": 0.3}
    # Edge 2 runs between vertices 1 and 2.
    for v in (1, 2, 3, 4):
        assert _weights(plane, v) == {"b": 0.7, "c": 0.3}
    assert _weights(plane, 5) == {"a": 1.0}


def test_copy_vertex_weights_needs_one_vertex(new_scene):
    plane, _ = _three_joint_plane()

    with pytest.raises(ValueError):
        logic.copy_vertex_weights(f"{plane}.vtx[0:1]")


def test_paste_needs_the_influences_on_the_target(new_scene):
    plane, cluster = _three_joint_plane()
    cmds.skinPercent(cluster, f"{plane}.vtx[0]", transformValue=[("c", 1.0)])
    copied = logic.copy_vertex_weights(f"{plane}.vtx[0]")
    other = _plane("other", x=5)
    cmds.skinCluster("a", "b", other, toSelectedBones=True)

    with pytest.raises(ValueError) as info:
        logic.paste_vertex_weights(copied, [f"{other}.vtx[0]"])

    assert "c" in str(info.value)


def test_add_influences(new_scene):
    plane, cluster = _skinned_source()
    extra = _joint("extra", 0)
    before = _all_weights(plane)

    added = logic.add_influences(plane, [extra, "left"])

    assert added == ["extra"]
    assert sorted(cmds.skinCluster(cluster, query=True, influence=True)) == ["extra", "left", "right"]
    assert _all_weights(plane) == before


def test_add_influences_needs_joints(new_scene):
    plane, _ = _skinned_source()

    with pytest.raises(ValueError):
        logic.add_influences(plane, [])


def test_remove_influences_keeps_weights_normalized(new_scene):
    plane, cluster = _three_joint_plane()
    cmds.skinPercent(cluster, f"{plane}.vtx[0]", transformValue=[("a", 0.5), ("b", 0.3), ("c", 0.2)])
    cmds.skinPercent(cluster, f"{plane}.vtx[2]", transformValue=[("c", 1.0)])

    removed = logic.remove_influences(plane, ["c"])

    assert removed == ["c"]
    assert sorted(cmds.skinCluster(cluster, query=True, influence=True)) == ["a", "b"]
    assert _weights(plane, 0) == {"a": 0.625, "b": 0.375}
    # Vertex 2 (x = 1) was only on c: it goes to the closest joint left, b (x = 0).
    assert _weights(plane, 2) == {"b": 1.0}
    for weights in _all_weights(plane):
        assert sum(weights.values()) == pytest.approx(1.0, abs=1e-3)


def test_remove_influences_cant_remove_them_all(new_scene):
    plane, cluster = _skinned_source()

    with pytest.raises(ValueError):
        logic.remove_influences(plane, ["left", "right"])

    assert len(cmds.skinCluster(cluster, query=True, influence=True)) == 2


def test_skin_weight_edits_are_one_undo_step_each(new_scene):
    cmds.undoInfo(state=True)
    plane, cluster = _three_joint_plane()
    cmds.skinPercent(cluster, f"{plane}.vtx[0]", transformValue=[("a", 0.5), ("b", 0.3), ("c", 0.2)])
    cmds.skinPercent(cluster, f"{plane}.vtx[2]", transformValue=[("c", 1.0)])
    extra = _joint("extra", 0)
    before = _all_weights(plane)
    copied = logic.copy_vertex_weights(f"{plane}.vtx[0]")

    edits = (
        lambda: logic.limit_influences([plane], 1),
        lambda: logic.hammer([f"{plane}.vtx[1]", f"{plane}.vtx[2]"]),
        lambda: logic.paste_vertex_weights(copied, [f"{plane}.vtx[5]"]),
        lambda: logic.add_influences(plane, [extra]),
        lambda: logic.remove_influences(plane, ["c"]),
    )
    for edit in edits:
        edit()
        cmds.undo()

        assert _all_weights(plane) == before
        assert sorted(cmds.skinCluster(cluster, query=True, influence=True)) == ["a", "b", "c"]


# -- export / import --------------------------------------------------------


def test_export_and_import_weights(new_scene, tmp_path):
    plane, _ = _skinned_source()
    before = _all_weights(plane)
    path = logic.export_weights(str(tmp_path / "src.skin"), [plane])
    assert path.endswith("src.skin")

    cmds.skinCluster(logic.skin_cluster(plane), edit=True, unbind=True)
    assert logic.skin_cluster(plane) is None
    message = logic.import_weights(path)
    assert message.startswith("Bound 1 mesh")
    assert _all_weights(plane) == before


def test_export_needs_skinned_meshes(new_scene, tmp_path):
    bare = _plane("bare")
    with pytest.raises(ValueError, match="No skinCluster on: bare"):
        logic.export_weights(str(tmp_path / "bare.skin"), [bare])
    with pytest.raises(ValueError, match="No meshes"):
        logic.export_weights(str(tmp_path / "none.skin"), [])


def test_import_refuses_another_kind_of_file(new_scene, tmp_path):
    path = tmp_path / "a.skin"
    path.write_text('{"kaiju": "mesh", "format": 1, "data": {}}')
    with pytest.raises(ValueError):
        logic.import_weights(str(path))


def test_import_weights_is_one_undo_step(new_scene, tmp_path):
    cmds.undoInfo(state=True)
    plane, cluster = _skinned_source()
    path = logic.export_weights(str(tmp_path / "src.skin"), [plane])
    for v in range(cmds.polyEvaluate(plane, vertex=True)):
        cmds.skinPercent(cluster, f"{plane}.vtx[{v}]", transformValue=[("left", 0.5), ("right", 0.5)])
    before = _all_weights(plane)

    logic.import_weights(path)
    assert _all_weights(plane) != before
    cmds.undo()
    assert _all_weights(plane) == before


# -- QC tab -----------------------------------------------------------------


def test_qc_runs_the_skin_checks_on_the_selected_meshes(new_scene):
    src, _ = _skinned_source()
    bare = _plane("bare")
    cmds.select(src, bare)

    found = {check.key: problems for check, problems in logic.run_qc(cmds.ls(selection=True, long=True))}

    assert list(found) == ["skinned", "normalized", "influence_count", "small_weights", "unused"]
    assert found["skinned"] == ["bare: no skinCluster"]


def test_qc_uses_the_settings_given(new_scene):
    src, _ = _skinned_source()
    settings = logic.qc_defaults()
    settings["unused"]["enabled"] = False

    found = [check.key for check, _ in logic.run_qc(cmds.ls(src, long=True), settings)]

    assert "unused" not in found


def test_qc_needs_meshes(new_scene):
    joint = _joint("j", 0)

    with pytest.raises(ValueError, match="No meshes selected"):
        logic.run_qc(cmds.ls(joint, long=True))


def test_qc_refuses_bad_settings(new_scene):
    src, _ = _skinned_source()

    with pytest.raises(ValueError, match="max_influences"):
        logic.run_qc(cmds.ls(src, long=True), {"influence_count": {"max_influences": "four"}})


def test_qc_settings_are_saved_per_user(new_scene):
    logic.save_qc_setting("influence_count", "max_influences", 6)
    try:
        assert logic.qc_settings()["influence_count"]["max_influences"] == 6
    finally:
        cmds.optionVar(remove="kaiju_suite_datatype_skin_qc_influence_count_max_influences")


def test_select_problem_selects_what_it_points_at(new_scene):
    src, cluster = _skinned_source()
    cmds.skinPercent(cluster, f"{src}.vtx[0]", transformValue=[("left", 0.9995), ("right", 0.0005)])
    [(_, [problem])] = logic.run_qc(cmds.ls(src, long=True), {
        key: {"enabled": key == "small_weights"} for key in logic.qc_defaults()
    })

    assert logic.select_problem(problem) == ["src.vtx[0]"]
    assert cmds.ls(selection=True) == ["src.vtx[0]"]


def test_select_problem_skips_what_is_gone(new_scene):
    from kaiju_suite.core.checks import Problem

    _plane("here")
    selected = logic.select_problem(Problem("x", ["here", "gone"]))

    assert selected == ["here"]
    assert cmds.ls(selection=True) == ["here"]


def test_qc_with_nothing_selected_checks_nothing(new_scene):
    _skinned_source()

    with pytest.raises(ValueError, match="No meshes selected"):
        logic.run_qc([])


def test_qc_settings_are_the_ones_builder_publish_uses(new_scene):
    from kaiju_suite import datatypes

    logic.save_qc_setting("small_weights", "threshold", 0.05)
    try:
        assert datatypes.qc_settings(skin)["small_weights"]["threshold"] == 0.05
    finally:
        cmds.optionVar(remove="kaiju_suite_datatype_skin_qc_small_weights_threshold")
