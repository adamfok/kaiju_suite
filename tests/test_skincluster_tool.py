import pytest
from maya import cmds

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

    for edit in (lambda: logic.prune([src], 0.01), lambda: logic.mirror_skin([src]), lambda: logic.remove_unused([src])):
        edit()
        cmds.undo()

        assert _all_weights(src) == before
        assert len(cmds.skinCluster(cluster, query=True, influence=True)) == 3
