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


def test_publishing_unchanged_data_leaves_the_item_unmodified(tmp_path, new_scene):
    """'No changes' puts the file back byte for byte, so the Version column
    doesn't gain a ``*`` (on Windows a text-mode write turned LF into CRLF)."""
    hip = _chain()[0]
    path = logic.create_data_item(items.JOINTS, str(tmp_path), "skeleton", _long(hip))
    with open(path, "rb") as f:
        before = f.read()

    with pytest.raises(ValueError, match="No changes"):
        items.publish_data(path, _long(hip), "Same")

    assert versions.label(path) == "v001"
    assert not versions.has_unpublished(path)
    with open(path, "rb") as f:
        assert f.read() == before


def test_unchanged_since_checks_the_selection_without_writing(tmp_path, new_scene):
    """Publish asks this first, so "No changes" never costs a description."""
    hip = _chain()[0]
    path = logic.create_data_item(items.JOINTS, str(tmp_path), "skeleton", _long(hip))
    with open(path, "rb") as f:
        before = f.read()

    assert items.unchanged_since(path, _long(hip)) == 1
    cmds.setAttr("knee.translateX", 1)
    assert items.unchanged_since(path, _long(hip)) is None
    with open(path, "rb") as f:
        assert f.read() == before  # only compared, not written
    assert sorted(os.listdir(str(tmp_path))) == [".scripter", "skeleton.jnt"]  # no temporary files left


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


# -- Select Objects, and publishing again from the saved objects ------------


def test_select_saved_selects_the_objects_in_the_file(tmp_path, new_scene):
    path = logic.create_data_item(items.JOINTS, str(tmp_path), "skeleton", _long(_chain()[0]))
    cmds.createNode("transform", name="other")
    cmds.select("other")

    assert items.select_saved(path) == "Selected 3 objects from skeleton.jnt"
    assert cmds.ls(selection=True) == ["hip", "knee", "ankle"]


def test_select_saved_names_missing_and_ambiguous_objects(tmp_path, new_scene):
    path = logic.create_data_item(items.JOINTS, str(tmp_path), "skeleton", _long(_chain()[0]))
    cmds.delete("ankle")
    grp = cmds.createNode("transform", name="grp")
    cmds.createNode("transform", name="knee", parent=grp)

    message = items.select_saved(path)
    assert message.startswith("Selected 1 object from skeleton.jnt. ")
    assert "Missing in the scene: ankle" in message
    assert "Several nodes are called knee" in message
    assert cmds.ls(selection=True) == ["hip"]


def test_select_saved_with_nothing_found_clears_the_selection(tmp_path, new_scene):
    cube = cmds.polyCube(name="box", constructionHistory=False)[0]
    path = logic.create_data_item(items.MESH, str(tmp_path), "body", _long(cube))
    cmds.rename(cube, "crate")
    cmds.select("crate")
    assert items.select_saved(path).startswith("Selected 0 objects from body.mesh. Missing in the scene: box")
    assert cmds.ls(selection=True) == []


def test_saved_objects_of_a_skin_item_are_its_meshes(tmp_path, new_scene):
    joints = _chain()
    mesh = cmds.polyCylinder(name="leg", height=4, constructionHistory=False)[0]
    cmds.skinCluster(*joints, mesh, toSelectedBones=True, name="leg_skin")
    path = logic.create_data_item(items.SKIN, str(tmp_path), "leg", _long(mesh))
    assert items.saved_objects(path) == (["|leg"], [])


def test_publishing_the_saved_objects_updates_the_item_from_them(tmp_path, new_scene):
    """What Publish does with nothing selected."""
    path = logic.create_data_item(items.JOINTS, str(tmp_path), "skeleton", _long(_chain()[0]))
    cmds.select(clear=True)
    found, problems = items.saved_objects(path)
    assert (found, problems) == (["|hip", "|hip|knee", "|hip|knee|ankle"], [])
    assert items.unchanged_since(path, found) == 1

    cmds.setAttr("knee.translateX", 1)
    assert items.unchanged_since(path, found) is None
    assert items.publish_data(path, found, "Moved the knee") == 2
    assert versions.list_versions(path)[-1].description == "Moved the knee"
    assert cmds.ls(selection=True) == []  # the selection doesn't change


def test_saved_objects_names_the_missing_ones(tmp_path, new_scene):
    path = logic.create_data_item(items.JOINTS, str(tmp_path), "skeleton", _long(_chain()[0]))
    cmds.delete("knee")  # ankle goes with it
    assert items.saved_objects(path) == (["|hip"], ["Missing in the scene: knee, ankle"])


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


def _selected(*names):
    return {"type": items.SELECTED, "value": list(names)}


def test_new_selection_item_saves_the_selection_as_one_selected_entry(tmp_path, new_scene):
    a = cmds.createNode("transform", name="body_geo")
    b = cmds.createNode("transform", name="hair_geo")

    path = logic.create_selection_item(str(tmp_path), "hero", [a, b])

    assert path == os.path.join(str(tmp_path), "hero.sel")
    assert items.read_entries(path) == [_selected("body_geo", "hair_geo")]
    [entry] = logic.scan(str(tmp_path))
    assert (entry.kind, entry.type_label) == (items.SELECTION, "Selection")
    assert not versions.is_versioned(path)


def test_new_selection_item_with_nothing_selected_starts_empty(tmp_path, new_scene):
    path = logic.create_selection_item(str(tmp_path), "hero", [])
    assert items.read_entries(path) == []


def test_entries_round_trip(tmp_path):
    path = logic.create_selection_item(str(tmp_path), "hero", [])
    entries = [
        _selected("body_geo", "hair_geo"),
        {"type": items.PATTERN, "value": "*_geo"},
        {"type": items.SET, "value": "render_set"},
    ]
    items.write_entries(path, entries)
    assert items.read_entries(path) == entries


def test_add_selected_adds_one_entry_for_all_the_names():
    entries = [_selected("a")]
    assert items.add_selected(entries, ["b", "a", "c", "b"]) == [_selected("a"), _selected("b", "a", "c")]
    assert items.add_selected(entries, []) == [_selected("a")]


def test_selected_names_are_the_shortest_unique_ones(new_scene):
    for group in ("L_arm", "R_arm"):
        cmds.createNode("transform", name="hand_geo", parent=cmds.createNode("transform", name=group))
    cmds.createNode("transform", name="body_geo")
    cmds.select("body_geo", "|L_arm|hand_geo")

    assert items.selected_names() == ["body_geo", "L_arm|hand_geo"]


def test_selected_entry_finds_its_objects_and_components_in_order(new_scene):
    cmds.polyCube(name="body_geo")
    cmds.createNode("transform", name="a_geo")
    entry = _selected("body_geo", "body_geo.f[0:2]", "a_geo", "gone")
    assert items.find(entry) == ["body_geo", "body_geo.f[0:2]", "a_geo"]
    assert items.missing(entry) == ["gone"]


def test_selected_entry_still_finds_an_object_after_reparenting(new_scene):
    node = cmds.createNode("transform", name="body_geo")
    cmds.parent(node, cmds.createNode("transform", name="grp"))
    assert items.find(_selected("body_geo")) == ["body_geo"]


def test_pattern_entry_uses_maya_wildcards(new_scene):
    for name in ("body_geo", "hair_geo", "body_ctl"):
        cmds.createNode("transform", name=name)
    assert sorted(items.find({"type": items.PATTERN, "value": "*_geo"})) == ["body_geo", "hair_geo"]
    assert sorted(items.find({"type": items.PATTERN, "value": "body_* hair_?eo"})) == [
        "body_ctl",
        "body_geo",
        "hair_geo",
    ]
    nothing = {"type": items.PATTERN, "value": "*_nothing"}
    assert items.find(nothing) == []
    assert items.missing(nothing) == ["*_nothing"]


def test_set_entry_expands_nested_sets(new_scene):
    a, b, c = (cmds.createNode("transform", name=n) for n in ("a", "b", "c"))
    inner = cmds.sets(b, c, name="inner_set")
    cmds.sets(a, inner, name="outer_set")

    assert sorted(items.find({"type": items.SET, "value": "outer_set"})) == ["a", "b", "c"]
    assert items.find({"type": items.SET, "value": "missing_set"}) == []
    assert items.missing({"type": items.SET, "value": "missing_set"}) == ["set: missing_set"]
    assert items.find({"type": items.SET, "value": "a"}) == []


def test_set_entry_keeps_components(new_scene):
    cube = cmds.polyCube(name="body_geo")[0]
    cmds.sets(f"{cube}.f[0:1]", name="faces_set")
    assert items.find({"type": items.SET, "value": "faces_set"}) == ["body_geo.f[0:1]"]


def test_resolve_combines_in_entry_order_without_repeats(new_scene):
    for name in ("c_geo", "a_geo", "b_geo"):
        cmds.createNode("transform", name=name)
    entries = [_selected("c_geo"), {"type": items.PATTERN, "value": "*_geo"}, _selected("a_geo")]

    objects, missing = items.resolve(entries)

    assert objects[0] == "c_geo"
    assert sorted(objects) == ["a_geo", "b_geo", "c_geo"]
    assert missing == []


def test_resolve_reports_what_is_missing(new_scene):
    cmds.createNode("transform", name="a_geo")
    entries = [_selected("a_geo", "gone"), {"type": items.SET, "value": "no_set"}]
    assert items.resolve(entries) == (["a_geo"], ["gone", "set: no_set"])


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


def test_selection_item_fails_naming_what_is_missing(tmp_path, new_scene):
    cmds.createNode("transform", name="here")
    path = logic.create_selection_item(str(tmp_path), "hero", ["here"])
    items.write_entries(path, [_selected("here", "gone"), {"type": items.SET, "value": "no_set"}])
    cmds.select(clear=True)
    runner = logic.Runner()

    assert runner.run([path]) == logic.FAILED
    message = runner.status(path)[1]
    assert "gone" in message and "set: no_set" in message and "here" not in message
    assert cmds.ls(selection=True) == []


def test_empty_selection_item_fails(tmp_path, new_scene):
    path = logic.create_selection_item(str(tmp_path), "hero", [])
    runner = logic.Runner()
    assert runner.run([path]) == logic.FAILED
    assert "no entries" in runner.status(path)[1].lower()


def test_entry_labels():
    assert items.entry_label(_selected("body_geo", "hair_geo")) == "body_geo, hair_geo"
    assert items.entry_label({"type": items.PATTERN, "value": "*_geo"}) == "*_geo"
    assert items.entry_label({"type": items.SET, "value": "render_set"}) == "set: render_set"


def test_summary_lists_the_entries_names(tmp_path):
    entries = [
        _selected("body_geo", "hair_geo"),
        {"type": items.PATTERN, "value": "*_eye_geo"},
        {"type": items.SET, "value": "render_set"},
    ]
    assert items.summary(entries) == "body_geo, hair_geo, *_eye_geo, set: render_set"
    assert items.summary([]) == "No entries. Double-click to add some."
    many = [_selected(*(f"n{i}" for i in range(12)))]
    assert items.summary(many).endswith("n9 ...and 2 more")


def test_scene_sets_lists_selection_sets_only(new_scene):
    cmds.sets(cmds.createNode("transform"), name="render_set")
    cmds.sets(name="empty_set", empty=True)
    assert items.scene_sets() == ["empty_set", "render_set"]


def test_entries_skip_intermediate_objects(new_scene):
    cube = cmds.polyCube(name="body_geo")[0]
    orig = cmds.createNode("mesh", name="body_geoShapeOrig", parent=cube)
    cmds.setAttr(f"{orig}.intermediateObject", True)
    cmds.sets(cube, orig, name="geo_set")

    assert items.find({"type": items.PATTERN, "value": "body_geoShape*"}) == ["body_geoShape"]
    assert items.find({"type": items.SET, "value": "geo_set"}) == ["body_geo"]
    assert items.find(_selected("body_geoShapeOrig")) == []


def _pattern(value, node_type=None):
    entry = {"type": items.PATTERN, "value": value}
    if node_type:
        entry["node_type"] = node_type
    return entry


def test_pattern_node_types_offered():
    assert items.NODE_TYPES[0] == "*"
    assert {"Transform", "Joint", "Geo", "Nurbs Curve", "Nurbs Surface", "Locator", "Constraint"} <= set(
        items.NODE_TYPES
    )


def test_pattern_node_type_filters_what_it_finds(new_scene):
    cmds.polyCube(name="body_x")
    cmds.circle(name="ctrl_x")
    cmds.nurbsPlane(name="plane_x")
    cmds.spaceLocator(name="loc_x")
    cmds.createNode("transform", name="grp_x")
    cmds.select(clear=True)
    cmds.joint(name="jnt_x")
    cmds.parentConstraint("loc_x", "grp_x", name="con_x")

    def found(node_type):
        return sorted(items.find(_pattern("*_x", node_type)))

    assert found(None) == found("*") == ["body_x", "con_x", "ctrl_x", "grp_x", "jnt_x", "loc_x", "plane_x"]
    assert found("Geo") == ["body_x"]
    assert found("Nurbs Curve") == ["ctrl_x"]
    assert found("Nurbs Surface") == ["plane_x"]
    assert found("Locator") == ["loc_x"]
    assert found("Joint") == ["jnt_x"]
    assert found("Constraint") == ["con_x"]
    # Plain transforms: groups and transforms with shapes, not joints or constraints.
    assert found("Transform") == ["body_x", "ctrl_x", "grp_x", "loc_x", "plane_x"]


def test_geo_ignores_intermediate_shapes(new_scene):
    group = cmds.createNode("transform", name="only_orig_geo")
    orig = cmds.createNode("mesh", name="only_orig_geoShapeOrig", parent=group)
    cmds.setAttr(f"{orig}.intermediateObject", True)
    assert items.find(_pattern("*_geo", "Geo")) == []


def test_pattern_with_a_node_type_reads_with_it():
    assert items.entry_label(_pattern("*_geo", "Geo")) == "*_geo (Geo)"
    assert items.entry_label(_pattern("*_geo", "*")) == "*_geo"
    assert items.entry_label(_pattern("*_geo")) == "*_geo"
    assert items.missing(_pattern("*_none", "Joint")) == ["*_none (Joint)"]


def test_create_set_makes_a_selection_set_as_one_undo_step(new_scene):
    a = cmds.createNode("transform", name="a_geo")
    b = cmds.createNode("transform", name="b_geo")
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    name = items.create_set("render_set", [a, b])

    assert name == "render_set"
    assert name in items.scene_sets()
    assert sorted(items.find({"type": items.SET, "value": name})) == ["a_geo", "b_geo"]
    cmds.undo()
    assert not cmds.objExists("render_set")


def test_create_set_returns_the_name_maya_gave_it(new_scene):
    a = cmds.createNode("transform", name="a_geo")
    cmds.sets(a, name="render_set")
    assert items.create_set("render_set", [a]) == "render_set1"


def test_create_set_needs_a_name_and_a_selection(new_scene):
    a = cmds.createNode("transform", name="a_geo")
    with pytest.raises(ValueError, match="Nothing selected"):
        items.create_set("render_set", [])
    with pytest.raises(ValueError, match="name"):
        items.create_set("  ", [a])
    assert items.scene_sets() == []


def test_delete_set_keeps_its_members_as_one_undo_step(new_scene):
    a = cmds.createNode("transform", name="a_geo")
    cmds.sets(a, name="render_set")
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    items.delete_set("render_set")

    assert not cmds.objExists("render_set") and cmds.objExists("a_geo")
    cmds.undo()
    assert items.find({"type": items.SET, "value": "render_set"}) == ["a_geo"]


def test_delete_set_only_deletes_selection_sets(new_scene):
    cmds.createNode("transform", name="a_geo")
    with pytest.raises(ValueError, match="Not a selection set"):
        items.delete_set("a_geo")
    with pytest.raises(ValueError, match="Not a selection set"):
        items.delete_set("initialShadingGroup")
    assert cmds.objExists("a_geo")


# -- double-click opens the datatype's tool ----------------------------------


def _skin_item(tmp_path):
    joints = _chain()
    mesh = cmds.polyCylinder(name="leg", height=4, subdivisionsY=4, constructionHistory=False)[0]
    cmds.skinCluster(*joints, mesh, toSelectedBones=True, name="leg_skin")
    return logic.create_data_item(items.SKIN, str(tmp_path), "leg", _long(mesh))


def test_skin_items_open_the_skincluster_tool():
    from kaiju_suite import registry

    assert items.tool_for(items.SKIN) == "SkinCluster Tool"
    assert registry.find(items.tool_for(items.SKIN)) is not None


def test_joints_items_open_the_joint_tool():
    from kaiju_suite import registry

    assert items.tool_for(items.JOINTS) == "Joint Tool"
    assert registry.find(items.tool_for(items.JOINTS)) is not None


def test_mesh_items_open_the_mesh_tool():
    from kaiju_suite import registry

    assert items.tool_for(items.MESH) == "Mesh Tool"
    assert registry.find(items.tool_for(items.MESH)) is not None


def test_kinds_without_a_tool_have_none():
    for kind in (items.SCRIPT, items.SELECTION):
        assert items.tool_for(kind) is None


def test_open_in_tool_selects_the_saved_objects_then_launches_the_tool(tmp_path, new_scene, monkeypatch):
    from kaiju_suite import registry

    path = _skin_item(tmp_path)
    cmds.select(clear=True)
    calls = []
    monkeypatch.setattr(
        registry, "find", lambda name: {"name": name, "launch": lambda: calls.append((name, cmds.ls(selection=True)))}
    )

    message = items.open_in_tool(path)

    assert calls == [("SkinCluster Tool", ["leg"])]
    assert message == "Selected 1 object from leg.skin"


def test_open_in_tool_still_launches_when_the_objects_are_gone(tmp_path, new_scene, monkeypatch):
    from kaiju_suite import registry

    path = _skin_item(tmp_path)
    cmds.delete("leg")
    calls = []
    monkeypatch.setattr(registry, "find", lambda name: {"name": name, "launch": lambda: calls.append(name)})

    message = items.open_in_tool(path)

    assert calls == ["SkinCluster Tool"]
    assert "Missing in the scene: leg" in message


def test_open_in_tool_says_when_the_tool_is_missing(tmp_path, new_scene, monkeypatch):
    from kaiju_suite import registry

    path = _skin_item(tmp_path)
    monkeypatch.setattr(registry, "find", lambda name: None)

    with pytest.raises(LookupError, match="SkinCluster Tool"):
        items.open_in_tool(path)


# -- QC before publishing ----------------------------------------------------


def test_publish_qc_runs_the_skin_checks_on_the_objects(tmp_path, new_scene):
    path = _skin_item(tmp_path)

    found = items.publish_qc(path, _long("leg"))

    assert [check.key for check, _ in found] == ["skinned", "normalized", "influence_count", "small_weights", "unused"]


def test_publish_qc_of_a_mesh_leaves_out_uvs_and_symmetry(tmp_path, new_scene):
    cube = cmds.polyCube(name="box", constructionHistory=False)[0]
    path = logic.create_data_item(items.MESH, str(tmp_path), "body", _long(cube))

    keys = [check.key for check, _ in items.publish_qc(path, _long(cube))]

    assert "uvs" not in keys and "symmetry" not in keys
    assert "ngons" in keys and "history" in keys


def test_publish_qc_runs_the_joint_checks_on_the_joints(tmp_path, new_scene):
    hip = _chain()[0]
    path = logic.create_data_item(items.JOINTS, str(tmp_path), "skeleton", _long(hip))
    cmds.setAttr(f"{hip}.rotateX", 30)

    found = dict((check.key, problems) for check, problems in items.publish_qc(path, _long(hip)))

    assert found["rotate"] == ["hip: rotate is (30, 0, 0)"]


# -- ControlShape items ------------------------------------------------------


def _controlshape_ctrl(name="ctrl", color=17):
    node = cmds.rename(cmds.circle(normal=(0, 1, 0), constructionHistory=False)[0], name)
    shape = cmds.rename(cmds.listRelatives(node, shapes=True, fullPath=True)[0], f"{name}Shape")
    if color:
        cmds.setAttr(f"{node}|{shape}.overrideEnabled", True)
        cmds.setAttr(f"{node}|{shape}.overrideColor", color)
    return node


def test_new_controlshape_item_publishes_the_selection_as_v001(tmp_path, new_scene):
    ctrl = _controlshape_ctrl()

    path = logic.create_data_item(items.CONTROLSHAPE, str(tmp_path), "ctrls", _long(ctrl))

    assert path == os.path.join(str(tmp_path), "ctrls.ctrl")
    assert versions.is_versioned(path) and versions.label(path) == "v001"
    assert items.describe(path) == ["1 control", "1 curve shape", "Controls: ctrl"]
    [entry] = logic.scan(str(tmp_path))
    assert (entry.kind, entry.type_label) == (items.CONTROLSHAPE, "ControlShape")
    assert items.CONTROLSHAPE in items.RUNNABLE


def test_running_a_controlshape_item_replaces_the_shapes_as_one_undo_step(tmp_path, new_scene):
    ctrl = _controlshape_ctrl()
    path = logic.create_data_item(items.CONTROLSHAPE, str(tmp_path), "ctrls", _long(ctrl))
    cmds.delete(cmds.listRelatives(ctrl, shapes=True, fullPath=True))
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    assert logic.Runner().run([path]) == logic.DONE
    assert cmds.listRelatives(ctrl, shapes=True) == ["ctrlShape"]

    cmds.undo()
    assert not cmds.listRelatives(ctrl, shapes=True)


def test_new_controlshape_item_needs_curve_shapes(tmp_path, new_scene):
    bare = cmds.createNode("transform", name="bare")
    with pytest.raises(ValueError, match="bare"):
        logic.create_data_item(items.CONTROLSHAPE, str(tmp_path), "ctrls", _long(bare))
    assert logic.scan(str(tmp_path)) == []


def test_select_saved_selects_the_controls(tmp_path, new_scene):
    path = logic.create_data_item(items.CONTROLSHAPE, str(tmp_path), "ctrls", _long(_controlshape_ctrl()))
    cmds.select(clear=True)

    assert items.select_saved(path) == "Selected 1 object from ctrls.ctrl"
    assert cmds.ls(selection=True) == ["ctrl"]


def test_controlshape_items_open_the_controlshape_tool():
    from kaiju_suite import registry

    assert items.tool_for(items.CONTROLSHAPE) == "ControlShape Tool"
    assert registry.find(items.tool_for(items.CONTROLSHAPE)) is not None


def test_publish_qc_runs_the_controlshape_checks_on_the_controls(tmp_path, new_scene):
    ctrl = _controlshape_ctrl()
    path = logic.create_data_item(items.CONTROLSHAPE, str(tmp_path), "ctrls", _long(ctrl))
    plain = _controlshape_ctrl("plain", color=0)

    found = dict((check.key, problems) for check, problems in items.publish_qc(path, _long([ctrl, plain])))

    assert list(found) == ["no_shapes", "shape_names", "color", "duplicate_names", "rational"]
    assert found["color"] == ["plain: no color"]
