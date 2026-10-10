import os

import pytest
from maya import cmds

from kaiju_suite.core import deformers as weightmaps
from kaiju_suite.tools.assembler import data, logic, products, runlog, versions
from kaiju_suite.tools.assembler.products import deformers


def _mesh(name="body"):
    """A subdivided cube (26 vertices, 2 x 4 x 2) with no history."""
    return cmds.polyCube(name=name, width=2, height=4, depth=2, sx=2, sy=2, sz=2, ch=False)[0]


def _curve(name="wire_crv"):
    return cmds.curve(name=name, point=[(-2, 0, 1.5), (0, 1, 1.5), (2, 0, 1.5)], degree=2)


def _group(name="ctrl_grp"):
    """A moved group to parent handles under."""
    group = cmds.createNode("transform", name=name)
    cmds.setAttr(f"{group}.translate", 1, 2, 0)
    cmds.setAttr(f"{group}.rotateY", 30)
    return group


def _cluster(mesh="body", name="body_cls"):
    """A relative cluster on the top vertices, its handle parented and moved."""
    node, handle = cmds.cluster(f"{mesh}.vtx[0:5]", name=name)
    cmds.setAttr(f"{node}.relative", True)
    cmds.setAttr(f"{node}.envelope", 0.9)
    cmds.setAttr(f"{node}.weightList[0].weights[1]", 0.4)
    if cmds.objExists("ctrl_grp"):
        handle = cmds.parent(handle, "ctrl_grp")[0]
    cmds.setAttr(f"{handle}.translate", 0.5, 0.25, 0)
    cmds.setAttr(f"{handle}.rotateX", 20)
    return node


def _softmod(mesh="body", name="body_sm"):
    node, handle = cmds.softMod(f"{mesh}.vtx[3]", name=name)
    cmds.setAttr(f"{node}.falloffRadius", 2.5)
    cmds.setAttr(f"{node}.falloffCenter", 0, -1, 1)
    cmds.setAttr(f"{handle}.translateZ", 0.75)
    return node


def _bend(mesh="body", name="body_bend"):
    node, handle = cmds.nonLinear(mesh, type="bend", name=name)
    cmds.setAttr(f"{node}.curvature", 45)
    cmds.setAttr(f"{node}.lowBound", -0.5)
    cmds.setAttr(f"{handle}.rotateZ", 10)
    cmds.setAttr(f"{node}.weightList[0].weights[7]", 0.0)
    return node


def _twist(mesh="body", name="body_twist"):
    node, _handle = cmds.nonLinear(mesh, type="twist", name=name)
    cmds.setAttr(f"{node}.endAngle", 60)
    return node


def _lattice(mesh="body", name="body_ffd"):
    node, lattice, base = cmds.lattice(mesh, divisions=(2, 3, 2), objectCentered=True, name=name)
    cmds.setAttr(f"{node}.outsideLattice", 1)
    cmds.setAttr(f"{lattice}.scaleX", 3)
    cmds.xform(f"{lattice}.pt[1][2][1]", objectSpace=True, translation=(0.8, 0.7, 0.9))
    return node


def _wire(mesh="body", name="body_wire", curve="wire_crv"):
    node = cmds.wire(mesh, wire=curve, name=name)[0]
    cmds.setAttr(f"{node}.dropoffDistance[0]", 3)
    cmds.setAttr(f"{node}.rotation", 0.5)
    cmds.xform(f"{curve}.cv[1]", worldSpace=True, translation=(0, 2, 1.5))  # bend it after binding
    return node


def _points(mesh="body"):
    flat = cmds.xform(f"{mesh}.vtx[*]", query=True, worldSpace=True, translation=True)
    return [round(v, 4) for v in flat]


def _weights(node, mesh="body"):
    return [round(w, 5) for w in cmds.percent(node, f"{mesh}.vtx[*]", query=True, value=True)]


def _members(node, mesh):
    shape = cmds.listRelatives(mesh, shapes=True, fullPath=True)[0]
    return weightmaps.members(node, weightmaps.geometry_index(node, shape), 26)


def _deformers(mesh="body"):
    """The mesh's deformers, last evaluated first."""
    return cmds.ls(cmds.listHistory(mesh), type="geometryFilter")


def _publish(tmp_path, *selection, name="dfm"):
    path = deformers.PRODUCT.create(str(tmp_path), name)
    cmds.select(selection)
    message = versions.publish_action(path).fn()
    return path, message


def _records(path):
    return {r["name"]: r for r in data.read(path, "deformers")["deformers"]}


# -- product ----------------------------------------------------------------


def test_deformers_is_discovered_and_owns_dfm(tmp_path):
    assert deformers.PRODUCT in products.discover()
    assert deformers.PRODUCT.name == "Deformers"
    assert deformers.PRODUCT.kind == "deformers"
    assert deformers.PRODUCT.extensions == (".dfm",)
    assert deformers.PRODUCT.runnable and deformers.PRODUCT.versioned
    path = deformers.PRODUCT.creators[0].fn(str(tmp_path), "dfm", None)
    assert path == str(tmp_path / "dfm.dfm") and os.path.getsize(path) == 0
    assert products.product_for(path) is deformers.PRODUCT


# -- publish ----------------------------------------------------------------


def test_publish_saves_type_members_settings_and_sparse_weights(new_scene, tmp_path):
    _mesh()
    _cluster()
    path, message = _publish(tmp_path, "body")
    assert message == "Published Deformers dfm.dfm v001"

    record = _records(path)["body_cls"]
    assert record["type"] == "cluster"
    assert record["settings"]["relative"] is True
    assert record["settings"]["envelope"] == pytest.approx(0.9)
    (geometry,) = record["geometry"]
    assert geometry["mesh"] == "body" and geometry["vertex_count"] == 26
    assert geometry["members"] == [[0, 5]]
    assert [tuple(w) for w in geometry["weights"]] == [(1, pytest.approx(0.4))]
    assert record["handle"]["name"] == "body_clsHandle"


def test_publish_saves_every_kind_of_deformer_in_evaluation_order(new_scene, tmp_path):
    _mesh()
    _curve()
    _cluster()
    _softmod()
    _bend()
    _lattice()
    _wire()
    path, _ = _publish(tmp_path, "body")
    records = data.read(path, "deformers")["deformers"]
    assert [(r["name"], r["type"]) for r in records] == [
        ("body_cls", "cluster"),
        ("body_sm", "softMod"),
        ("body_bend", "nonLinear"),
        ("body_ffd", "ffd"),
        ("body_wire", "wire"),
    ]
    by_name = {r["name"]: r for r in records}
    assert by_name["body_bend"]["nonlinear"] == "bend"
    assert by_name["body_bend"]["geometry"][0]["members"] is None
    assert by_name["body_ffd"]["divisions"] == [2, 3, 2]
    assert [w["curve"] for w in by_name["body_wire"]["wires"]] == ["wire_crv"]


def test_publish_leaves_out_skin_and_deltamush(new_scene, tmp_path):
    mesh = _mesh()
    cmds.select(clear=True)
    cmds.joint(name="jnt")
    cmds.skinCluster("jnt", mesh, toSelectedBones=True)
    cmds.deltaMush(mesh)
    _twist()
    path, _ = _publish(tmp_path, mesh)
    assert list(_records(path)) == ["body_twist"]


# -- run: round trips ---------------------------------------------------------


def _round_trip(tmp_path, build, *, group=False, curve=False):
    """Build a deformed body, publish it, rebuild the bare scene, Run.
    Returns the points before and after."""
    _mesh()
    if group:
        _group()
    if curve:
        _curve()
    names = build()
    before = _points()
    path, _ = _publish(tmp_path, "body")

    cmds.file(new=True, force=True)
    _mesh()
    if group:
        _group()
    if curve:
        _curve()
        cmds.xform("wire_crv.cv[1]", worldSpace=True, translation=(0, 2, 1.5))
    logic.run_steps([path])
    assert _deformers() == list(reversed(names))
    return before, _points()


def test_round_trip_cluster_with_a_parented_handle(new_scene, tmp_path):
    before, after = _round_trip(tmp_path, lambda: [_cluster()], group=True)
    assert after == pytest.approx(before, abs=1e-3)
    assert cmds.listRelatives("body_clsHandle", parent=True) == ["ctrl_grp"]
    assert cmds.getAttr("body_cls.relative") is True
    assert _weights("body_cls")[1] == 0.4


def test_round_trip_softmod(new_scene, tmp_path):
    before, after = _round_trip(tmp_path, lambda: [_softmod()])
    assert after == pytest.approx(before, abs=1e-3)
    assert cmds.getAttr("body_sm.falloffRadius") == pytest.approx(2.5)


def test_round_trip_nonlinear(new_scene, tmp_path):
    before, after = _round_trip(tmp_path, lambda: [_bend(), _twist()])
    assert after == pytest.approx(before, abs=1e-3)
    assert cmds.nodeType(cmds.listRelatives("body_bendHandle", shapes=True)[0]) == "deformBend"
    assert cmds.nodeType(cmds.listRelatives("body_twistHandle", shapes=True)[0]) == "deformTwist"
    assert cmds.getAttr("body_bend.curvature") == pytest.approx(45)
    assert _weights("body_bend")[7] == 0.0


def test_round_trip_lattice(new_scene, tmp_path):
    before, after = _round_trip(tmp_path, lambda: [_lattice()])
    assert after == pytest.approx(before, abs=1e-3)
    assert cmds.objExists("body_ffdLattice") and cmds.objExists("body_ffdBase")
    assert cmds.getAttr("body_ffd.outsideLattice") == 1


def test_round_trip_wire(new_scene, tmp_path):
    before, after = _round_trip(tmp_path, lambda: [_wire()], curve=True)
    assert after == pytest.approx(before, abs=1e-3)
    assert cmds.getAttr("body_wire.dropoffDistance[0]") == pytest.approx(3)
    cmds.setAttr("body_wire.envelope", 0)
    assert _points() != pytest.approx(after, abs=1e-3)  # the wire does deform the mesh


def test_round_trip_every_kind_in_order(new_scene, tmp_path):
    def build():
        return [_cluster(), _softmod(), _bend(), _lattice(), _wire()]

    before, after = _round_trip(tmp_path, build, group=True, curve=True)
    assert after == pytest.approx(before, abs=1e-3)


def test_shared_deformer_restores_members_and_weights_per_mesh(new_scene, tmp_path):
    body = _mesh("body")
    head = _mesh("head")
    node = cmds.cluster(f"{head}.vtx[0:3]", f"{body}.vtx[10:12]", name="shared_cls")[0]
    cmds.percent(node, f"{body}.vtx[11]", value=0.2)
    cmds.percent(node, f"{head}.vtx[2]", value=0.6)
    path, _ = _publish(tmp_path, body, head)

    cmds.file(new=True, force=True)
    _mesh("body")
    _mesh("head")
    deformers.PRODUCT.run(path)
    assert cmds.ls(type="cluster") == ["shared_cls"]
    assert _members("shared_cls", "body") == [[10, 12]]
    assert _members("shared_cls", "head") == [[0, 3]]
    body_weights = _weights("shared_cls", "body")
    assert body_weights[11] == 0.2 and body_weights[10] == 1.0
    head_weights = _weights("shared_cls", "head")
    assert head_weights[2] == 0.6 and head_weights[0] == 1.0


def test_rerunning_replaces_the_same_named_deformers(new_scene, tmp_path):
    _mesh()
    _cluster()
    _bend()
    path, _ = _publish(tmp_path, "body")
    before = _points()
    cmds.setAttr("body_bend.curvature", 5)
    cmds.setAttr("body_cls.weightList[0].weights[1]", 1.0)

    deformers.PRODUCT.run(path)
    message = deformers.PRODUCT.run(path)
    assert "body_cls" in message and "body_bend" in message
    assert cmds.ls(type="cluster") == ["body_cls"] and cmds.ls(type="nonLinear") == ["body_bend"]
    assert cmds.ls("body_clsHandle*", type="transform") == ["body_clsHandle"]
    assert _deformers() == ["body_bend", "body_cls"]
    assert _points() == pytest.approx(before, abs=1e-3)


def test_other_deformers_are_left_alone(new_scene, tmp_path):
    _mesh()
    _cluster()
    path, _ = _publish(tmp_path, "body")
    cmds.delete("body_cls")
    _twist(name="keep_twist")
    deformers.PRODUCT.run(path)
    assert _deformers() == ["body_cls", "keep_twist"]


# -- run: what's missing is skipped -----------------------------------------


def test_missing_mesh_is_skipped_with_a_warning(new_scene, tmp_path):
    _mesh("body")
    _mesh("head")
    _cluster("body", "body_cls")
    _cluster("head", "head_cls")
    path, _ = _publish(tmp_path, "body", "head")

    cmds.file(new=True, force=True)
    _mesh("body")
    with runlog.capture() as run:
        deformers.PRODUCT.run(path)
    assert run.warnings == ["Skipped missing meshes: head"]
    assert cmds.ls(type="cluster") == ["body_cls"]


def test_missing_wire_curve_is_skipped_with_a_warning(new_scene, tmp_path):
    _mesh()
    _curve()
    _bend()
    _wire()
    path, _ = _publish(tmp_path, "body")

    cmds.file(new=True, force=True)
    _mesh()
    with runlog.capture() as run:
        message = deformers.PRODUCT.run(path)
    assert run.warnings == ["Skipped wire body_wire: missing curves wire_crv"]
    assert not cmds.ls(type="wire")
    assert cmds.ls(type="nonLinear") == ["body_bend"]
    assert "body_wire" not in message


def test_missing_handle_parent_leaves_the_handle_in_the_world(new_scene, tmp_path):
    _mesh()
    _group()
    _cluster()
    path, _ = _publish(tmp_path, "body")

    cmds.file(new=True, force=True)
    _mesh()
    with runlog.capture() as run:
        deformers.PRODUCT.run(path)
    assert run.warnings == ["Skipped missing parents: ctrl_grp (body_clsHandle left in the world)"]
    assert cmds.listRelatives("body_clsHandle", parent=True) is None


# -- run: problems raise before anything changes -----------------------------


def test_vertex_count_mismatch_raises_and_changes_nothing(new_scene, tmp_path):
    _mesh()
    _bend()
    path, _ = _publish(tmp_path, "body")

    cmds.file(new=True, force=True)
    cmds.polyCube(name="body", ch=False)  # 8 vertices, not 26
    _bend()
    cmds.setAttr("body_bend.curvature", 5)
    with pytest.raises(RuntimeError) as info:
        deformers.PRODUCT.run(path)
    assert "body" in str(info.value) and "26" in str(info.value) and "8" in str(info.value)
    assert cmds.ls(type="nonLinear") == ["body_bend"]
    assert cmds.getAttr("body_bend.curvature") == 5


def test_ambiguous_mesh_name_raises_and_changes_nothing(new_scene, tmp_path):
    _mesh()
    _bend()
    path, _ = _publish(tmp_path, "body")

    cmds.file(new=True, force=True)
    for group in ("a", "b"):
        cmds.parent(_mesh(), cmds.createNode("transform", name=group))
    with pytest.raises(RuntimeError) as info:
        deformers.PRODUCT.run(path)
    assert "|a|body" in str(info.value) and "|b|body" in str(info.value)
    assert not cmds.ls(type="nonLinear")


def test_ambiguous_wire_curve_raises_and_changes_nothing(new_scene, tmp_path):
    _mesh()
    _curve()
    _wire()
    path, _ = _publish(tmp_path, "body")

    cmds.file(new=True, force=True)
    _mesh()
    for group in ("a", "b"):
        cmds.parent(_curve(), cmds.createNode("transform", name=group))
    with pytest.raises(RuntimeError) as info:
        deformers.PRODUCT.run(path)
    assert "wire_crv" in str(info.value)
    assert not cmds.ls(type="wire")


def test_name_taken_by_another_node_raises_and_changes_nothing(new_scene, tmp_path):
    _mesh()
    _cluster()
    _bend()
    path, _ = _publish(tmp_path, "body")
    cmds.delete("body_cls", "body_bend")
    cmds.createNode("transform", name="body_bend")
    with pytest.raises(RuntimeError) as info:
        deformers.PRODUCT.run(path)
    assert "body_bend" in str(info.value)
    assert not cmds.ls(type="cluster") and not cmds.ls(type="nonLinear")


def test_handle_name_taken_by_another_node_raises(new_scene, tmp_path):
    _mesh()
    _cluster()
    path, _ = _publish(tmp_path, "body")
    cmds.delete("body_cls")
    cmds.createNode("transform", name="body_clsHandle")
    with pytest.raises(RuntimeError) as info:
        deformers.PRODUCT.run(path)
    assert "body_clsHandle" in str(info.value)
    assert not cmds.ls(type="cluster")


def test_empty_file_is_skipped(new_scene, tmp_path):
    path = deformers.PRODUCT.create(str(tmp_path), "dfm")
    _mesh()
    assert logic.run_steps([path]) == [path]
    assert not cmds.ls(type="geometryFilter")


# -- undo --------------------------------------------------------------------


def test_one_undo_reverts_a_run(new_scene, tmp_path):
    _mesh()
    _curve()
    _cluster()
    _lattice()
    _wire()
    path, _ = _publish(tmp_path, "body")
    cmds.setAttr("body_cls.envelope", 0.1)
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    deformers.PRODUCT.run(path)
    assert cmds.getAttr("body_cls.envelope") == pytest.approx(0.9)
    cmds.undo()
    assert cmds.getAttr("body_cls.envelope") == pytest.approx(0.1)
    assert _deformers() == ["body_wire", "body_ffd", "body_cls"]


def test_one_undo_reverts_a_fresh_run(new_scene, tmp_path):
    _mesh()
    _softmod()
    _twist()
    path, _ = _publish(tmp_path, "body")
    cmds.delete("body_sm", "body_twist")
    before = _points()
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    deformers.PRODUCT.run(path)
    assert _deformers() == ["body_twist", "body_sm"]
    cmds.undo()
    assert not _deformers()
    assert _points() == before


# -- publish checks, versions and panel ---------------------------------------


def test_publish_problems(new_scene, tmp_path):
    path = deformers.PRODUCT.create(str(tmp_path), "dfm")
    cmds.select(clear=True)
    (problem,) = versions.publish_problems(path)
    assert "Nothing selected" in problem

    cmds.select(cmds.createNode("transform"))
    (problem,) = versions.publish_problems(path)
    assert "mesh" in problem.lower()

    body = _mesh("body")
    head = _mesh("head")
    _bend(body)
    cmds.select(body, head)
    (problem,) = versions.publish_problems(path)
    assert "head" in problem and "body" not in problem

    cmds.select(body)
    assert versions.publish_problems(path) == []


def test_publish_without_deformers_raises_and_writes_nothing(new_scene, tmp_path):
    path = deformers.PRODUCT.create(str(tmp_path), "dfm")
    cmds.select(_mesh())
    with pytest.raises(RuntimeError):
        versions.publish_action(path).fn()
    assert os.path.getsize(path) == 0


def test_republishing_adds_a_version_only_on_change(new_scene, tmp_path):
    _mesh()
    _bend()
    path, message = _publish(tmp_path, "body")
    assert message.endswith("v001")
    cmds.select("body")
    assert versions.publish_action(path).fn().endswith("v001")
    cmds.setAttr("body_bend.curvature", 10)
    assert versions.publish_action(path).fn().endswith("v002")


def test_panel_describes_the_deformers(new_scene, tmp_path):
    _mesh("body")
    _mesh("head")
    _curve()
    _cluster("body")
    _wire("head", "head_wire")
    _twist("head", "head_twist")
    path, _ = _publish(tmp_path, "body", "head")
    assert deformers.PRODUCT.panel(path).info == [
        "3 deformers: body_cls (cluster), head_wire (wire), head_twist (twist)",
        "Meshes: body, head",
        "Wire curves: wire_crv",
    ]
