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


# -- selection --------------------------------------------------------------


def _picked(*names):
    return [{"type": items.PICKED, "value": n} for n in names]


def test_new_selection_item_saves_the_selection_as_picked_entries(tmp_path, new_scene):
    a = cmds.createNode("transform", name="body_geo")
    b = cmds.createNode("transform", name="hair_geo")

    path = logic.create_selection_item(str(tmp_path), "hero", [a, b])

    assert path == os.path.join(str(tmp_path), "hero.sel")
    assert items.read_entries(path) == _picked("body_geo", "hair_geo")
    [entry] = logic.scan(str(tmp_path))
    assert (entry.kind, entry.type_label) == (items.SELECTION, "Selection")
    assert not versions.is_versioned(path)


def test_new_selection_item_with_nothing_selected_starts_empty(tmp_path, new_scene):
    path = logic.create_selection_item(str(tmp_path), "hero", [])
    assert items.read_entries(path) == []


def test_entries_round_trip(tmp_path):
    path = logic.create_selection_item(str(tmp_path), "hero", [])
    entries = [
        {"type": items.PICKED, "value": "body_geo"},
        {"type": items.PATTERN, "value": "*_geo"},
        {"type": items.SET, "value": "render_set"},
    ]
    items.write_entries(path, entries)
    assert items.read_entries(path) == entries


def test_add_picked_keeps_order_and_skips_ones_already_there():
    entries = _picked("a")
    assert items.add_picked(entries, ["b", "a", "c", "b"]) == _picked("a", "b", "c")


def test_picked_names_are_the_shortest_unique_ones(new_scene):
    for group in ("L_arm", "R_arm"):
        cmds.createNode("transform", name="hand_geo", parent=cmds.createNode("transform", name=group))
    cmds.createNode("transform", name="body_geo")
    cmds.select("body_geo", "|L_arm|hand_geo")

    assert items.picked_names() == ["body_geo", "L_arm|hand_geo"]


def test_picked_entry_finds_its_object_and_components(new_scene):
    cube = cmds.polyCube(name="body_geo")[0]
    assert items.find({"type": items.PICKED, "value": cube}) == ["body_geo"]
    assert items.find({"type": items.PICKED, "value": "body_geo.f[0:2]"}) == ["body_geo.f[0:2]"]
    assert items.find({"type": items.PICKED, "value": "gone"}) == []


def test_picked_entry_still_finds_an_object_after_reparenting(new_scene):
    node = cmds.createNode("transform", name="body_geo")
    cmds.parent(node, cmds.createNode("transform", name="grp"))
    assert items.find({"type": items.PICKED, "value": "body_geo"}) == ["body_geo"]


def test_pattern_entry_uses_maya_wildcards(new_scene):
    for name in ("body_geo", "hair_geo", "body_ctl"):
        cmds.createNode("transform", name=name)
    assert sorted(items.find({"type": items.PATTERN, "value": "*_geo"})) == ["body_geo", "hair_geo"]
    assert sorted(items.find({"type": items.PATTERN, "value": "body_* hair_?eo"})) == [
        "body_ctl",
        "body_geo",
        "hair_geo",
    ]
    assert items.find({"type": items.PATTERN, "value": "*_nothing"}) == []


def test_set_entry_expands_nested_sets(new_scene):
    a, b, c = (cmds.createNode("transform", name=n) for n in ("a", "b", "c"))
    inner = cmds.sets(b, c, name="inner_set")
    cmds.sets(a, inner, name="outer_set")

    assert sorted(items.find({"type": items.SET, "value": "outer_set"})) == ["a", "b", "c"]
    assert items.find({"type": items.SET, "value": "missing_set"}) == []
    assert items.find({"type": items.SET, "value": "a"}) == []


def test_set_entry_keeps_components(new_scene):
    cube = cmds.polyCube(name="body_geo")[0]
    cmds.sets(f"{cube}.f[0:1]", name="faces_set")
    assert items.find({"type": items.SET, "value": "faces_set"}) == ["body_geo.f[0:1]"]


def test_resolve_combines_in_entry_order_without_repeats(new_scene):
    for name in ("c_geo", "a_geo", "b_geo"):
        cmds.createNode("transform", name=name)
    entries = _picked("c_geo") + [{"type": items.PATTERN, "value": "*_geo"}] + _picked("a_geo")

    objects, empty = items.resolve(entries)

    assert objects[0] == "c_geo"
    assert sorted(objects) == ["a_geo", "b_geo", "c_geo"]
    assert empty == []


def test_resolve_reports_entries_that_find_nothing(new_scene):
    cmds.createNode("transform", name="a_geo")
    entries = _picked("a_geo", "gone") + [{"type": items.SET, "value": "no_set"}]
    assert items.resolve(entries) == (["a_geo"], entries[1:])


def test_running_a_selection_item_replaces_the_selection_in_order(tmp_path, new_scene):
    for name in ("first", "second", "other"):
        cmds.createNode("transform", name=name)
    path = logic.create_selection_item(str(tmp_path), "hero", ["second", "first"])
    cmds.select("other")

    assert logic.Runner().run([path]) == logic.DONE
    assert cmds.ls(selection=True) == ["second", "first"]


def test_running_a_selection_item_finds_objects_made_by_earlier_steps(tmp_path, new_scene):
    make = tmp_path / "make.py"
    make.write_text("from maya import cmds\ncmds.createNode('transform', name='new_geo')\n")
    path = logic.create_selection_item(str(tmp_path), "geo", [])
    items.write_entries(path, [{"type": items.PATTERN, "value": "*_geo"}])

    assert logic.Runner().run([str(make), path]) == logic.DONE
    assert cmds.ls(selection=True) == ["new_geo"]


def test_selection_item_fails_naming_the_entries_that_found_nothing(tmp_path, new_scene):
    cmds.createNode("transform", name="here")
    path = logic.create_selection_item(str(tmp_path), "hero", ["here"])
    items.write_entries(path, _picked("here", "gone") + [{"type": items.SET, "value": "no_set"}])
    cmds.select(clear=True)
    runner = logic.Runner()

    assert runner.run([path]) == logic.FAILED
    message = runner.status(path)[1]
    assert "gone" in message and "set: no_set" in message and "here," not in message
    assert cmds.ls(selection=True) == []


def test_empty_selection_item_fails(tmp_path, new_scene):
    path = logic.create_selection_item(str(tmp_path), "hero", [])
    runner = logic.Runner()
    assert runner.run([path]) == logic.FAILED
    assert "no entries" in runner.status(path)[1].lower()


def test_summary_lists_the_entries(tmp_path):
    entries = _picked("body_geo") + [
        {"type": items.PATTERN, "value": "*_eye_geo"},
        {"type": items.SET, "value": "render_set"},
    ]
    assert items.summary(entries) == "body_geo, *_eye_geo, set: render_set"
    assert items.summary([]) == "No entries. Double-click to add some."
    many = _picked(*(f"n{i}" for i in range(12)))
    assert items.summary(many).endswith("n9 ...and 2 more")


def test_scene_sets_lists_selection_sets_only(new_scene):
    cmds.sets(cmds.createNode("transform"), name="render_set")
    cmds.sets(name="empty_set", empty=True)
    assert items.scene_sets() == ["empty_set", "render_set"]
