import os

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import data, logic, products, runlog, versions
from kaiju_suite.tools.assembler.products import deltamush

SETTINGS = {
    "smoothingIterations": 7,
    "smoothingStep": 0.75,
    "inwardConstraint": 0.25,
    "outwardConstraint": 0.5,
    "distanceWeight": 0.3,
    "displacement": 0.6,
    "pinBorderVertices": False,
    "envelope": 0.8,
}
PAINTED = {3: 0.25, 10: 0.0, 17: 0.5}


def _mesh(name="body"):
    """A subdivided cube (26 vertices) with no history."""
    return cmds.polyCube(name=name, width=2, height=4, depth=2, sx=2, sy=2, sz=2, ch=False)[0]


def _skinned(name="body"):
    """A cube bound to two joints, so it has a skinCluster to sit on top of."""
    mesh = _mesh(name)
    cmds.select(clear=True)
    cmds.joint(name=f"{name}_lo_jnt", position=(0, -2, 0))
    cmds.joint(name=f"{name}_hi_jnt", position=(0, 2, 0))
    cmds.skinCluster(f"{name}_lo_jnt", f"{name}_hi_jnt", mesh, toSelectedBones=True, name=f"{name}_skin")
    cmds.select(clear=True)
    return mesh


def _mush(mesh, name="body_dm", settings=SETTINGS, painted=PAINTED):
    node = cmds.deltaMush(mesh, name=name)[0]
    for attr, value in settings.items():
        cmds.setAttr(f"{node}.{attr}", value)
    for vertex, weight in painted.items():
        cmds.setAttr(f"{node}.weightList[0].weights[{vertex}]", weight)
    return node


def _settings(node):
    return {attr: pytest.approx(cmds.getAttr(f"{node}.{attr}")) for attr in SETTINGS}


def _weights(node, mesh):
    return [round(w, 5) for w in cmds.percent(node, f"{mesh}.vtx[*]", query=True, value=True)]


def _deformers(mesh):
    """The mesh's deformers, last evaluated first."""
    return cmds.ls(cmds.listHistory(mesh), type="geometryFilter")


def _points(mesh):
    flat = cmds.xform(f"{mesh}.vtx[*]", query=True, worldSpace=True, translation=True)
    return [round(v, 4) for v in flat]


def _publish(tmp_path, *selection, name="mush"):
    path = deltamush.PRODUCT.create(str(tmp_path), name)
    cmds.select(selection)
    message = versions.publish_action(path).fn()
    return path, message


# -- product ----------------------------------------------------------------


def test_deltamush_is_discovered_and_owns_dmsh(tmp_path):
    assert deltamush.PRODUCT in products.discover()
    assert deltamush.PRODUCT.name == "DeltaMush"
    assert deltamush.PRODUCT.kind == "deltamush"
    assert deltamush.PRODUCT.extensions == (".dmsh",)
    assert deltamush.PRODUCT.order == 70
    assert deltamush.PRODUCT.runnable and deltamush.PRODUCT.versioned
    path = deltamush.PRODUCT.creators[0].fn(str(tmp_path), "mush", None)
    assert path == str(tmp_path / "mush.dmsh") and os.path.getsize(path) == 0
    assert products.product_for(path) is deltamush.PRODUCT


# -- publish ----------------------------------------------------------------


def test_publish_saves_settings_and_sparse_weights(new_scene, tmp_path):
    mesh = _mesh()
    _mush(mesh)
    path, message = _publish(tmp_path, mesh)
    assert message == "Published DeltaMush mush.dmsh v001"

    (record,) = data.read(path, "deltamush")["deltamush"]
    assert record["name"] == "body_dm"
    assert record["mesh"] == "body"
    assert record["vertex_count"] == 26
    for attr, value in SETTINGS.items():
        assert record[attr] == pytest.approx(value)
    assert sorted(map(tuple, record["weights"])) == sorted(PAINTED.items())


def test_publish_saves_every_deltamush_on_each_mesh(new_scene, tmp_path):
    body = _mesh("body")
    head = _mesh("head")
    _mush(body, "body_dm")
    _mush(body, "body_dm2", painted={})
    _mush(head, "head_dm", painted={1: 0.5})
    path, _ = _publish(tmp_path, body, head)
    records = data.read(path, "deltamush")["deltamush"]
    assert sorted((r["name"], r["mesh"]) for r in records) == [
        ("body_dm", "body"),
        ("body_dm2", "body"),
        ("head_dm", "head"),
    ]


def test_publish_saves_weights_of_the_selected_geometry(new_scene, tmp_path):
    # One deltaMush on two meshes: each mesh's weights are its own index's.
    body = _mesh("body")
    head = _mesh("head")
    node = cmds.deltaMush(body, head, name="shared_dm")[0]
    index = dict(zip(
        [cmds.listRelatives(g, parent=True)[0] for g in cmds.deformer(node, query=True, geometry=True)],
        cmds.deformer(node, query=True, geometryIndices=True),
    ))
    cmds.setAttr(f"{node}.weightList[{index['body']}].weights[2]", 0.1)
    cmds.setAttr(f"{node}.weightList[{index['head']}].weights[5]", 0.9)
    path, _ = _publish(tmp_path, body, head)
    records = {r["mesh"]: r for r in data.read(path, "deltamush")["deltamush"]}
    assert [tuple(w) for w in records["body"]["weights"]] == [(2, pytest.approx(0.1))]
    assert [tuple(w) for w in records["head"]["weights"]] == [(5, pytest.approx(0.9))]


# -- run --------------------------------------------------------------------


def test_round_trip_on_a_skinned_mesh(new_scene, tmp_path):
    mesh = _skinned()
    _mush(mesh)
    cmds.setAttr("body_hi_jnt.rotateZ", 40)
    before = _points(mesh)
    path, _ = _publish(tmp_path, mesh)

    cmds.file(new=True, force=True)
    mesh = _skinned()
    cmds.setAttr("body_hi_jnt.rotateZ", 40)
    logic.run_steps([path])

    assert _deformers(mesh) == ["body_dm", "body_skin"]  # deltaMush on top of skin
    assert _settings("body_dm") == SETTINGS
    expected = [1.0] * 26
    for vertex, weight in PAINTED.items():
        expected[vertex] = weight
    assert _weights("body_dm", mesh) == expected
    assert _points(mesh) == pytest.approx(before, abs=1e-3)


def test_run_on_a_mesh_without_deformers(new_scene, tmp_path):
    mesh = _mesh()
    _mush(mesh)
    path, _ = _publish(tmp_path, mesh)
    cmds.file(new=True, force=True)
    mesh = _mesh()
    message = deltamush.PRODUCT.run(path)
    assert "body_dm" in message
    assert _deformers(mesh) == ["body_dm"]
    assert _weights("body_dm", mesh)[3] == 0.25


def test_shared_deltamush_restores_weights_per_geometry(new_scene, tmp_path):
    body = _mesh("body")
    head = _mesh("head")
    node = cmds.deltaMush(head, body, name="shared_dm")[0]
    geometries = [cmds.listRelatives(g, parent=True)[0] for g in cmds.deformer(node, query=True, geometry=True)]
    index = dict(zip(geometries, cmds.deformer(node, query=True, geometryIndices=True)))
    cmds.setAttr(f"{node}.weightList[{index['body']}].weights[2]", 0.1)
    cmds.setAttr(f"{node}.weightList[{index['head']}].weights[5]", 0.9)
    path, _ = _publish(tmp_path, body, head)

    cmds.file(new=True, force=True)
    body = _mesh("body")
    head = _mesh("head")
    deltamush.PRODUCT.run(path)
    assert cmds.ls(type="deltaMush") == ["shared_dm"]
    assert _weights("shared_dm", body)[2] == 0.1 and _weights("shared_dm", body).count(1.0) == 25
    assert _weights("shared_dm", head)[5] == 0.9 and _weights("shared_dm", head).count(1.0) == 25


def test_rerunning_replaces_the_same_named_node(new_scene, tmp_path):
    mesh = _skinned()
    _mush(mesh)
    path, _ = _publish(tmp_path, mesh)
    cmds.setAttr("body_dm.smoothingIterations", 2)
    cmds.setAttr("body_dm.weightList[0].weights[20]", 0.1)

    deltamush.PRODUCT.run(path)
    deltamush.PRODUCT.run(path)
    assert cmds.ls(type="deltaMush") == ["body_dm"]
    assert _deformers(mesh) == ["body_dm", "body_skin"]
    assert _settings("body_dm") == SETTINGS
    assert _weights("body_dm", mesh)[20] == 1.0


def test_other_deltamush_nodes_are_left_alone(new_scene, tmp_path):
    mesh = _mesh()
    _mush(mesh)
    path, _ = _publish(tmp_path, mesh)
    cmds.delete("body_dm")
    _mush(mesh, "keep_dm", painted={})
    deltamush.PRODUCT.run(path)
    assert sorted(cmds.ls(type="deltaMush")) == ["body_dm", "keep_dm"]
    assert _deformers(mesh) == ["body_dm", "keep_dm"]


def test_missing_mesh_is_skipped_with_a_warning(new_scene, tmp_path):
    body = _mesh("body")
    head = _mesh("head")
    _mush(body, "body_dm")
    _mush(head, "head_dm")
    path, _ = _publish(tmp_path, body, head)

    cmds.file(new=True, force=True)
    _mesh("body")
    with runlog.capture() as run:
        deltamush.PRODUCT.run(path)
    assert run.warnings == ["Skipped missing meshes: head"]
    assert cmds.ls(type="deltaMush") == ["body_dm"]


def test_all_meshes_missing_is_a_warning_not_an_error(new_scene, tmp_path):
    _mush(_mesh("body"), "body_dm")
    path, _ = _publish(tmp_path, "body")
    cmds.file(new=True, force=True)
    with runlog.capture() as run:
        deltamush.PRODUCT.run(path)
    assert run.warnings == ["Skipped missing meshes: body"]
    assert not cmds.ls(type="deltaMush")


def test_vertex_count_mismatch_raises_and_changes_nothing(new_scene, tmp_path):
    mesh = _mesh()
    _mush(mesh)
    path, _ = _publish(tmp_path, mesh)

    cmds.file(new=True, force=True)
    mesh = cmds.polyCube(name="body", ch=False)[0]  # 8 vertices, not 26
    _mush(mesh, settings={"smoothingIterations": 3}, painted={})
    with pytest.raises(RuntimeError) as info:
        deltamush.PRODUCT.run(path)
    assert "body" in str(info.value) and "26" in str(info.value) and "8" in str(info.value)
    assert cmds.ls(type="deltaMush") == ["body_dm"]
    assert cmds.getAttr("body_dm.smoothingIterations") == 3


def test_name_taken_by_another_node_raises_and_changes_nothing(new_scene, tmp_path):
    mesh = _mesh()
    _mush(mesh)
    path, _ = _publish(tmp_path, mesh)
    cmds.delete("body_dm")
    cmds.createNode("transform", name="body_dm")
    with pytest.raises(RuntimeError) as info:
        deltamush.PRODUCT.run(path)
    assert "body_dm" in str(info.value)
    assert not cmds.ls(type="deltaMush")


def test_empty_file_is_skipped(new_scene, tmp_path):
    path = deltamush.PRODUCT.create(str(tmp_path), "mush")
    _mesh()
    assert logic.run_steps([path]) == [path]
    assert not cmds.ls(type="deltaMush")


def test_one_undo_reverts_a_run(new_scene, tmp_path):
    mesh = _skinned()
    _mush(mesh)
    path, _ = _publish(tmp_path, mesh)
    cmds.setAttr("body_dm.smoothingIterations", 2)
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    deltamush.PRODUCT.run(path)
    assert cmds.getAttr("body_dm.smoothingIterations") == 7
    cmds.undo()
    assert cmds.ls(type="deltaMush") == ["body_dm"]
    assert cmds.getAttr("body_dm.smoothingIterations") == 2
    assert _deformers(mesh) == ["body_dm", "body_skin"]


def test_one_undo_reverts_a_fresh_run(new_scene, tmp_path):
    mesh = _skinned()
    _mush(mesh)
    path, _ = _publish(tmp_path, mesh)
    cmds.delete("body_dm")
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    deltamush.PRODUCT.run(path)
    assert cmds.ls(type="deltaMush") == ["body_dm"]
    cmds.undo()
    assert not cmds.ls(type="deltaMush")
    assert _deformers(mesh) == ["body_skin"]


# -- publish checks and versions --------------------------------------------


def test_publish_problems(new_scene, tmp_path):
    path = deltamush.PRODUCT.create(str(tmp_path), "mush")
    cmds.select(clear=True)
    (problem,) = versions.publish_problems(path)
    assert "Nothing selected" in problem

    cmds.select(cmds.createNode("transform"))
    (problem,) = versions.publish_problems(path)
    assert "mesh" in problem.lower()

    body = _mesh("body")
    head = _mesh("head")
    cmds.select(body, head)
    (problem,) = versions.publish_problems(path)
    assert "deltaMush" in problem and "body" in problem and "head" in problem

    _mush(body)
    cmds.select(body, head)
    (problem,) = versions.publish_problems(path)
    assert "head" in problem and "body" not in problem

    cmds.select(body)
    assert versions.publish_problems(path) == []


def test_publish_without_deltamush_raises_and_writes_nothing(new_scene, tmp_path):
    path = deltamush.PRODUCT.create(str(tmp_path), "mush")
    cmds.select(_mesh())
    with pytest.raises(RuntimeError):
        versions.publish_action(path).fn()
    assert os.path.getsize(path) == 0


def test_republishing_adds_a_version_only_on_change(new_scene, tmp_path):
    mesh = _mesh()
    _mush(mesh)
    path, message = _publish(tmp_path, mesh)
    assert message.endswith("v001")

    cmds.select(mesh)
    assert versions.publish_action(path).fn().endswith("v001")
    assert [v.number for v in versions.list_versions(path)] == [1]

    cmds.setAttr("body_dm.weightList[0].weights[4]", 0.3)
    assert versions.publish_action(path).fn().endswith("v002")


def test_panel_describes_the_nodes(new_scene, tmp_path):
    body = _mesh("body")
    head = _mesh("head")
    _mush(body, "body_dm")
    _mush(head, "head_dm")
    path, _ = _publish(tmp_path, body, head)
    assert deltamush.PRODUCT.panel(path).info == ["2 deltaMush nodes", "Meshes: body, head"]
