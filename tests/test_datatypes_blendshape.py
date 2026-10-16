"""BlendShape save/load (kaiju_suite.datatypes.blendshape), without the Assembler.

The Assembler's BlendShapes product (tests/test_assembler_blendshape.py)
goes through this module; the file format is unchanged.
"""

from maya import cmds

from kaiju_suite import datatypes
from kaiju_suite.datatypes import blendshape


def _base(name="face"):
    return cmds.polyPlane(name=name, subdivisionsX=4, subdivisionsY=4, constructionHistory=False)[0]


def _rig(name="face"):
    """``name`` with blendShape ``<name>BS`` holding target ``smile`` (two vertices moved)."""
    base = _base(name)
    smile = cmds.duplicate(base, name="smile")[0]
    cmds.move(0, 1, 0, f"{smile}.vtx[0]", f"{smile}.vtx[3]", relative=True, objectSpace=True)
    node = cmds.blendShape(smile, base, name=f"{name}BS")[0]
    cmds.delete(smile)
    cmds.setAttr(f"{node}.smile", 0.5)
    return base, node


def _y(mesh, vertex):
    return cmds.pointPosition(f"{mesh}.vtx[{vertex}]", local=True)[1]


def test_kind_and_extension():
    assert blendshape.KIND == "blendshape"
    assert blendshape.EXTENSION == ".bshp"


def test_gather_then_apply_rebuilds_the_blendshape(new_scene):
    base, node = _rig()
    payload = blendshape.gather(cmds.ls(base, long=True))
    cmds.delete(node)
    lines = []

    message = blendshape.apply(payload, info=lines.append)

    assert message == "Built 1 blendShape with 1 target"
    assert lines == ["faceBS: built on face, 1 target"]
    assert cmds.getAttr("faceBS.smile") == 0.5
    assert abs(_y(base, 0) - 0.5) < 1e-5


def test_save_and_load_write_the_assembler_file_format(new_scene, tmp_path):
    base, node = _rig()
    path = datatypes.save(blendshape, str(tmp_path / "face.bshp"), cmds.ls(base, long=True))
    cmds.delete(node)

    datatypes.load(blendshape, path)

    assert cmds.ls(type="blendShape") == ["faceBS"]
    record = datatypes.read(path, "blendshape")["blendshapes"][0]
    assert sorted(record) == ["base_weights", "envelope", "mesh", "name", "points", "targets", "vertex_count"]


def test_selection_problems(new_scene):
    assert blendshape.selection_problems([]) == [
        "Nothing selected. Select the meshes whose blendShapes to publish."
    ]
    joint = cmds.createNode("joint", name="jnt")
    assert blendshape.selection_problems(cmds.ls(joint, long=True)) == [
        "No meshes selected. Select the meshes whose blendShapes to publish."
    ]
    plain = _base("plain")
    rigged, _ = _rig()
    assert blendshape.selection_problems(cmds.ls([plain, rigged], long=True)) == ["No blendShape on: plain"]
    assert blendshape.selection_problems(cmds.ls(rigged, long=True)) == []


def test_describe_and_nodes(new_scene):
    base, _ = _rig()
    payload = blendshape.gather(cmds.ls(base, long=True))

    assert blendshape.describe(payload) == ["1 blendShape, 1 target", "Meshes: face"]
    assert blendshape.nodes(payload) == ["face"]


def test_compare_view_leaves_out_the_rest_points(new_scene):
    base, _ = _rig()
    payload = blendshape.gather(cmds.ls(base, long=True))

    view = blendshape.compare_view(payload)

    assert "points" not in view["blendshapes"][0]
    assert view["blendshapes"][0]["targets"] == payload["blendshapes"][0]["targets"]
    assert "points" in payload["blendshapes"][0]
