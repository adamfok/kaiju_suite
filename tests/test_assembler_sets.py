import os

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import data, logic, products, runlog, versions
from kaiju_suite.tools.assembler.products import sets


def _scene():
    """Two controls, a mesh, an animator set with a nested set, an export set
    and a templated, hidden display layer."""
    grp = cmds.createNode("transform", name="rig_grp", skipSelect=True)
    arm = cmds.createNode("transform", name="arm_ctrl", parent=grp, skipSelect=True)
    leg = cmds.createNode("transform", name="leg_ctrl", parent=grp, skipSelect=True)
    body = cmds.polyCube(name="body", constructionHistory=False)[0]
    arms = cmds.sets(arm, name="arms_set")
    cmds.sets(leg, name="legs_set")
    controls = cmds.sets(["arms_set", "legs_set"], name="controls_set")
    export = cmds.sets([body, "rig_grp"], name="export_set")
    layer = cmds.createDisplayLayer([body], name="geo_layer", noRecurse=True)
    cmds.setAttr(f"{layer}.displayType", 2)
    cmds.setAttr(f"{layer}.visibility", False)
    cmds.select(clear=True)
    return {"arms": arms, "controls": controls, "export": export, "layer": layer}


def _publish(tmp_path, *selection, name="sets"):
    path = sets.PRODUCT.create(str(tmp_path), name)
    cmds.select(selection, noExpand=True)
    message = versions.publish_action(path).fn()
    return path, message


def _members(node):
    return sorted(cmds.ls(cmds.sets(node, query=True) or []))


def _layer_members(layer):
    return sorted(cmds.ls(cmds.editDisplayLayerMembers(layer, query=True, fullNames=True) or []))


def _delete_sets_and_layers():
    cmds.delete(cmds.ls(["controls_set", "arms_set", "legs_set", "export_set", "geo_layer"]))


def _check_rebuilt():
    assert cmds.nodeType("controls_set") == "objectSet"
    assert _members("controls_set") == ["arms_set", "legs_set"]
    assert _members("arms_set") == ["arm_ctrl"]
    assert _members("legs_set") == ["leg_ctrl"]
    assert _members("export_set") == ["body", "rig_grp"]
    assert cmds.nodeType("geo_layer") == "displayLayer"
    assert _layer_members("geo_layer") == ["body"]
    assert cmds.getAttr("geo_layer.displayType") == 2
    assert cmds.getAttr("geo_layer.visibility") is False


# -- product ----------------------------------------------------------------


def test_sets_is_discovered_and_owns_sets(tmp_path):
    assert sets.PRODUCT in products.discover()
    assert sets.PRODUCT.name == "Sets & Layers"
    assert sets.PRODUCT.extensions == (".sets",)
    assert sets.PRODUCT.runnable and sets.PRODUCT.versioned
    assert sets.PRODUCT.menu_slot is not None
    path = sets.PRODUCT.creators[0].fn(str(tmp_path), "anim", None)
    assert path == str(tmp_path / "anim.sets") and os.path.getsize(path) == 0
    assert products.product_for(path) is sets.PRODUCT


# -- publish ----------------------------------------------------------------


def test_publish_saves_nested_sets_and_layers(new_scene, tmp_path):
    _scene()
    path, message = _publish(tmp_path, "controls_set", "export_set", "geo_layer")
    assert message == "Published Sets & Layers sets.sets v001"

    payload = data.read(path, "sets")
    saved = {s["name"]: s["members"] for s in payload["sets"]}
    assert list(saved) == ["controls_set", "arms_set", "legs_set", "export_set"]
    assert saved["controls_set"] == ["arms_set", "legs_set"]
    assert saved["export_set"] == ["body", "rig_grp"]
    (layer,) = payload["layers"]
    assert layer["name"] == "geo_layer"
    assert layer["members"] == ["body"]
    assert layer["displayType"] == 2
    assert layer["visibility"] is False


def test_publish_problems(new_scene, tmp_path):
    _scene()
    path = sets.PRODUCT.create(str(tmp_path), "anim")
    cmds.select(clear=True)
    (problem,) = versions.publish_problems(path)
    assert "Nothing selected" in problem

    cmds.select("arm_ctrl")
    (problem,) = versions.publish_problems(path)
    assert "No sets or display layers selected" in problem

    cmds.select("arms_set", noExpand=True)
    assert versions.publish_problems(path) == []


def test_shading_groups_are_not_sets(new_scene, tmp_path):
    _scene()
    path = sets.PRODUCT.create(str(tmp_path), "anim")
    cmds.select("initialShadingGroup", noExpand=True)
    (problem,) = versions.publish_problems(path)
    assert "No sets or display layers selected" in problem


def test_republishing_adds_a_version_only_on_change(new_scene, tmp_path):
    _scene()
    path, message = _publish(tmp_path, "controls_set")
    assert message.endswith("v001")
    cmds.select("controls_set", noExpand=True)
    assert versions.publish_action(path).fn().endswith("v001")
    cmds.sets("body", add="arms_set")
    cmds.select("controls_set", noExpand=True)
    assert versions.publish_action(path).fn().endswith("v002")


# -- run --------------------------------------------------------------------


def test_round_trip_into_a_new_scene(new_scene, tmp_path):
    _scene()
    path, _ = _publish(tmp_path, "controls_set", "export_set", "geo_layer")
    _delete_sets_and_layers()
    assert not cmds.objExists("controls_set")

    with runlog.capture() as run:
        message = sets.PRODUCT.run(path)
    assert run.warnings == []
    assert message == "Created 4 sets and 1 display layer"
    _check_rebuilt()


def test_round_trip_via_run_steps(new_scene, tmp_path):
    _scene()
    path, _ = _publish(tmp_path, "controls_set", "export_set", "geo_layer")
    _delete_sets_and_layers()
    logic.run_steps([path])
    _check_rebuilt()


def test_existing_set_and_layer_are_reused_and_members_added(new_scene, tmp_path):
    _scene()
    path, _ = _publish(tmp_path, "arms_set", "geo_layer")
    cmds.sets("arm_ctrl", remove="arms_set")
    cmds.sets("leg_ctrl", add="arms_set")
    cmds.editDisplayLayerMembers("defaultLayer", "body", noRecurse=True)
    cmds.setAttr("geo_layer.displayType", 0)

    message = sets.PRODUCT.run(path)
    assert message == "Updated 1 set and 1 display layer"
    assert _members("arms_set") == ["arm_ctrl", "leg_ctrl"]
    assert _layer_members("geo_layer") == ["body"]
    assert cmds.getAttr("geo_layer.displayType") == 2
    assert cmds.ls("arms_set*", type="objectSet") == ["arms_set"]
    assert cmds.ls("geo_layer*", type="displayLayer") == ["geo_layer"]


def test_running_twice_changes_nothing(new_scene, tmp_path):
    _scene()
    path, _ = _publish(tmp_path, "controls_set", "export_set", "geo_layer")
    _delete_sets_and_layers()
    sets.PRODUCT.run(path)
    sets.PRODUCT.run(path)
    _check_rebuilt()
    assert sorted(cmds.ls("*_set*", type="objectSet")) == ["arms_set", "controls_set", "export_set", "legs_set"]
    assert cmds.ls("geo_layer*", type="displayLayer") == ["geo_layer"]


def test_missing_members_are_skipped_with_one_warning(new_scene, tmp_path):
    _scene()
    path, _ = _publish(tmp_path, "controls_set", "export_set", "geo_layer")
    _delete_sets_and_layers()
    cmds.delete("arm_ctrl", "body")

    with runlog.capture() as run:
        sets.PRODUCT.run(path)
    assert run.warnings == ["Skipped missing members: arm_ctrl, body"]
    assert _members("arms_set") == []
    assert _members("legs_set") == ["leg_ctrl"]
    assert _members("export_set") == ["rig_grp"]
    assert _layer_members("geo_layer") == []
    assert cmds.getAttr("geo_layer.displayType") == 2


def test_ambiguous_member_raises_and_changes_nothing(new_scene, tmp_path):
    _scene()
    path, _ = _publish(tmp_path, "controls_set", "geo_layer")
    _delete_sets_and_layers()
    other = cmds.createNode("transform", name="other_grp", skipSelect=True)
    cmds.createNode("transform", name="arm_ctrl", parent=other, skipSelect=True)
    before = sorted(cmds.ls(type=("objectSet", "displayLayer")))

    with pytest.raises(RuntimeError) as info:
        sets.PRODUCT.run(path)
    assert "arm_ctrl" in str(info.value)
    assert sorted(cmds.ls(type=("objectSet", "displayLayer"))) == before


def test_name_used_by_another_node_type_raises_and_changes_nothing(new_scene, tmp_path):
    _scene()
    path, _ = _publish(tmp_path, "controls_set", "geo_layer")
    _delete_sets_and_layers()
    cmds.createNode("transform", name="legs_set", skipSelect=True)
    before = sorted(cmds.ls(type=("objectSet", "displayLayer")))

    with pytest.raises(RuntimeError) as info:
        sets.PRODUCT.run(path)
    assert "legs_set" in str(info.value)
    assert sorted(cmds.ls(type=("objectSet", "displayLayer"))) == before


def test_empty_file_is_skipped(new_scene, tmp_path):
    path = sets.PRODUCT.create(str(tmp_path), "anim")
    assert logic.run_steps([path]) == [path]


def test_one_undo_reverts_a_run(new_scene, tmp_path):
    _scene()
    path, _ = _publish(tmp_path, "controls_set", "export_set", "geo_layer")
    _delete_sets_and_layers()
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    sets.PRODUCT.run(path)
    assert cmds.objExists("controls_set") and cmds.objExists("geo_layer")
    cmds.undo()
    for name in ("controls_set", "arms_set", "legs_set", "export_set", "geo_layer"):
        assert not cmds.objExists(name)


def test_panel_describes_the_file(new_scene, tmp_path):
    _scene()
    path, _ = _publish(tmp_path, "controls_set", "export_set", "geo_layer")
    assert sets.PRODUCT.panel(path).info == [
        "4 sets",
        "1 display layer",
        "Sets: controls_set, arms_set, legs_set, export_set",
        "Display layers: geo_layer",
    ]
