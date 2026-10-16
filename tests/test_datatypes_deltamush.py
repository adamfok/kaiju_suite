"""DeltaMush save/load (kaiju_suite.datatypes.deltamush), without the Assembler.

The Assembler's DeltaMush product (tests/test_assembler_deltamush.py) and
Kaiju Builder's DeltaMush items both go through this module.
"""

import pytest
from maya import cmds

from kaiju_suite import datatypes
from kaiju_suite.datatypes import deltamush
from kaiju_suite.tools.assembler import runlog


def _mesh(name="body"):
    """A subdivided cube (26 vertices) with no history."""
    return cmds.polyCube(name=name, width=2, height=4, depth=2, sx=2, sy=2, sz=2, ch=False)[0]


def _mush(mesh, name="body_dm", painted=None):
    node = cmds.deltaMush(mesh, name=name)[0]
    cmds.setAttr(f"{node}.smoothingIterations", 7)
    for vertex, weight in (painted or {3: 0.25}).items():
        cmds.setAttr(f"{node}.weightList[0].weights[{vertex}]", weight)
    return node


def _long(*nodes):
    return cmds.ls(nodes, long=True)


def test_kind_and_extension():
    assert deltamush.KIND == "deltamush"
    assert deltamush.EXTENSION == ".dmsh"


def test_gather_then_apply_restores_the_deltamush(new_scene):
    mesh = _mesh()
    _mush(mesh)
    payload = deltamush.gather(_long(mesh))
    (record,) = payload["deltamush"]
    assert (record["name"], record["mesh"], record["weights"]) == ("body_dm", "body", [[3, 0.25]])

    cmds.file(new=True, force=True)
    _mesh()
    lines = []
    message = deltamush.apply(payload, info=lines.append)

    assert message == "Created deltaMush body_dm on body"
    assert lines == ["body_dm: created on body"]
    assert cmds.getAttr("body_dm.smoothingIterations") == 7
    assert cmds.getAttr("body_dm.weightList[0].weights[3]") == pytest.approx(0.25)


def test_apply_skips_a_missing_mesh_with_a_maya_warning(new_scene):
    mesh = _mesh()
    _mush(mesh)
    payload = deltamush.gather(_long(mesh))
    cmds.delete(mesh)
    with runlog.capture() as run:
        assert deltamush.apply(payload) == "Created no deltaMush nodes"
    assert run.warnings == ["Skipped missing meshes: body"]


def test_gather_needs_meshes_with_a_deltamush(new_scene):
    bare = _mesh("bare")
    with pytest.raises(RuntimeError, match="No deltaMush"):
        deltamush.gather(_long(bare))


def test_selection_problems(new_scene):
    assert "Nothing selected" in deltamush.selection_problems([])[0]
    assert "No meshes" in deltamush.selection_problems(_long(cmds.createNode("transform")))[0]
    body, head = _mesh("body"), _mesh("head")
    _mush(body)
    assert deltamush.selection_problems(_long(body, head)) == ["No deltaMush on: head"]
    assert deltamush.selection_problems(_long(body)) == []


def test_nodes_describe_and_compare_view(new_scene):
    body, head = _mesh("body"), _mesh("head")
    _mush(body, "body_dm")
    _mush(head, "head_dm")
    payload = deltamush.gather(_long(body, head))

    assert deltamush.nodes(payload) == ["body", "head"]
    assert deltamush.describe(payload) == ["2 deltaMush nodes", "Meshes: body, head"]
    view = deltamush.compare_view(payload)["deltamush"][0]
    assert "points" not in view
    assert len(view["weights"]) == 26 and view["weights"][3] == 0.25 and view["weights"][0] == 1.0


def test_save_and_load_files_the_assembler_reads(new_scene, tmp_path):
    mesh = _mesh()
    _mush(mesh)
    path = datatypes.save(deltamush, str(tmp_path / "mush.dmsh"), _long(mesh))
    assert datatypes.read(path, "deltamush")["deltamush"][0]["name"] == "body_dm"

    cmds.delete("body_dm")
    datatypes.load(deltamush, path)
    assert cmds.ls(type="deltaMush") == ["body_dm"]
