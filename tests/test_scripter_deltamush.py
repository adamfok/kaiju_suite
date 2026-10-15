"""Kaiju Scripter's DeltaMush items (.dmsh): deltaMush nodes published from
the selected meshes with kaiju_suite.datatypes.deltamush, versioned, applied
back when run, opening the DeltaMush Tool on double-click."""

import os

import pytest
from maya import cmds

from kaiju_suite import registry
from kaiju_suite.tools.scripter import items, logic, versions


def _mesh(name="body"):
    return cmds.polyCube(name=name, sx=2, sy=2, sz=2, constructionHistory=False)[0]


def _mush(mesh, name="body_dm"):
    node = cmds.deltaMush(mesh, name=name)[0]
    cmds.setAttr(f"{node}.weightList[0].weights[3]", 0.25)
    return node


def _long(*nodes):
    return cmds.ls(nodes, long=True)


def test_new_deltamush_item_publishes_the_selection_as_v001(tmp_path, new_scene):
    mesh = _mesh()
    _mush(mesh)

    path = logic.create_data_item(items.DELTAMUSH, str(tmp_path), "mush", _long(mesh))

    assert path == os.path.join(str(tmp_path), "mush.dmsh")
    assert versions.is_versioned(path)
    assert versions.label(path) == "v001"
    assert items.describe(path) == ["1 deltaMush node", "Meshes: body"]
    [entry] = logic.scan(str(tmp_path))
    assert (entry.kind, entry.type_label) == (items.DELTAMUSH, "DeltaMush")


def test_new_deltamush_item_needs_a_mesh_with_a_deltamush(tmp_path, new_scene):
    mesh = _mesh()
    with pytest.raises(ValueError, match="No deltaMush on: body"):
        logic.create_data_item(items.DELTAMUSH, str(tmp_path), "mush", _long(mesh))
    assert logic.scan(str(tmp_path)) == []


def test_running_a_deltamush_item_rebuilds_it_as_one_undo_step(tmp_path, new_scene):
    mesh = _mesh()
    _mush(mesh)
    path = logic.create_data_item(items.DELTAMUSH, str(tmp_path), "mush", _long(mesh))
    cmds.delete("body_dm")
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    assert logic.Runner().run([path]) == logic.DONE
    assert cmds.ls(type="deltaMush") == ["body_dm"]
    assert cmds.getAttr("body_dm.weightList[0].weights[3]") == pytest.approx(0.25)

    cmds.undo()
    assert not cmds.ls(type="deltaMush")


def test_publishing_again_adds_a_version(tmp_path, new_scene):
    mesh = _mesh()
    _mush(mesh)
    path = logic.create_data_item(items.DELTAMUSH, str(tmp_path), "mush", _long(mesh))
    cmds.setAttr("body_dm.weightList[0].weights[4]", 0.5)

    assert items.publish_data(path, _long(mesh), "painted more") == 2
    assert versions.label(path) == "v002"


def test_saved_objects_are_its_meshes(tmp_path, new_scene):
    mesh = _mesh()
    _mush(mesh)
    path = logic.create_data_item(items.DELTAMUSH, str(tmp_path), "mush", _long(mesh))

    assert items.saved_objects(path) == (["|body"], [])


def test_deltamush_items_open_the_deltamush_tool():
    assert items.tool_for(items.DELTAMUSH) == "DeltaMush Tool"
    assert registry.find(items.tool_for(items.DELTAMUSH)) is not None


def test_open_in_tool_selects_the_meshes_then_launches_the_tool(tmp_path, new_scene, monkeypatch):
    mesh = _mesh()
    _mush(mesh)
    path = logic.create_data_item(items.DELTAMUSH, str(tmp_path), "mush", _long(mesh))
    cmds.select(clear=True)
    calls = []
    monkeypatch.setattr(
        registry, "find", lambda name: {"name": name, "launch": lambda: calls.append((name, cmds.ls(selection=True)))}
    )

    assert items.open_in_tool(path) == "Selected 1 object from mush.dmsh"
    assert calls == [("DeltaMush Tool", ["body"])]


def test_publish_qc_runs_the_deltamush_checks(tmp_path, new_scene):
    mesh = _mesh()
    node = _mush(mesh)
    path = logic.create_data_item(items.DELTAMUSH, str(tmp_path), "mush", _long(mesh))
    cmds.setAttr(f"{node}.envelope", 0)

    found = dict((check.key, problems) for check, problems in items.publish_qc(path, _long(mesh)))

    assert list(found) == ["missing", "below_skin", "disabled", "empty_weights", "duplicate_names"]
    assert found["disabled"] == ["body_dm on body: envelope is 0"]
