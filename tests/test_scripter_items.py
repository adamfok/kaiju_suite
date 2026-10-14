"""Kaiju Scripter items beyond scripts: Joints, Skin and Mesh (data published
from the selection, versioned) and Import File / Export File (a path)."""

import json
import os

import pytest
from maya import cmds

from kaiju_suite.tools.scripter import items, logic, versions


def _chain():
    cmds.select(clear=True)
    made = [cmds.joint(name=n, position=(0, i * 2, 0)) for i, n in enumerate(("hip", "knee", "ankle"))]
    cmds.select(clear=True)
    return made


def _long(nodes):
    return cmds.ls(nodes, long=True)


# -- data items -------------------------------------------------------------


def test_new_joints_item_publishes_the_selection_as_v001(tmp_path, new_scene):
    hip = _chain()[0]

    path = logic.create_data_item(items.JOINTS, str(tmp_path), "skeleton", _long(hip))

    assert path == os.path.join(str(tmp_path), "skeleton.jnt")
    assert versions.label(path) == "v001"
    assert items.describe(path) == ["3 joints", "Roots: hip"]
    [entry] = logic.scan(str(tmp_path))
    assert (entry.kind, entry.type_label) == (items.JOINTS, "Joints")


def test_new_data_item_without_a_valid_selection_creates_nothing(tmp_path, new_scene):
    cube = cmds.polyCube(name="box")[0]
    with pytest.raises(ValueError, match="No joints selected"):
        logic.create_data_item(items.JOINTS, str(tmp_path), "skeleton", _long(cube))
    with pytest.raises(ValueError, match="Nothing selected"):
        logic.create_data_item(items.MESH, str(tmp_path), "body", [])
    assert logic.scan(str(tmp_path)) == []


def test_running_a_joints_item_rebuilds_them_as_one_undo_step(tmp_path, new_scene):
    path = logic.create_data_item(items.JOINTS, str(tmp_path), "skeleton", _long(_chain()[0]))
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    assert logic.Runner().run([path]) == logic.DONE
    assert cmds.listRelatives("ankle", parent=True) == ["knee"]

    cmds.undo()
    assert not cmds.objExists("hip")


def test_publish_data_saves_a_new_version_only_when_it_changed(tmp_path, new_scene):
    hip = _chain()[0]
    path = logic.create_data_item(items.JOINTS, str(tmp_path), "skeleton", _long(hip))

    with pytest.raises(ValueError, match="No changes"):
        items.publish_data(path, _long(hip), "Same")
    cmds.setAttr("knee.translateX", 1)
    assert items.publish_data(path, _long(hip), "Moved the knee") == 2
    assert [v.description for v in versions.list_versions(path)][-1] == "Moved the knee"


def test_publish_data_checks_the_selection_before_writing(tmp_path, new_scene):
    path = logic.create_data_item(items.JOINTS, str(tmp_path), "skeleton", _long(_chain()[0]))
    with open(path, encoding="utf-8") as f:
        before = f.read()
    with pytest.raises(ValueError):
        items.publish_data(path, [], "")
    with open(path, encoding="utf-8") as f:
        assert f.read() == before


def test_mesh_item_round_trip(tmp_path, new_scene):
    cube = cmds.polyCube(name="box", constructionHistory=False)[0]
    path = logic.create_data_item(items.MESH, str(tmp_path), "body", _long(cube))
    cmds.file(new=True, force=True)
    logic.Runner().run([path])
    assert cmds.polyEvaluate("box", vertex=True) == 8
    assert items.describe(path) == ["1 mesh", "box"]


def test_skin_item_round_trip(tmp_path, new_scene):
    joints = _chain()
    mesh = cmds.polyCylinder(name="leg", height=4, subdivisionsY=4, constructionHistory=False)[0]
    cmds.skinCluster(*joints, mesh, toSelectedBones=True, name="leg_skin")
    path = logic.create_data_item(items.SKIN, str(tmp_path), "leg", _long(mesh))

    cmds.delete("leg_skin")
    logic.Runner().run([path])

    assert cmds.ls(cmds.listHistory(mesh), type="skinCluster")
    assert logic.scan(str(tmp_path))[0].type_label == "Skin"


def test_data_items_are_versioned(tmp_path, new_scene):
    path = logic.create_data_item(items.JOINTS, str(tmp_path), "skeleton", _long(_chain()[0]))
    assert versions.is_versioned(path)


# -- import file ------------------------------------------------------------


def _maya_file(path, node="imported_node"):
    cmds.file(new=True, force=True)
    cmds.createNode("transform", name=node)
    cmds.file(rename=str(path))
    cmds.file(save=True, type="mayaAscii", force=True)
    cmds.file(new=True, force=True)
    return str(path)


def test_import_file_stores_a_path_relative_to_the_folder_when_inside(tmp_path, new_scene):
    (tmp_path / "files").mkdir()
    target = _maya_file(tmp_path / "files" / "body.ma")
    path = logic.create_file_item(items.IMPORT_FILE, str(tmp_path), "body", target)

    assert path.endswith("body.import")
    with open(path, encoding="utf-8") as f:
        assert json.load(f) == {"path": "files/body.ma"}
    assert os.path.normcase(items.target(path)) == os.path.normcase(os.path.normpath(target))
    entry = next(e for e in logic.scan(str(tmp_path)) if e.name == "body.import")
    assert entry.type_label == "Import File"
    assert not versions.is_versioned(path)


def test_import_file_keeps_an_absolute_path_outside_the_folder(tmp_path, new_scene):
    target = _maya_file(tmp_path / "elsewhere.ma")
    folder = tmp_path / "scripts"
    folder.mkdir()
    path = logic.create_file_item(items.IMPORT_FILE, str(folder), "body", target)
    with open(path, encoding="utf-8") as f:
        assert os.path.normcase(json.load(f)["path"]) == os.path.normcase(target.replace("\\", "/"))


def test_running_an_import_file_imports_without_a_namespace(tmp_path, new_scene):
    target = _maya_file(tmp_path / "body.ma")
    path = logic.create_file_item(items.IMPORT_FILE, str(tmp_path), "body", target)

    assert logic.Runner().run([path]) == logic.DONE

    assert cmds.ls("imported_node", long=True) == ["|imported_node"]


def test_set_target_changes_the_path(tmp_path, new_scene):
    first = _maya_file(tmp_path / "a.ma")
    second = _maya_file(tmp_path / "b.ma", node="other_node")
    path = logic.create_file_item(items.IMPORT_FILE, str(tmp_path), "body", first)

    items.set_target(path, second)
    logic.Runner().run([path])

    assert cmds.objExists("other_node")
    assert not cmds.objExists("imported_node")


def test_importing_a_missing_file_fails_the_step(tmp_path, new_scene):
    target = _maya_file(tmp_path / "gone.ma")
    path = logic.create_file_item(items.IMPORT_FILE, str(tmp_path), "gone", target)
    os.remove(target)
    runner = logic.Runner()

    assert runner.run([path]) == logic.FAILED
    status, message = runner.status(path)
    assert "not found" in message.lower()


# -- export file ------------------------------------------------------------


def test_running_an_export_file_exports_the_selection(tmp_path, new_scene):
    out = str(tmp_path / "out" / "rig.ma")
    path = logic.create_file_item(items.EXPORT_FILE, str(tmp_path), "rig", out)
    assert logic.scan(str(tmp_path))[0].type_label == "Export File"
    cmds.createNode("transform", name="keep_me")
    cmds.createNode("transform", name="leave_me")
    cmds.select("keep_me")

    assert logic.Runner().run([path]) == logic.DONE

    cmds.file(new=True, force=True)
    cmds.file(out, i=True)
    assert cmds.objExists("keep_me")
    assert not cmds.objExists("leave_me")


def test_export_overwrites_an_existing_file(tmp_path, new_scene):
    out = str(tmp_path / "rig.ma")
    path = logic.create_file_item(items.EXPORT_FILE, str(tmp_path), "rig", out)
    cmds.select(cmds.createNode("transform", name="first"))
    logic.Runner().run([path])
    cmds.select(cmds.createNode("transform", name="second"))
    assert logic.Runner().run([path]) == logic.DONE

    cmds.file(new=True, force=True)
    cmds.file(out, i=True)
    assert cmds.objExists("second") and not cmds.objExists("first")


def test_export_with_nothing_selected_fails(tmp_path, new_scene):
    out = tmp_path / "rig.ma"
    path = logic.create_file_item(items.EXPORT_FILE, str(tmp_path), "rig", str(out))
    cmds.select(clear=True)
    runner = logic.Runner()

    assert runner.run([path]) == logic.FAILED
    assert "Nothing selected to export" in runner.status(path)[1]
    assert not out.exists()


def test_export_refuses_formats_it_cant_write(tmp_path):
    with pytest.raises(ValueError, match="Can't export"):
        logic.create_file_item(items.EXPORT_FILE, str(tmp_path), "rig", str(tmp_path / "rig.xyz"))
    assert logic.scan(str(tmp_path)) == []
