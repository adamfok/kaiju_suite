"""Skin weights save/load (kaiju_suite.datatypes.skin), without the Assembler.

The Assembler's SkinCluster product (tests/test_assembler_skin.py) and the
SkinCluster Tool both go through this module.
"""

import pytest
from maya import cmds

from kaiju_suite import datatypes
from kaiju_suite.datatypes import skin

JOINTS = ("hip", "knee", "ankle")


def _skeleton():
    cmds.select(clear=True)
    made = [cmds.joint(name=name, position=(0, 4 - i * 4, 0)) for i, name in enumerate(JOINTS)]
    cmds.select(clear=True)
    return made


def _mesh(name="leg"):
    return cmds.polyCylinder(name=name, height=8, subdivisionsX=8, subdivisionsY=4, constructionHistory=False)[0]


def _weights(mesh):
    cluster = skin.skin_cluster(mesh)
    names = cmds.skinCluster(cluster, query=True, influence=True)
    found = []
    for i in range(cmds.polyEvaluate(mesh, vertex=True)):
        values = cmds.skinPercent(cluster, f"{mesh}.vtx[{i}]", query=True, value=True)
        found.append({n: round(w, 5) for n, w in zip(names, values) if abs(w) > 1e-9})
    return found


def _rig():
    joints = _skeleton()
    mesh = _mesh()
    cluster = cmds.skinCluster(*joints, mesh, toSelectedBones=True, name="leg_skin")[0]
    for i in range(cmds.polyEvaluate(mesh, vertex=True)):
        w = (i % 5) / 5.0
        cmds.skinPercent(cluster, f"{mesh}.vtx[{i}]", transformValue=[("hip", w), ("knee", 1 - w)])
    return mesh, cluster


def test_kind_and_extension():
    assert skin.KIND == "skin"
    assert skin.EXTENSION == ".skin"


def test_gather_then_apply_restores_the_weights(new_scene):
    mesh, _ = _rig()
    before = _weights(mesh)
    payload = skin.gather([mesh])
    assert [r["mesh"] for r in payload["meshes"]] == ["leg"]

    cmds.file(new=True, force=True)
    _skeleton()
    _mesh()
    lines = []
    message = skin.apply(payload, info=lines.append)
    assert message == "Bound 1 mesh: leg_skin"
    assert lines == ["leg: bound leg_skin to 3 influences"]
    assert _weights("leg") == before


def test_apply_skips_a_missing_mesh_with_a_maya_warning(new_scene, monkeypatch):
    mesh, _ = _rig()
    payload = skin.gather([mesh])
    cmds.delete(mesh)
    warnings = []
    monkeypatch.setattr(cmds, "warning", warnings.append)
    assert skin.apply(payload) == "Bound 0 meshes"
    assert warnings == ["Skipped missing meshes: leg"]


def test_gather_needs_skinned_meshes(new_scene):
    _skeleton()
    bare = _mesh("bare")
    with pytest.raises(RuntimeError, match="No skinCluster on: bare"):
        skin.gather([bare])
    assert skin.selection_problems([bare]) == ["No skinCluster on: bare. Bind them first, or leave them out."]
    assert skin.selection_problems([]) == ["Nothing selected. Select the skinned meshes to publish."]


def test_describe_nodes_and_compare_view(new_scene):
    mesh, _ = _rig()
    payload = skin.gather([mesh])
    assert skin.nodes(payload) == ["leg"]
    assert skin.describe(payload)[0] == "1 mesh, 3 influences"
    view = skin.compare_view(payload)
    assert "points" not in view["meshes"][0]
    assert isinstance(view["meshes"][0]["weights"][0], dict)


def test_save_and_load_a_skin_file(new_scene, tmp_path):
    mesh, _ = _rig()
    before = _weights(mesh)
    path = datatypes.save(skin, str(tmp_path / "leg.skin"), [mesh])
    assert datatypes.read(path, "skin")["meshes"][0]["skinCluster"] == "leg_skin"
    cmds.file(new=True, force=True)
    _skeleton()
    _mesh()
    datatypes.load(skin, path)
    assert _weights("leg") == before
