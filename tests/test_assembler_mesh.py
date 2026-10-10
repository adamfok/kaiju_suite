import os

import pytest
from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.tools.assembler import data, logic, products, versions
from kaiju_suite.tools.assembler.products import mesh


def _fn(node):
    sel = om.MSelectionList()
    sel.add(node)
    return om.MFnMesh(sel.getDagPath(0))


def _shape(transform):
    shapes = cmds.listRelatives(transform, shapes=True, fullPath=True, noIntermediate=True) or []
    return cmds.ls(shapes, type="mesh", long=True)[0]


def _geometry(transform):
    """Everything Run should restore, rounded so it compares across a file."""
    fn = _fn(_shape(transform))
    points = [tuple(round(c, 5) for c in (p.x, p.y, p.z)) for p in fn.getPoints(om.MSpace.kObject)]
    counts, connects = fn.getVertices()
    uv_sets = []
    current = fn.currentUVSetName()
    for name in [current] + [s for s in fn.getUVSetNames() if s != current]:
        u, v = fn.getUVs(name)
        uv_counts, uv_ids = fn.getAssignedUVs(name)
        uv_sets.append(
            (name, [round(x, 5) for x in u], [round(x, 5) for x in v], list(uv_counts), list(uv_ids))
        )
    hard = sorted(
        tuple(sorted(fn.getEdgeVertices(e))) for e in range(fn.numEdges) if not fn.isEdgeSmooth(e)
    )
    return {"points": points, "counts": list(counts), "connects": list(connects), "uv_sets": uv_sets, "hard": hard}


def _transform(transform):
    found = {}
    for attr in ("translate", "rotate", "scale"):
        found[attr] = [round(v, 5) for v in cmds.getAttr(f"{transform}.{attr}")[0]]
    found["rotateOrder"] = cmds.getAttr(f"{transform}.rotateOrder")
    return found


def _cube(name="body", parent=None):
    """A cube with a tweaked point, moved UVs, a second UV set, some hard
    edges and a transform off its defaults."""
    node = cmds.polyCube(name=name, constructionHistory=False)[0]
    if parent:
        node = cmds.parent(node, parent)[0]
    node = cmds.ls(node, long=True)[0]
    cmds.move(0.25, 0.5, 0, f"{node}.vtx[0]", relative=True, objectSpace=True)
    cmds.polyEditUV(f"{node}.map[0]", u=0.1, v=0.2)
    cmds.polyUVSet(node, copy=True, uvSet="map1", newUVSet="extra")
    cmds.polyEditUV(f"{node}.map[1]", u=-0.05, v=0.0, uvSetName="extra")
    cmds.polySoftEdge(f"{node}.e[*]", angle=180, constructionHistory=False)
    cmds.polySoftEdge(f"{node}.e[0:2]", angle=0, constructionHistory=False)
    cmds.setAttr(f"{node}.translate", 1, 2, 3)
    cmds.setAttr(f"{node}.rotate", 10, 20, 30)
    cmds.setAttr(f"{node}.scale", 1, 2, 0.5)
    cmds.setAttr(f"{node}.rotateOrder", 4)
    return node


def _publish(tmp_path, *selection, name="geo"):
    path = mesh.PRODUCT.create(str(tmp_path), name)
    cmds.select(selection)
    message = versions.publish_action(path).fn()
    return path, message


# -- product ----------------------------------------------------------------


def test_mesh_is_discovered_and_owns_mesh_files(tmp_path):
    assert mesh.PRODUCT in products.discover()
    assert mesh.PRODUCT.name == "Mesh"
    assert mesh.PRODUCT.extensions == (".mesh",)
    assert mesh.PRODUCT.order == 50
    assert mesh.PRODUCT.runnable and mesh.PRODUCT.versioned
    path = mesh.PRODUCT.creators[0].fn(str(tmp_path), "geo", None)
    assert path == str(tmp_path / "geo.mesh") and os.path.getsize(path) == 0
    assert products.product_for(path) is mesh.PRODUCT


# -- publish and run --------------------------------------------------------


def test_round_trip_restores_geometry_uvs_hard_edges_and_transform(new_scene, tmp_path):
    cube = _cube()
    geometry, transform = _geometry(cube), _transform(cube)
    assert geometry["hard"] and len(geometry["uv_sets"]) == 2  # the fixture is what we think
    path, message = _publish(tmp_path, cube)
    assert message == "Published Mesh geo.mesh v001"

    cmds.file(new=True, force=True)
    logic.run_steps([path])

    assert cmds.ls("|body", type="transform")
    assert cmds.listRelatives("|body", shapes=True) == ["bodyShape"]
    assert _geometry("|body") == geometry
    assert _transform("|body") == transform
    assert cmds.listConnections("|body|bodyShape", type="shadingEngine") == ["initialShadingGroup"]


def test_current_uv_set_is_saved_first_and_restored_as_current(new_scene, tmp_path):
    cube = _cube()
    cmds.polyUVSet(cube, currentUVSet=True, uvSet="extra")
    path, _ = _publish(tmp_path, cube)
    saved = data.read(path, "mesh")["meshes"][0]
    assert [s["name"] for s in saved["uv_sets"]] == ["extra", "map1"]

    cmds.file(new=True, force=True)
    mesh.PRODUCT.run(path)
    assert cmds.polyUVSet("|body", query=True, currentUVSet=True) == ["extra"]
    assert sorted(cmds.polyUVSet("|body", query=True, allUVSets=True)) == ["extra", "map1"]


def test_publish_saves_several_meshes_in_selection_order(new_scene, tmp_path):
    a = _cube("a")
    b = cmds.polyPlane(name="b", constructionHistory=False)[0]
    path, _ = _publish(tmp_path, b, a)
    assert [m["name"] for m in data.read(path, "mesh")["meshes"]] == ["b", "a"]
    assert mesh.PRODUCT.panel(path).info == ["2 meshes", "b, a"]


def test_selecting_the_shape_publishes_its_transform(new_scene, tmp_path):
    cube = _cube()
    path, _ = _publish(tmp_path, _shape(cube))
    assert [m["name"] for m in data.read(path, "mesh")["meshes"]] == ["body"]


def test_publish_reads_through_construction_history(new_scene, tmp_path):
    node = cmds.polySphere(name="ball", subdivisionsAxis=8, subdivisionsHeight=6)[0]
    expected = _geometry(node)
    path, _ = _publish(tmp_path, node)
    cmds.file(new=True, force=True)
    mesh.PRODUCT.run(path)
    assert _geometry("|ball") == expected
    assert not cmds.listHistory("|ball|ballShape", pruneDagObjects=True)


def test_running_twice_makes_numbered_copies(new_scene, tmp_path):
    cube = _cube()
    geometry, transform = _geometry(cube), _transform(cube)
    path, _ = _publish(tmp_path, cube)

    message = mesh.PRODUCT.run(path)
    assert "body1" in message

    # The original is untouched...
    assert _geometry("|body") == geometry and _transform("|body") == transform
    assert cmds.listRelatives("|body", shapes=True) == ["bodyShape"]
    # ...and the copy is complete, with its own shape name.
    assert cmds.listRelatives("|body1", shapes=True) == ["body1Shape"]
    assert _geometry("|body1") == geometry and _transform("|body1") == transform

    mesh.PRODUCT.run(path)
    assert cmds.objExists("|body2|body2Shape")


def test_parent_is_found_by_name(new_scene, tmp_path):
    rig = cmds.createNode("transform", name="geo_grp")
    cube = _cube(parent=rig)
    path, _ = _publish(tmp_path, cube)
    assert data.read(path, "mesh")["meshes"][0]["parent"] == "geo_grp"

    cmds.file(new=True, force=True)
    cmds.createNode("transform", name="geo_grp")
    mesh.PRODUCT.run(path)
    assert cmds.objExists("|geo_grp|body|bodyShape")


def test_parent_missing_from_the_scene_means_world(new_scene, tmp_path):
    cube = _cube(parent=cmds.createNode("transform", name="geo_grp"))
    path, _ = _publish(tmp_path, cube)
    cmds.file(new=True, force=True)
    mesh.PRODUCT.run(path)
    assert cmds.objExists("|body|bodyShape")


def test_ambiguous_parent_creates_nothing(new_scene, tmp_path):
    cube = _cube(parent=cmds.createNode("transform", name="geo_grp"))
    path, _ = _publish(tmp_path, cube)

    cmds.file(new=True, force=True)
    for group in ("a", "b"):
        cmds.createNode("transform", name="geo_grp", parent=cmds.createNode("transform", name=group))
    with pytest.raises(RuntimeError) as info:
        mesh.PRODUCT.run(path)
    assert "geo_grp" in str(info.value)
    assert not cmds.ls(type="mesh")


def test_empty_file_is_skipped(new_scene, tmp_path):
    path = mesh.PRODUCT.create(str(tmp_path), "geo")
    assert logic.run_steps([path]) == [path]
    assert not cmds.ls(type="mesh")


def test_one_undo_reverts_a_run(new_scene, tmp_path):
    a, b = _cube("a"), _cube("b")
    path, _ = _publish(tmp_path, a, b)
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    mesh.PRODUCT.run(path)
    assert len(cmds.ls(type="mesh")) == 2
    cmds.undo()
    assert not cmds.ls(type="mesh")
    assert not cmds.ls("a", "b")
    assert not cmds.sets("initialShadingGroup", query=True)


# -- publish checks and versions --------------------------------------------


def test_publish_problems(new_scene, tmp_path):
    path = mesh.PRODUCT.create(str(tmp_path), "geo")
    cmds.select(clear=True)
    (problem,) = versions.publish_problems(path)
    assert "Nothing selected" in problem

    cmds.select(cmds.createNode("transform", name="empty_grp"))
    (problem,) = versions.publish_problems(path)
    assert "mesh" in problem.lower() and "empty_grp" in problem

    cube = _cube()
    cmds.select(cube)
    assert versions.publish_problems(path) == []

    cmds.select(cube, "empty_grp")
    (problem,) = versions.publish_problems(path)
    assert "empty_grp" in problem and "body" not in problem


def test_publish_without_meshes_raises_and_writes_nothing(new_scene, tmp_path):
    path = mesh.PRODUCT.create(str(tmp_path), "geo")
    cmds.select(cmds.createNode("joint"))
    with pytest.raises(RuntimeError):
        versions.publish_action(path).fn()
    assert os.path.getsize(path) == 0


def test_republishing_adds_a_version_only_on_change(new_scene, tmp_path):
    cube = _cube()
    path, message = _publish(tmp_path, cube)
    assert message.endswith("v001")

    cmds.select(cube)
    assert versions.publish_action(path).fn().endswith("v001")
    assert [v.number for v in versions.list_versions(path)] == [1]

    cmds.move(0, 1, 0, f"{cube}.vtx[3]", relative=True)
    assert versions.publish_action(path).fn().endswith("v002")


def test_panel_describes_the_meshes(new_scene, tmp_path):
    cube = _cube()
    path, _ = _publish(tmp_path, cube)
    assert mesh.PRODUCT.panel(path).info == ["1 mesh", "body"]


# -- normals and vertex colors ----------------------------------------------


def _normals_and_colors(transform):
    """Locked face-vertex normals and every color set (current first),
    rounded so they compare across a file."""
    fn = _fn(_shape(transform))
    counts, connects = fn.getVertices()
    _, normal_ids = fn.getNormalIds()
    normals = fn.getNormals()
    locked, i = [], 0
    for face, count in enumerate(counts):
        for _ in range(count):
            if fn.isNormalLocked(normal_ids[i]):
                n = normals[normal_ids[i]]
                locked.append((face, connects[i], round(n.x, 4), round(n.y, 4), round(n.z, 4)))
            i += 1
    current = fn.currentColorSetName()
    names = [current] + [s for s in fn.getColorSetNames() if s != current] if current else []
    color_sets = []
    for name in names:
        colors = [tuple(round(c, 4) for c in (col.r, col.g, col.b, col.a)) for col in fn.getFaceVertexColors(name)]
        color_sets.append((name, fn.getColorRepresentation(name), colors))
    return {"locked": sorted(locked), "color_sets": color_sets}


def _cube_with_normals_and_colors(name="body"):
    """The test cube plus two locked vertex normals and two color sets:
    ``paint`` (RGBA, every vertex colored, current) and ``mask`` (RGB, one
    vertex colored)."""
    node = _cube(name)
    cmds.polyNormalPerVertex(f"{node}.vtx[0]", xyz=(0.0, 1.0, 0.0))
    cmds.polyNormalPerVertex(f"{node}.vtx[5]", xyz=(1.0, 0.0, 0.0))
    cmds.polyColorSet(node, create=True, colorSet="paint", representation="RGBA")
    cmds.polyColorSet(node, currentColorSet=True, colorSet="paint")
    cmds.polyColorPerVertex(f"{node}.vtx[*]", rgb=(0.2, 0.4, 0.6), alpha=0.5)
    cmds.polyColorPerVertex(f"{node}.vtx[2]", rgb=(1.0, 0.0, 0.0), alpha=1.0)
    cmds.polyColorSet(node, create=True, colorSet="mask", representation="RGB")
    cmds.polyColorSet(node, currentColorSet=True, colorSet="mask")
    cmds.polyColorPerVertex(f"{node}.vtx[1]", rgb=(0.0, 1.0, 0.0))
    cmds.polyColorSet(node, currentColorSet=True, colorSet="paint")
    cmds.delete(node, constructionHistory=True)
    return node


def test_round_trip_restores_locked_normals_and_color_sets(new_scene, tmp_path):
    cube = _cube_with_normals_and_colors()
    expected = _normals_and_colors(cube)
    assert expected["locked"] and [s[0] for s in expected["color_sets"]] == ["paint", "mask"]
    geometry = _geometry(cube)
    path, _ = _publish(tmp_path, cube)

    cmds.file(new=True, force=True)
    logic.run_steps([path])

    assert _normals_and_colors("|body") == expected
    assert _geometry("|body") == geometry
    assert cmds.polyColorSet("|body", query=True, currentColorSet=True) == ["paint"]


def test_mesh_without_locked_normals_or_colors_saves_none(new_scene, tmp_path):
    cube = _cube()
    path, _ = _publish(tmp_path, cube)
    saved = data.read(path, "mesh")["meshes"][0]
    assert saved["normals"] == [] and saved["color_sets"] == []

    cmds.file(new=True, force=True)
    mesh.PRODUCT.run(path)
    assert _normals_and_colors("|body") == {"locked": [], "color_sets": []}


def test_old_files_without_normals_or_colors_still_load(new_scene, tmp_path):
    cube = _cube_with_normals_and_colors()
    geometry = _geometry(cube)
    path, _ = _publish(tmp_path, cube)
    payload = data.read(path, "mesh")
    for record in payload["meshes"]:
        del record["normals"], record["color_sets"]
    data.write(path, "mesh", payload)

    cmds.file(new=True, force=True)
    mesh.PRODUCT.run(path)
    assert _geometry("|body") == geometry
    assert _normals_and_colors("|body") == {"locked": [], "color_sets": []}


def test_one_undo_reverts_a_run_with_normals_and_colors(new_scene, tmp_path):
    cube = _cube_with_normals_and_colors()
    path, _ = _publish(tmp_path, cube)
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    mesh.PRODUCT.run(path)
    assert cmds.ls(type="mesh")
    cmds.undo()
    assert not cmds.ls(type="mesh")
    assert not cmds.ls("body")
