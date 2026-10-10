import os

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import data, logic, products, runlog, versions
from kaiju_suite.tools.assembler.products import skin

JOINTS = ("hip", "knee", "ankle")
SETTINGS = ("skinningMethod", "normalizeWeights", "maxInfluences", "maintainMaxInfluences")


def _skeleton(prefix=""):
    cmds.select(clear=True)
    made = []
    for i, name in enumerate(JOINTS):
        made.append(cmds.joint(name=prefix + name, position=(0, 4 - i * 4, 0)))
    cmds.select(clear=True)
    return made


def _mesh(name="leg"):
    return cmds.polyCylinder(name=name, height=8, subdivisionsX=8, subdivisionsY=4, constructionHistory=False)[0]


def _vertex_count(mesh):
    return cmds.polyEvaluate(mesh, vertex=True)


def _skin_cluster(mesh):
    found = cmds.ls(cmds.listHistory(mesh) or [], type="skinCluster")
    return found[0] if found else None


def _bind(mesh, joints, name=None):
    kwargs = {"toSelectedBones": True}
    if name:
        kwargs["name"] = name
    return cmds.skinCluster(*joints, mesh, **kwargs)[0]


def _paint(mesh, cluster, influences):
    """Non-trivial weights: every vertex gets its own mix, some with a zero."""
    for i in range(_vertex_count(mesh)):
        raw = [((i * 7 + k * 3) % 5) for k in range(len(influences))]
        if not any(raw):
            raw[0] = 1
        total = float(sum(raw))
        cmds.skinPercent(
            cluster,
            f"{mesh}.vtx[{i}]",
            transformValue=[(inf, w / total) for inf, w in zip(influences, raw)],
            normalize=False,
        )


def _weights(mesh, cluster):
    """Per vertex, {influence: weight} without zeros."""
    names = cmds.skinCluster(cluster, query=True, influence=True)
    found = []
    for i in range(_vertex_count(mesh)):
        values = cmds.skinPercent(cluster, f"{mesh}.vtx[{i}]", query=True, value=True)
        found.append({n: w for n, w in zip(names, values) if abs(w) > 1e-9})
    return found


def _same_weights(a, b, tol=1e-5):
    assert len(a) == len(b)
    for va, vb in zip(a, b):
        assert set(va) == set(vb), (va, vb)
        for k in va:
            assert abs(va[k] - vb[k]) < tol, (k, va[k], vb[k])


def _settings(cluster):
    return {attr: cmds.getAttr(f"{cluster}.{attr}") for attr in SETTINGS}


def _blend_weights(mesh, cluster):
    return [cmds.getAttr(f"{cluster}.blendWeights[{i}]") for i in range(_vertex_count(mesh))]


def _rig():
    """A skinned leg with painted weights and non-default settings."""
    joints = _skeleton()
    mesh = _mesh()
    cluster = _bind(mesh, joints, name="leg_skin")
    _paint(mesh, cluster, joints)
    cmds.setAttr(f"{cluster}.maxInfluences", 3)
    cmds.setAttr(f"{cluster}.maintainMaxInfluences", True)
    return joints, mesh, cluster


def _publish(tmp_path, *selection, name="leg"):
    path = skin.PRODUCT.create(str(tmp_path), name)
    cmds.select(selection)
    message = versions.publish_action(path).fn()
    return path, message


def _rebuild():
    """A fresh scene with the same joints and an unskinned mesh."""
    cmds.file(new=True, force=True)
    _skeleton()
    return _mesh()


# -- product ----------------------------------------------------------------


def test_skin_is_discovered_and_owns_skin(tmp_path):
    assert skin.PRODUCT in products.discover()
    assert skin.PRODUCT.name == "SkinCluster"
    assert skin.PRODUCT.extensions == (".skin",)
    assert skin.PRODUCT.order == 60
    assert skin.PRODUCT.kind == "skin"
    assert skin.PRODUCT.runnable and skin.PRODUCT.versioned
    path = skin.PRODUCT.creators[0].fn(str(tmp_path), "leg", None)
    assert path == str(tmp_path / "leg.skin") and os.path.getsize(path) == 0
    assert products.product_for(path) is skin.PRODUCT


# -- publish and run --------------------------------------------------------


def test_file_holds_the_mesh_data(new_scene, tmp_path):
    joints, mesh, cluster = _rig()
    path, message = _publish(tmp_path, mesh)
    assert message == "Published SkinCluster leg.skin v001"

    (saved,) = data.read(path, "skin")["meshes"]
    assert saved["mesh"] == "leg"
    assert saved["skinCluster"] == "leg_skin"
    assert saved["influences"] == list(JOINTS)
    assert saved["vertex_count"] == _vertex_count(mesh)
    assert saved["maxInfluences"] == 3 and saved["maintainMaxInfluences"] is True
    assert "blend_weights" not in saved
    assert len(saved["weights"]) == _vertex_count(mesh)
    # Sparse: zeros dropped, [influence index, weight] pairs.
    assert all(w != 0 for vertex in saved["weights"] for _, w in vertex)
    assert any(len(vertex) < len(JOINTS) for vertex in saved["weights"])


def test_round_trip_restores_weights_and_settings(new_scene, tmp_path):
    joints, mesh, cluster = _rig()
    cmds.setAttr(f"{cluster}.normalizeWeights", 2)
    before_weights = _weights(mesh, cluster)
    before_settings = _settings(cluster)
    path, _ = _publish(tmp_path, mesh)

    mesh = _rebuild()
    logic.run_steps([path])

    cluster = _skin_cluster(mesh)
    assert cluster == "leg_skin"
    assert cmds.skinCluster(cluster, query=True, influence=True) == list(JOINTS)
    _same_weights(_weights(mesh, cluster), before_weights)
    assert _settings(cluster) == before_settings


def test_round_trip_restores_dual_quaternion_blend_weights(new_scene, tmp_path):
    joints, mesh, cluster = _rig()
    cmds.setAttr(f"{cluster}.skinningMethod", 2)
    for i in range(_vertex_count(mesh)):
        cmds.setAttr(f"{cluster}.blendWeights[{i}]", (i % 4) / 4.0)
    before = _blend_weights(mesh, cluster)
    path, _ = _publish(tmp_path, mesh)
    assert "blend_weights" in data.read(path, "skin")["meshes"][0]

    mesh = _rebuild()
    skin.PRODUCT.run(path)

    cluster = _skin_cluster(mesh)
    assert cmds.getAttr(f"{cluster}.skinningMethod") == 2
    assert all(abs(a - b) < 1e-5 for a, b in zip(_blend_weights(mesh, cluster), before))


def test_publish_accepts_shapes_and_several_meshes(new_scene, tmp_path):
    joints, mesh, cluster = _rig()
    other = _mesh("arm")
    _bind(other, joints[:2], name="arm_skin")
    shape = cmds.listRelatives(other, shapes=True, noIntermediate=True)[0]
    path, _ = _publish(tmp_path, mesh, shape)
    saved = data.read(path, "skin")["meshes"]
    assert [m["mesh"] for m in saved] == ["leg", "arm"]
    assert saved[1]["influences"] == ["hip", "knee"]
    assert skin.PRODUCT.panel(path).info[0] == "2 meshes, 3 influences"


def test_round_trip_after_an_influence_was_removed(new_scene, tmp_path):
    # Removing an influence leaves a gap in the skinCluster's indices.
    joints = _skeleton()
    extra = cmds.joint(name="extra", position=(2, 0, 0))
    mesh = _mesh()
    cluster = _bind(mesh, [joints[0], extra, joints[1], joints[2]], name="leg_skin")
    cmds.skinCluster(cluster, edit=True, removeInfluence=extra)
    _paint(mesh, cluster, joints)
    before = _weights(mesh, cluster)
    path, _ = _publish(tmp_path, mesh)
    assert data.read(path, "skin")["meshes"][0]["influences"] == list(JOINTS)

    mesh = _rebuild()
    skin.PRODUCT.run(path)
    _same_weights(_weights(mesh, _skin_cluster(mesh)), before)


def test_rerunning_replaces_the_existing_skin_cluster(new_scene, tmp_path):
    joints, mesh, cluster = _rig()
    before = _weights(mesh, cluster)
    path, _ = _publish(tmp_path, mesh)

    # Rebind differently: other influences, other weights.
    cmds.skinCluster(cluster, edit=True, unbind=True)
    _bind(mesh, joints[:2], name="other_skin")

    skin.PRODUCT.run(path)
    assert cmds.ls(type="skinCluster") == ["leg_skin"]
    cluster = _skin_cluster(mesh)
    assert cmds.skinCluster(cluster, query=True, influence=True) == list(JOINTS)
    _same_weights(_weights(mesh, cluster), before)

    # And running again over its own result is the same.
    skin.PRODUCT.run(path)
    assert cmds.ls(type="skinCluster") == ["leg_skin"]
    _same_weights(_weights(mesh, _skin_cluster(mesh)), before)


def _unchanged_after_failed_run(path, mesh):
    cluster = _skin_cluster(mesh)
    before = (cluster, cluster and _weights(mesh, cluster))
    with pytest.raises(Exception) as info:
        skin.PRODUCT.run(path)
    cluster = _skin_cluster(mesh)
    assert (cluster, cluster and _weights(mesh, cluster)) == before
    return str(info.value)


def test_mesh_with_missing_influences_is_skipped_with_a_warning(new_scene, tmp_path):
    joints, mesh, cluster = _rig()
    path, _ = _publish(tmp_path, mesh)

    cmds.file(new=True, force=True)
    mesh = _mesh()
    cmds.joint(name="hip")
    _bind(mesh, ["hip"], name="old_skin")
    before = _weights(mesh, "old_skin")
    with runlog.capture() as run:
        skin.PRODUCT.run(path)
    assert run.warnings == ["Skipped leg: missing influences knee, ankle"]
    assert _skin_cluster(mesh) == "old_skin"
    assert _weights(mesh, "old_skin") == before


def test_missing_mesh_is_skipped_with_a_warning(new_scene, tmp_path):
    joints, mesh, cluster = _rig()
    path, _ = _publish(tmp_path, mesh)

    cmds.file(new=True, force=True)
    _skeleton()
    with runlog.capture() as run:
        skin.PRODUCT.run(path)
    assert run.warnings == ["Skipped missing meshes: leg"]
    assert not cmds.ls(type="skinCluster")


def _without_points(path):
    """Rewrite ``path`` as an older file, saved before point positions were."""
    payload = data.read(path, "skin")
    for record in payload["meshes"]:
        del record["points"]
    data.write(path, "skin", payload)


def _nearest(points, p):
    return min(range(len(points)), key=lambda i: sum((a - b) ** 2 for a, b in zip(points[i], p)))


def _object_points(mesh):
    flat = cmds.xform(f"{mesh}.vtx[*]", query=True, objectSpace=True, translation=True)
    return [tuple(flat[i : i + 3]) for i in range(0, len(flat), 3)]


def test_file_holds_the_point_positions(new_scene, tmp_path):
    joints, mesh, cluster = _rig()
    path, _ = _publish(tmp_path, mesh)

    (saved,) = data.read(path, "skin")["meshes"]
    assert len(saved["points"]) == _vertex_count(mesh)
    for saved_point, point in zip(saved["points"], _object_points(mesh)):
        assert saved_point == pytest.approx(point, abs=1e-5)


def test_changed_topology_remaps_weights_by_closest_point(new_scene, tmp_path):
    joints, mesh, cluster = _rig()
    old_points = _object_points(mesh)
    old_weights = _weights(mesh, cluster)
    path, _ = _publish(tmp_path, mesh)

    cmds.file(new=True, force=True)
    _skeleton()
    mesh = cmds.polyCylinder(name="leg", height=8, subdivisionsX=12, subdivisionsY=5, constructionHistory=False)[0]
    with runlog.capture() as run:
        skin.PRODUCT.run(path)

    (warning,) = run.warnings
    assert "leg" in warning and "closest point" in warning
    assert str(len(old_points)) in warning and str(_vertex_count(mesh)) in warning
    cluster = _skin_cluster(mesh)
    assert cluster == "leg_skin"
    expected = [old_weights[_nearest(old_points, p)] for p in _object_points(mesh)]
    _same_weights(_weights(mesh, cluster), expected)


def test_old_file_without_points_still_round_trips(new_scene, tmp_path):
    joints, mesh, cluster = _rig()
    before = _weights(mesh, cluster)
    path, _ = _publish(tmp_path, mesh)
    _without_points(path)

    mesh = _rebuild()
    with runlog.capture() as run:
        skin.PRODUCT.run(path)
    assert run.warnings == []
    _same_weights(_weights(mesh, _skin_cluster(mesh)), before)


def test_vertex_count_mismatch_raises_and_changes_nothing(new_scene, tmp_path):
    joints, mesh, cluster = _rig()
    path, _ = _publish(tmp_path, mesh)
    _without_points(path)

    cmds.file(new=True, force=True)
    joints = _skeleton()
    mesh = cmds.polyCylinder(name="leg", subdivisionsX=6, constructionHistory=False)[0]
    _bind(mesh, joints, name="old_skin")
    message = _unchanged_after_failed_run(path, mesh)
    assert "leg" in message and "vert" in message.lower()


def test_a_missing_mesh_doesnt_stop_the_others(new_scene, tmp_path):
    joints, mesh, cluster = _rig()
    other = _mesh("arm")
    _bind(other, joints, name="arm_skin")
    path, _ = _publish(tmp_path, mesh, other)

    cmds.file(new=True, force=True)
    _skeleton()
    _mesh()  # leg is fine, arm is missing
    with runlog.capture() as run:
        skin.PRODUCT.run(path)
    assert run.warnings == ["Skipped missing meshes: arm"]
    assert cmds.ls(type="skinCluster") == ["leg_skin"]


def test_one_bad_mesh_stops_the_others_too(new_scene, tmp_path):
    joints, mesh, cluster = _rig()
    other = _mesh("arm")
    _bind(other, joints, name="arm_skin")
    path, _ = _publish(tmp_path, mesh, other)
    _without_points(path)

    cmds.file(new=True, force=True)
    _skeleton()
    _mesh()
    cmds.polyCylinder(name="arm", subdivisionsX=6, constructionHistory=False)  # wrong vertex count
    with pytest.raises(RuntimeError):
        skin.PRODUCT.run(path)
    assert not cmds.ls(type="skinCluster")


def test_empty_file_is_skipped(new_scene, tmp_path):
    path = skin.PRODUCT.create(str(tmp_path), "leg")
    assert logic.run_steps([path]) == [path]
    assert not cmds.ls(type="skinCluster")
    assert skin.PRODUCT.panel(path).info == ["Empty: nothing published into it yet."]


def test_one_undo_reverts_a_run(new_scene, tmp_path):
    joints, mesh, cluster = _rig()
    path, _ = _publish(tmp_path, mesh)
    mesh = _rebuild()
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    skin.PRODUCT.run(path)
    assert _skin_cluster(mesh)
    cmds.undo()
    assert not cmds.ls(type="skinCluster")


def test_one_undo_brings_back_the_replaced_skin_cluster(new_scene, tmp_path):
    joints, mesh, cluster = _rig()
    path, _ = _publish(tmp_path, mesh)
    cmds.skinCluster(cluster, edit=True, unbind=True)
    old = _bind(mesh, joints[:2], name="old_skin")
    _paint(mesh, old, joints[:2])
    before = _weights(mesh, old)
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    skin.PRODUCT.run(path)
    assert _skin_cluster(mesh) == "leg_skin"
    cmds.undo()
    assert _skin_cluster(mesh) == "old_skin"
    _same_weights(_weights(mesh, "old_skin"), before)


# -- publish checks and versions --------------------------------------------


def test_publish_problems(new_scene, tmp_path):
    path = skin.PRODUCT.create(str(tmp_path), "leg")
    cmds.select(clear=True)
    (problem,) = versions.publish_problems(path)
    assert "Nothing selected" in problem

    cmds.select(cmds.createNode("transform"))
    (problem,) = versions.publish_problems(path)
    assert "mesh" in problem.lower()

    joints = _skeleton()
    bare = _mesh("bare")
    plain = _mesh("plain")
    cmds.select(bare, plain)
    (problem,) = versions.publish_problems(path)
    assert "No skinCluster on: bare, plain" in problem

    leg = _mesh()
    _bind(leg, joints)
    cmds.select(leg)
    assert versions.publish_problems(path) == []


def test_publish_unskinned_raises_and_writes_nothing(new_scene, tmp_path):
    path = skin.PRODUCT.create(str(tmp_path), "leg")
    cmds.select(_mesh())
    with pytest.raises(RuntimeError):
        versions.publish_action(path).fn()
    assert os.path.getsize(path) == 0


def test_republishing_adds_a_version_only_on_change(new_scene, tmp_path):
    joints, mesh, cluster = _rig()
    path, message = _publish(tmp_path, mesh)
    assert message.endswith("v001")

    cmds.select(mesh)
    assert versions.publish_action(path).fn().endswith("v001")
    assert [v.number for v in versions.list_versions(path)] == [1]

    cmds.skinPercent(cluster, f"{mesh}.vtx[0]", transformValue=[("hip", 1.0)])
    assert versions.publish_action(path).fn().endswith("v002")


def test_panel_describes_the_file(new_scene, tmp_path):
    joints, mesh, cluster = _rig()
    path, _ = _publish(tmp_path, mesh)
    count = _vertex_count(mesh)
    assert skin.PRODUCT.panel(path).info == [
        "1 mesh, 3 influences",
        f"leg: leg_skin, 3 influences, {count} vertices",
    ]
