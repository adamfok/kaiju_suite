import os

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import data, logic, products, versions
from kaiju_suite.tools.assembler.products import material


def _cube(name):
    return cmds.polyCube(name=name, constructionHistory=False)[0]


def _meshes():
    """body_geo, head_geo and eye_geo: plain cubes (6 faces), as Mesh would rebuild them."""
    return _cube("body_geo"), _cube("head_geo"), _cube("eye_geo")


def _shading_group(name, material_node):
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=name)
    cmds.connectAttr(f"{material_node}.outColor", f"{sg}.surfaceShader")
    return sg


def _look(texture):
    """skin_SG: a blinn with a file texture, on all of body_geo and faces 0-1
    of head_geo. cloth_SG: a lambert on head_geo's other faces. eye_geo stays
    on initialShadingGroup."""
    body, head, eye = _meshes()
    skin = cmds.shadingNode("blinn", asShader=True, name="skin_mat")
    cmds.setAttr(f"{skin}.eccentricity", 0.7)
    tex = cmds.shadingNode("file", asTexture=True, name="skin_file")
    cmds.setAttr(f"{tex}.fileTextureName", texture, type="string")
    place = cmds.shadingNode("place2dTexture", asUtility=True, name="skin_p2d")
    cmds.setAttr(f"{place}.repeatU", 3)
    cmds.connectAttr(f"{place}.outUV", f"{tex}.uvCoord")
    cmds.connectAttr(f"{tex}.outColor", f"{skin}.color")
    skin_sg = _shading_group("skin_SG", skin)

    cloth = cmds.shadingNode("lambert", asShader=True, name="cloth_mat")
    cmds.setAttr(f"{cloth}.color", 0.2, 0.3, 0.4, type="double3")
    cloth_sg = _shading_group("cloth_SG", cloth)

    cmds.sets(body, forceElement=skin_sg)
    cmds.sets(f"{head}.f[0:1]", forceElement=skin_sg)
    cmds.sets(f"{head}.f[2:5]", forceElement=cloth_sg)
    return body, head, eye


def _texture(tmp_path, name="skin.png"):
    path = tmp_path / name
    path.write_bytes(b"not really a png")
    return str(path).replace("\\", "/")


def _faces(sg):
    """The faces in ``sg``, one per entry, whole meshes expanded."""
    members = cmds.sets(sg, query=True) or []
    if not members:
        return []
    faces = cmds.polyListComponentConversion(members, toFace=True) or []
    return sorted(cmds.ls(faces, flatten=True))


def _assignments():
    return {sg: _faces(sg) for sg in ("skin_SG", "cloth_SG", "initialShadingGroup") if cmds.objExists(sg)}


def _publish(tmp_path, *selection, name="look"):
    path = material.PRODUCT.create(str(tmp_path), name)
    cmds.select(selection, replace=True)
    message = versions.publish_action(path).fn()
    return path, message


def _new_scene_with_meshes():
    cmds.file(new=True, force=True)
    return _meshes()


# -- product ----------------------------------------------------------------


def test_material_is_discovered_and_owns_mat(tmp_path):
    assert material.PRODUCT in products.discover()
    assert material.PRODUCT.name == "Material"
    assert material.PRODUCT.kind == "material"
    assert material.PRODUCT.extensions == (".mat",)
    assert material.PRODUCT.order == 90
    assert material.PRODUCT.runnable and material.PRODUCT.versioned
    path = material.PRODUCT.creators[0].fn(str(tmp_path), "look", None)
    assert path == str(tmp_path / "look.mat") and os.path.getsize(path) == 0
    assert products.product_for(path) is material.PRODUCT


# -- publish ----------------------------------------------------------------


def test_publish_records_assignments_by_mesh_and_face_range(new_scene, tmp_path):
    body, head, eye = _look(_texture(tmp_path))
    path, message = _publish(tmp_path, body, head, eye)
    assert message == "Published Material look.mat v001"
    payload = data.read(path, "material")
    assert payload["assignments"] == {
        "cloth_SG": ["head_geo.f[2:5]"],
        "initialShadingGroup": ["eye_geo"],
        "skin_SG": ["body_geo", "head_geo.f[0:1]"],
    }
    assert payload["shading_engines"] == ["cloth_SG", "skin_SG"]


def test_export_holds_the_network_but_not_the_meshes(new_scene, tmp_path):
    """The spike: exporting shadingEngines must not pull in their members
    through dagSetMembers, nor the default initialShadingGroup network."""
    body, head, eye = _look(_texture(tmp_path))
    path, _ = _publish(tmp_path, body, head, eye)
    network = data.read(path, "material")["network"]
    for node in ("skin_SG", "skin_mat", "skin_file", "skin_p2d", "cloth_SG", "cloth_mat"):
        assert f'-n "{node}"' in network
    for absent in ("createNode mesh", "createNode transform", "body_geo", "head_geo", "eye_geo", "groupId", "lambert1"):
        assert absent not in network
    # Nothing that would touch scene-wide settings or clash on UUID.
    assert "select -ne" not in network and "rename -uid" not in network and "fileInfo" not in network


def test_publish_leaves_the_scene_and_selection_unchanged(new_scene, tmp_path):
    body, head, eye = _look(_texture(tmp_path))
    before_nodes = sorted(cmds.ls())
    before = _assignments()
    path, _ = _publish(tmp_path, body, f"{head}.f[0]")
    assert sorted(cmds.ls()) == before_nodes
    assert _assignments() == before
    assert cmds.ls(selection=True) == ["body_geo", "head_geo.f[0]"]


def test_publish_selected_faces_records_only_those_faces(new_scene, tmp_path):
    body, head, eye = _look(_texture(tmp_path))
    path, _ = _publish(tmp_path, f"{head}.f[1:3]")
    payload = data.read(path, "material")
    assert payload["assignments"] == {"cloth_SG": ["head_geo.f[2:3]"], "skin_SG": ["head_geo.f[1]"]}


def test_publish_problems(new_scene, tmp_path):
    texture = _texture(tmp_path)
    path = material.PRODUCT.create(str(tmp_path), "look")
    cmds.select(clear=True)
    (problem,) = versions.publish_problems(path)
    assert "Nothing selected" in problem

    cmds.select(cmds.createNode("transform"))
    (problem,) = versions.publish_problems(path)
    assert "mesh" in problem.lower()

    body, head, eye = _look(texture)
    cmds.select(body)
    assert versions.publish_problems(path) == []

    os.remove(texture)
    (problem,) = versions.publish_problems(path)
    assert "not found" in problem and texture in problem


def test_publish_without_meshes_raises_and_writes_nothing(new_scene, tmp_path):
    path = material.PRODUCT.create(str(tmp_path), "look")
    cmds.select(cmds.createNode("transform"))
    with pytest.raises(RuntimeError):
        versions.publish_action(path).fn()
    assert os.path.getsize(path) == 0


def test_republishing_adds_a_version_only_on_change(new_scene, tmp_path):
    body, head, eye = _look(_texture(tmp_path))
    path, message = _publish(tmp_path, body, head)
    assert message.endswith("v001")

    cmds.select(body, head)
    assert versions.publish_action(path).fn().endswith("v001")
    assert [v.number for v in versions.list_versions(path)] == [1]

    cmds.setAttr("cloth_mat.color", 1, 0, 0, type="double3")
    cmds.select(body, head)
    assert versions.publish_action(path).fn().endswith("v002")


# -- run --------------------------------------------------------------------


def test_round_trip_restores_networks_and_assignments(new_scene, tmp_path):
    texture = _texture(tmp_path)
    body, head, eye = _look(texture)
    before = _assignments()
    path, _ = _publish(tmp_path, body, head, eye)

    _new_scene_with_meshes()
    logic.run_steps([path])

    assert cmds.nodeType("skin_mat") == "blinn"
    assert cmds.getAttr("skin_mat.eccentricity") == pytest.approx(0.7)
    assert cmds.getAttr("skin_file.fileTextureName") == texture
    assert cmds.getAttr("skin_p2d.repeatU") == pytest.approx(3)
    assert cmds.listConnections("skin_p2d.outUV", plugs=True) == ["skin_file.uvCoord"]
    assert cmds.listConnections("skin_file.outColor", plugs=True) == ["skin_mat.color"]
    assert cmds.listConnections("skin_SG.surfaceShader") == ["skin_mat"]
    assert cmds.nodeType("cloth_mat") == "lambert"
    assert cmds.getAttr("cloth_mat.color")[0] == pytest.approx((0.2, 0.3, 0.4))
    assert cmds.listConnections("cloth_SG.surfaceShader") == ["cloth_mat"]
    assert _assignments() == before
    # The shading groups are proper render sets.
    assert {"skin_SG", "cloth_SG"} <= set(cmds.listConnections("renderPartition.sets") or [])
    assert not cmds.namespace(exists="kaiju_material")


def test_running_twice_reuses_existing_shading_groups(new_scene, tmp_path):
    body, head, eye = _look(_texture(tmp_path))
    before = _assignments()
    path, _ = _publish(tmp_path, body, head, eye)

    _new_scene_with_meshes()
    material.PRODUCT.run(path)
    nodes = sorted(cmds.ls())
    material.PRODUCT.run(path)
    assert sorted(cmds.ls()) == nodes
    assert _assignments() == before


def test_running_in_the_source_scene_changes_nothing(new_scene, tmp_path):
    body, head, eye = _look(_texture(tmp_path))
    before_nodes = sorted(cmds.ls())
    before = _assignments()
    path, _ = _publish(tmp_path, body, head, eye)
    material.PRODUCT.run(path)
    assert sorted(cmds.ls()) == before_nodes
    assert _assignments() == before


def test_existing_material_is_reused_by_a_new_shading_group(new_scene, tmp_path):
    body, head, eye = _look(_texture(tmp_path))
    path, _ = _publish(tmp_path, body, head, eye)

    _new_scene_with_meshes()
    existing = cmds.shadingNode("lambert", asShader=True, name="cloth_mat")
    cmds.setAttr(f"{existing}.color", 1, 1, 1, type="double3")
    material.PRODUCT.run(path)
    assert not cmds.objExists("cloth_mat1")
    assert cmds.listConnections("cloth_SG.surfaceShader") == ["cloth_mat"]
    # Reused as it is: the file's values don't overwrite it.
    assert cmds.getAttr("cloth_mat.color")[0] == pytest.approx((1, 1, 1))


def test_same_name_of_another_type_is_not_reused(new_scene, tmp_path):
    body, head, eye = _look(_texture(tmp_path))
    path, _ = _publish(tmp_path, body)

    _new_scene_with_meshes()
    cmds.createNode("transform", name="skin_mat")
    material.PRODUCT.run(path)
    assert cmds.nodeType("skin_mat") == "transform"
    (shader,) = cmds.listConnections("skin_SG.surfaceShader")
    assert cmds.nodeType(shader) == "blinn"


def test_missing_mesh_raises_and_changes_nothing(new_scene, tmp_path):
    body, head, eye = _look(_texture(tmp_path))
    path, _ = _publish(tmp_path, body, head, eye)

    cmds.file(new=True, force=True)
    _cube("body_geo")
    nodes = sorted(cmds.ls())
    with pytest.raises(data.MissingNodesError) as info:
        material.PRODUCT.run(path)
    assert str(info.value) == "Missing meshes: eye_geo, head_geo"
    assert sorted(cmds.ls()) == nodes


def test_empty_file_is_skipped(new_scene, tmp_path):
    _meshes()
    path = material.PRODUCT.create(str(tmp_path), "look")
    assert logic.run_steps([path]) == [path]
    assert cmds.ls(type="shadingEngine") == ["initialParticleSE", "initialShadingGroup"]


def test_one_undo_reverts_a_run(new_scene, tmp_path):
    body, head, eye = _look(_texture(tmp_path))
    path, _ = _publish(tmp_path, body, head, eye)

    _new_scene_with_meshes()
    nodes = sorted(cmds.ls())
    before = _assignments()
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    material.PRODUCT.run(path)
    assert cmds.objExists("skin_SG")
    cmds.undo()
    assert sorted(cmds.ls()) == nodes
    assert _assignments() == before


def test_panel_describes_the_file(new_scene, tmp_path):
    body, head, eye = _look(_texture(tmp_path))
    path, _ = _publish(tmp_path, body, head, eye)
    assert material.PRODUCT.panel(path).info == [
        "2 shading groups: cloth_SG, skin_SG",
        "3 meshes: body_geo, eye_geo, head_geo",
        "1 texture",
    ]
