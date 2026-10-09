import os

import pytest
from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.tools.assembler import data, logic, products, runlog, versions
from kaiju_suite.tools.assembler.products import blendshape

# Weight settings the evaluated points are compared at: rest, full, an
# in-between, past full, and both targets together.
SAMPLES = (
    {"smile": 0.0, "blink": 0.0},
    {"smile": 1.0, "blink": 0.0},
    {"smile": 0.5, "blink": 0.0},
    {"smile": 0.25, "blink": 0.0},
    {"smile": 1.3, "blink": 0.0},
    {"smile": 0.0, "blink": 1.0},
    {"smile": 0.7, "blink": 0.6},
)


def _base(name="face"):
    """A 4x4 plane (25 vertices), built the same way in every scene."""
    return cmds.polyPlane(name=name, subdivisionsX=4, subdivisionsY=4, constructionHistory=False)[0]


def _sculpt(base, name, offsets):
    """A copy of ``base`` with vertex ``index`` moved by ``(x, y, z)`` for each item of ``offsets``."""
    target = cmds.duplicate(base, name=name)[0]
    for index, offset in offsets.items():
        cmds.move(*offset, f"{target}.vtx[{index}]", relative=True, objectSpace=True)
    return target


def _points(mesh):
    shape = cmds.listRelatives(mesh, shapes=True, noIntermediate=True, fullPath=True)[0]
    sel = om.MSelectionList()
    sel.add(shape)
    return [(round(p.x, 4), round(p.y, 4), round(p.z, 4)) for p in om.MFnMesh(sel.getDagPath(0)).getPoints()]


def _samples(mesh, node):
    found = []
    for weights in SAMPLES:
        for alias, value in weights.items():
            cmds.setAttr(f"{node}.{alias}", value)
        found.append(_points(mesh))
    return found


def _face_rig(live=False):
    """``face`` with blendShape ``faceBS``: target ``smile`` (with an
    in-between at 0.5, per-vertex weights) and ``blink``; base weights,
    envelope and weights off their defaults. Unless ``live``, the target
    meshes are deleted so the deltas are only stored on the node."""
    base = _base()
    smile = _sculpt(base, "smile", {0: (0, 1, 0), 3: (0, 0.5, 0.2)})
    smile_mid = _sculpt(base, "smile_mid", {0: (0.3, 0.2, 0), 7: (0, -0.4, 0)})
    blink = _sculpt(base, "blink", {12: (0, 0, 1), 13: (0.1, 0, 0)})
    node = cmds.blendShape(smile, blink, base, name="faceBS")[0]
    cmds.blendShape(node, edit=True, inBetween=True, target=(base, 0, smile_mid, 0.5))
    cmds.setAttr(f"{node}.inputTarget[0].inputTargetGroup[0].targetWeights[3]", 0.25)
    cmds.setAttr(f"{node}.inputTarget[0].baseWeights[12]", 0.5)
    cmds.setAttr(f"{node}.envelope", 0.9)
    cmds.setAttr(f"{node}.smile", 0.3)
    cmds.setAttr(f"{node}.blink", 0.8)
    if not live:
        cmds.delete(smile, smile_mid, blink)
    return base, node


def _publish(tmp_path, *selection, name="face"):
    path = blendshape.PRODUCT.create(str(tmp_path), name)
    cmds.select(selection)
    message = versions.publish_action(path).fn()
    return path, message


def _blendshapes():
    return sorted(cmds.ls(type="blendShape"))


# -- product ----------------------------------------------------------------


def test_blendshape_is_discovered_and_owns_bshp(tmp_path):
    assert blendshape.PRODUCT in products.discover()
    assert blendshape.PRODUCT.name == "BlendShapes"
    assert blendshape.PRODUCT.extensions == (".bshp",)
    assert blendshape.PRODUCT.order == 80
    assert blendshape.PRODUCT.kind == "blendshape"
    assert blendshape.PRODUCT.runnable and blendshape.PRODUCT.versioned
    path = blendshape.PRODUCT.creators[0].fn(str(tmp_path), "face", None)
    assert path == str(tmp_path / "face.bshp") and os.path.getsize(path) == 0
    assert products.product_for(path) is blendshape.PRODUCT


# -- publish and run --------------------------------------------------------


def test_round_trip_restores_targets_and_evaluated_points(new_scene, tmp_path):
    base, node = _face_rig()
    before = _samples(base, node)
    cmds.setAttr(f"{node}.smile", 0.3)
    cmds.setAttr(f"{node}.blink", 0.8)
    path, message = _publish(tmp_path, base)
    assert message == "Published BlendShapes face.bshp v001"

    cmds.file(new=True, force=True)
    _base()
    logic.run_steps([path])

    assert _blendshapes() == ["faceBS"]
    assert cmds.getAttr("faceBS.smile") == pytest.approx(0.3)
    assert cmds.getAttr("faceBS.blink") == pytest.approx(0.8)
    assert cmds.getAttr("faceBS.envelope") == pytest.approx(0.9)
    assert cmds.listAttr("faceBS.weight", multi=True) == ["smile", "blink"]
    assert cmds.getAttr("faceBS.inputTarget[0].inputTargetGroup[0].inputTargetItem", multiIndices=True) == [
        5500,
        6000,
    ]
    assert _samples("face", "faceBS") == before
    # No target geometry was made.
    assert cmds.ls(type="mesh", noIntermediate=True) == ["faceShape"]


def test_file_holds_sparse_deltas_and_weights(new_scene, tmp_path):
    base, node = _face_rig()
    path, _ = _publish(tmp_path, base)
    (record,) = data.read(path, "blendshape")["blendshapes"]
    assert record["name"] == "faceBS"
    assert record["mesh"] == "face"
    assert record["vertex_count"] == 25
    assert record["envelope"] == pytest.approx(0.9)
    assert record["base_weights"] == {"12": pytest.approx(0.5)}
    smile, blink = record["targets"]
    assert (smile["name"], smile["index"], smile["weight"]) == ("smile", 0, pytest.approx(0.3))
    assert (blink["name"], blink["index"]) == ("blink", 1)
    assert smile["weights"] == {"3": pytest.approx(0.25)}
    assert blink["weights"] == {}
    assert [item["item"] for item in smile["items"]] == [5500, 6000]
    full = smile["items"][1]
    assert full["indices"] == [0, 3]
    assert full["deltas"] == [pytest.approx([0, 1, 0]), pytest.approx([0, 0.5, 0.2])]


def test_live_sculpt_target_is_saved_from_the_sculpt_mesh(new_scene, tmp_path):
    base, node = _face_rig(live=True)
    assert cmds.listConnections(f"{node}.inputTarget[0].inputTargetGroup[0].inputTargetItem[6000].inputGeomTarget")
    # Sculpt the live target after the blendShape was made, and publish
    # before anything evaluates the blendShape: its stored deltas are stale.
    cmds.move(0, 0, 2, "smile.vtx[20]", relative=True, objectSpace=True)
    path, _ = _publish(tmp_path, base)
    (record,) = data.read(path, "blendshape")["blendshapes"]
    assert 20 in record["targets"][0]["items"][1]["indices"]
    before = _samples(base, node)

    cmds.file(new=True, force=True)
    _base()
    blendshape.PRODUCT.run(path)
    assert _samples("face", "faceBS") == before


def test_blendshape_goes_before_an_existing_skin(new_scene, tmp_path):
    base, node = _face_rig()
    before = _samples(base, node)
    path, _ = _publish(tmp_path, base)

    cmds.file(new=True, force=True)
    face = _base()
    joint = cmds.createNode("joint", name="root_jnt")
    skin = cmds.skinCluster(joint, face, toSelectedBones=True)[0]
    blendshape.PRODUCT.run(path)

    deformers = cmds.ls(cmds.listHistory(face, pruneDagObjects=True), type="geometryFilter")
    # History lists from the mesh back: the skin is applied after the blendShape.
    assert deformers.index(skin) < deformers.index("faceBS")
    assert _samples(face, "faceBS") == before


def test_running_again_replaces_the_same_named_node(new_scene, tmp_path):
    base, node = _face_rig()
    before = _samples(base, node)
    path, _ = _publish(tmp_path, base)

    blendshape.PRODUCT.run(path)
    blendshape.PRODUCT.run(path)
    assert _blendshapes() == ["faceBS"]
    assert _samples(base, "faceBS") == before


def test_several_meshes_round_trip(new_scene, tmp_path):
    base, node = _face_rig()
    other = _base("body")
    cmds.blendShape(_sculpt(other, "fat", {1: (0, 0, 3)}), other, name="bodyBS")
    cmds.delete("fat")
    path, _ = _publish(tmp_path, base, other)
    assert blendshape.PRODUCT.panel(path).info == ["2 blendShapes, 3 targets", "Meshes: face, body"]

    cmds.file(new=True, force=True)
    _base()
    _base("body")
    blendshape.PRODUCT.run(path)
    assert _blendshapes() == ["bodyBS", "faceBS"]
    cmds.setAttr("bodyBS.fat", 1)
    assert _points("body")[1][2] == pytest.approx(_points("face")[1][2] + 3)


def test_missing_mesh_is_skipped_with_a_warning(new_scene, tmp_path):
    base, node = _face_rig()
    other = _base("body")
    cmds.blendShape(_sculpt(other, "fat", {1: (0, 0, 3)}), other, name="bodyBS")
    path, _ = _publish(tmp_path, base, other)

    cmds.file(new=True, force=True)
    _base()  # body is missing
    with runlog.capture() as run:
        blendshape.PRODUCT.run(path)
    assert run.warnings == ["Skipped missing meshes: body"]
    assert _blendshapes() == ["faceBS"]


def test_vertex_count_mismatch_raises_and_changes_nothing(new_scene, tmp_path):
    base, node = _face_rig()
    path, _ = _publish(tmp_path, base)

    cmds.file(new=True, force=True)
    face = cmds.polyPlane(name="face", subdivisionsX=2, subdivisionsY=2, constructionHistory=False)[0]
    old = cmds.blendShape(_sculpt(face, "old_tgt", {0: (0, 1, 0)}), face, name="faceBS")[0]
    with pytest.raises(RuntimeError) as info:
        blendshape.PRODUCT.run(path)
    assert "face" in str(info.value) and "25" in str(info.value) and "9" in str(info.value)
    # The existing same-named node is still there, untouched.
    assert _blendshapes() == [old]
    assert cmds.listAttr(f"{old}.weight", multi=True) == ["old_tgt"]


def test_empty_file_is_skipped(new_scene, tmp_path):
    _base()
    path = blendshape.PRODUCT.create(str(tmp_path), "face")
    assert logic.run_steps([path]) == [path]
    assert _blendshapes() == []


def test_one_undo_reverts_a_run(new_scene, tmp_path):
    base, node = _face_rig()
    path, _ = _publish(tmp_path, base)
    cmds.file(new=True, force=True)
    face = _base()
    rest = _points(face)
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    blendshape.PRODUCT.run(path)
    assert _blendshapes() == ["faceBS"]
    cmds.undo()
    assert _blendshapes() == []
    assert _points(face) == rest


def test_one_undo_restores_a_replaced_node(new_scene, tmp_path):
    base, node = _face_rig()
    before = _samples(base, node)
    path, _ = _publish(tmp_path, base)
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    blendshape.PRODUCT.run(path)
    cmds.undo()
    assert _blendshapes() == ["faceBS"]
    assert _samples(base, "faceBS") == before


# -- publish checks and versions --------------------------------------------


def test_publish_problems(new_scene, tmp_path):
    path = blendshape.PRODUCT.create(str(tmp_path), "face")
    cmds.select(clear=True)
    (problem,) = versions.publish_problems(path)
    assert "Nothing selected" in problem

    cmds.select(cmds.createNode("joint"))
    (problem,) = versions.publish_problems(path)
    assert "mesh" in problem.lower()

    plain = _base("plain")
    rigged, _ = _face_rig()
    cmds.select(plain, rigged)
    (problem,) = versions.publish_problems(path)
    assert "plain" in problem and "face" not in problem

    cmds.select(rigged)
    assert versions.publish_problems(path) == []
    # The shape works as well as its transform.
    cmds.select("faceShape")
    assert versions.publish_problems(path) == []


def test_publish_without_blendshape_raises_and_writes_nothing(new_scene, tmp_path):
    path = blendshape.PRODUCT.create(str(tmp_path), "face")
    cmds.select(_base())
    with pytest.raises(RuntimeError):
        versions.publish_action(path).fn()
    assert os.path.getsize(path) == 0


def test_republishing_adds_a_version_only_on_change(new_scene, tmp_path):
    base, node = _face_rig()
    path, message = _publish(tmp_path, base)
    assert message.endswith("v001")

    cmds.select(base)
    assert versions.publish_action(path).fn().endswith("v001")
    assert [v.number for v in versions.list_versions(path)] == [1]

    cmds.setAttr(f"{node}.blink", 0.1)
    assert versions.publish_action(path).fn().endswith("v002")
