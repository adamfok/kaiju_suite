import os

import pytest
from maya import cmds, mel

from kaiju_suite.tools.assembler import data, logic, products, runlog, versions
from kaiju_suite.tools.assembler.products import wrap

WRAP_SETTINGS = {
    "weightThreshold": 0.1,
    "maxDistance": 2.5,
    "autoWeightThreshold": False,
    "exclusiveBind": False,
    "falloffMode": 1,
    "envelope": 0.9,
}
PROXIMITY_SETTINGS = {
    "wrapMode": 0,
    "falloffScale": 1.5,
    "smoothNormals": 2,
    "envelope": 0.8,
}
DRIVER_SETTINGS = {
    "driverFalloffStart": 0.05,
    "driverFalloffEnd": 2.0,
    "driverStrength": 0.7,
}
PAINTED = {3: 0.25, 10: 0.0}


def _body(name="body"):
    """A low sphere (radius 1, no history): the driver."""
    return cmds.polySphere(name=name, radius=1, sx=8, sy=8, ch=False)[0]


def _cloth(name="shirt", radius=1.1):
    """A cylinder around the body (24 vertices, no history): the driven mesh."""
    return cmds.polyCylinder(name=name, radius=radius, height=1, sx=8, sy=2, ch=False)[0]


def _shape(transform):
    return cmds.listRelatives(transform, shapes=True, noIntermediate=True, fullPath=True)[0]


def _wrap(driven, driver, name="shirt_wrap", settings=WRAP_SETTINGS, dropoff=6.0):
    """A wrap made the way Maya's Create Wrap menu makes it."""
    cmds.select(driven, driver)
    mel.eval('doWrapArgList "7" { "1","0","1", "2", "1", "1", "0", "0" }')
    node = cmds.rename(cmds.ls(cmds.listHistory(driven), type="wrap")[0], name)
    for attr, value in settings.items():
        cmds.setAttr(f"{node}.{attr}", value)
    cmds.setAttr(f"{driver}.dropoff", dropoff)
    cmds.select(clear=True)
    return node


def _proximity(driven, driver, name="shirt_pwrap", settings=PROXIMITY_SETTINGS, driver_settings=DRIVER_SETTINGS,
               painted=PAINTED):
    node = cmds.proximityWrap(driven, name=name)[0]
    cmds.proximityWrap(node, edit=True, addDrivers=[_shape(driver)])
    for attr, value in settings.items():
        cmds.setAttr(f"{node}.{attr}", value)
    for attr, value in driver_settings.items():
        cmds.setAttr(f"{node}.drivers[0].{attr}", value)
    for vertex, weight in painted.items():
        cmds.setAttr(f"{node}.weightList[0].weights[{vertex}]", weight)
    return node


def _deformers(mesh):
    """The mesh's deformers, last evaluated first."""
    return cmds.ls(cmds.listHistory(mesh), type="geometryFilter")


def _points(mesh):
    flat = cmds.xform(f"{mesh}.vtx[*]", query=True, worldSpace=True, translation=True)
    return [round(v, 4) for v in flat]


def _weights(node, mesh):
    return [round(w, 5) for w in cmds.percent(node, f"{mesh}.vtx[*]", query=True, value=True)]


def _publish(tmp_path, *selection, name="wrap"):
    path = wrap.PRODUCT.create(str(tmp_path), name)
    cmds.select(selection)
    message = versions.publish_action(path).fn()
    return path, message


def _records(path):
    return {r["name"]: r for r in data.read(path, "wrap")["deformers"]}


# -- product ----------------------------------------------------------------


def test_wrap_is_discovered_and_owns_wrap(tmp_path):
    assert wrap.PRODUCT in products.discover()
    assert wrap.PRODUCT.name == "Wrap"
    assert wrap.PRODUCT.kind == "wrap"
    assert wrap.PRODUCT.extensions == (".wrap",)
    assert wrap.PRODUCT.runnable and wrap.PRODUCT.versioned
    assert wrap.PRODUCT.utility == "Wrap Tool"
    path = wrap.PRODUCT.creators[0].fn(str(tmp_path), "clothes", None)
    assert path == str(tmp_path / "clothes.wrap") and os.path.getsize(path) == 0
    assert products.product_for(path) is wrap.PRODUCT


# -- publish ----------------------------------------------------------------


def test_publish_saves_a_wrap_its_driver_and_settings(new_scene, tmp_path):
    body = _body()
    shirt = _cloth()
    _wrap(shirt, body)
    path, message = _publish(tmp_path, shirt)
    assert message == "Published Wrap wrap.wrap v001"

    record = _records(path)["shirt_wrap"]
    assert record["type"] == "wrap"
    assert [m["mesh"] for m in record["meshes"]] == ["shirt"]
    assert record["meshes"][0]["vertex_count"] == 24
    assert [d["mesh"] for d in record["drivers"]] == ["body"]
    assert record["drivers"][0]["dropoff"] == pytest.approx(6.0)
    assert record["drivers"][0]["inflType"] == 2
    for attr, value in WRAP_SETTINGS.items():
        assert record["settings"][attr] == pytest.approx(value)


def test_publish_saves_a_proximity_wrap_with_driver_settings_and_weights(new_scene, tmp_path):
    body = _body()
    shirt = _cloth()
    _proximity(shirt, body)
    path, _ = _publish(tmp_path, shirt)

    record = _records(path)["shirt_pwrap"]
    assert record["type"] == "proximityWrap"
    assert [d["mesh"] for d in record["drivers"]] == ["body"]
    for attr, value in DRIVER_SETTINGS.items():
        assert record["drivers"][0][attr] == pytest.approx(value)
    for attr, value in PROXIMITY_SETTINGS.items():
        assert record["settings"][attr] == pytest.approx(value)
    assert sorted(map(tuple, record["meshes"][0]["weights"])) == sorted(PAINTED.items())


def test_publish_saves_every_wrap_on_each_mesh_but_not_the_drivers(new_scene, tmp_path):
    body = _body()
    shirt = _cloth("shirt", 1.1)
    coat = _cloth("coat", 1.3)
    _wrap(shirt, body, "shirt_wrap")
    _proximity(coat, body, "coat_pwrap")
    # The body is in the coat's history, but its deformers aren't saved.
    path, _ = _publish(tmp_path, shirt, coat)
    assert sorted(_records(path)) == ["coat_pwrap", "shirt_wrap"]


def test_publish_saves_several_drivers(new_scene, tmp_path):
    body = _body("body")
    arm = _body("arm")
    cmds.move(2, 0, 0, arm)
    shirt = _cloth()
    node = _proximity(shirt, body, painted={})
    cmds.proximityWrap(node, edit=True, addDrivers=[_shape(arm)])
    path, _ = _publish(tmp_path, shirt)
    assert sorted(d["mesh"] for d in _records(path)["shirt_pwrap"]["drivers"]) == ["arm", "body"]


# -- run --------------------------------------------------------------------


@pytest.mark.parametrize("make", [_wrap, _proximity])
def test_round_trip_follows_the_driver(new_scene, tmp_path, make):
    body = _body()
    shirt = _cloth()
    node_type = cmds.nodeType(make(shirt, body, name="shirt_def"))
    path, _ = _publish(tmp_path, shirt)
    rest = _points(shirt)
    cmds.setAttr(f"{body}.translateY", 0.5)
    cmds.setAttr(f"{body}.rotateZ", 20)
    expected = _points(shirt)
    assert expected != pytest.approx(rest, abs=1e-2)  # the shirt follows the body

    cmds.file(new=True, force=True)
    body = _body()
    shirt = _cloth()
    logic.run_steps([path])
    assert _deformers(shirt) == ["shirt_def"]
    assert cmds.nodeType("shirt_def") == node_type
    cmds.setAttr(f"{body}.translateY", 0.5)
    cmds.setAttr(f"{body}.rotateZ", 20)
    assert _points(shirt) == pytest.approx(expected, abs=1e-3)


def test_run_restores_wrap_settings(new_scene, tmp_path):
    body = _body()
    shirt = _cloth()
    _wrap(shirt, body)
    path, _ = _publish(tmp_path, shirt)

    cmds.file(new=True, force=True)
    _body()
    shirt = _cloth()
    message = wrap.PRODUCT.run(path)
    assert "shirt_wrap" in message
    assert cmds.nodeType("shirt_wrap") == "wrap"
    for attr, value in WRAP_SETTINGS.items():
        assert cmds.getAttr(f"shirt_wrap.{attr}") == pytest.approx(value)
    assert cmds.getAttr("shirt_wrap.dropoff[0]") == pytest.approx(6.0)
    assert cmds.getAttr("shirt_wrap.inflType[0]") == 2


def test_run_restores_proximity_wrap_settings_and_weights(new_scene, tmp_path):
    body = _body()
    shirt = _cloth()
    _proximity(shirt, body)
    path, _ = _publish(tmp_path, shirt)

    cmds.file(new=True, force=True)
    _body()
    shirt = _cloth()
    wrap.PRODUCT.run(path)
    assert cmds.nodeType("shirt_pwrap") == "proximityWrap"
    for attr, value in PROXIMITY_SETTINGS.items():
        assert cmds.getAttr(f"shirt_pwrap.{attr}") == pytest.approx(value)
    for attr, value in DRIVER_SETTINGS.items():
        assert cmds.getAttr(f"shirt_pwrap.drivers[0].{attr}") == pytest.approx(value)
    expected = [1.0] * 24
    for vertex, weight in PAINTED.items():
        expected[vertex] = weight
    assert _weights("shirt_pwrap", shirt) == expected


def test_run_on_a_skinned_mesh_sits_on_top(new_scene, tmp_path):
    body = _body()
    shirt = _cloth()
    _proximity(shirt, body, painted={})
    path, _ = _publish(tmp_path, shirt)

    cmds.file(new=True, force=True)
    _body()
    shirt = _cloth()
    cmds.select(clear=True)
    cmds.joint(name="root_jnt")
    cmds.skinCluster("root_jnt", shirt, toSelectedBones=True, name="shirt_skin")
    wrap.PRODUCT.run(path)
    assert _deformers(shirt) == ["shirt_pwrap", "shirt_skin"]


def test_rerunning_replaces_the_same_named_node_without_leftovers(new_scene, tmp_path):
    body = _body()
    shirt = _cloth()
    coat = _cloth("coat", 1.3)
    _wrap(shirt, body)
    _proximity(coat, body, "coat_pwrap")
    path, _ = _publish(tmp_path, shirt, coat)
    cmds.setAttr("shirt_wrap.maxDistance", 9)

    wrap.PRODUCT.run(path)
    nodes = sorted(cmds.ls(dag=True))
    wrap.PRODUCT.run(path)
    assert sorted(cmds.ls(dag=True)) == nodes
    assert cmds.ls(type="wrap") == ["shirt_wrap"]
    assert cmds.ls(type="proximityWrap") == ["coat_pwrap"]
    assert cmds.getAttr("shirt_wrap.maxDistance") == pytest.approx(2.5)
    assert _deformers(shirt) == ["shirt_wrap"]


def test_other_wrap_nodes_are_left_alone(new_scene, tmp_path):
    body = _body()
    shirt = _cloth()
    _proximity(shirt, body)
    path, _ = _publish(tmp_path, shirt)
    cmds.delete("shirt_pwrap")
    _proximity(shirt, body, "keep_pwrap", painted={})
    wrap.PRODUCT.run(path)
    assert sorted(cmds.ls(type="proximityWrap")) == ["keep_pwrap", "shirt_pwrap"]


def test_missing_mesh_is_skipped_with_a_warning(new_scene, tmp_path):
    body = _body()
    shirt = _cloth("shirt")
    coat = _cloth("coat", 1.3)
    _wrap(shirt, body, "shirt_wrap")
    _proximity(coat, body, "coat_pwrap")
    path, _ = _publish(tmp_path, shirt, coat)

    cmds.file(new=True, force=True)
    _body()
    _cloth("shirt")
    with runlog.capture() as run:
        wrap.PRODUCT.run(path)
    assert run.warnings == ["Skipped missing meshes: coat"]
    assert cmds.ls(type="wrap") == ["shirt_wrap"]
    assert not cmds.ls(type="proximityWrap")


def test_missing_driver_skips_its_deformers_with_a_warning(new_scene, tmp_path):
    body = _body("body")
    head = _body("head")
    shirt = _cloth("shirt")
    hat = _cloth("hat")
    _wrap(shirt, body, "shirt_wrap")
    _proximity(hat, head, "hat_pwrap")
    path, _ = _publish(tmp_path, shirt, hat)

    cmds.file(new=True, force=True)
    _body("body")
    _cloth("shirt")
    _cloth("hat")
    with runlog.capture() as run:
        wrap.PRODUCT.run(path)
    assert run.warnings == ["Skipped missing drivers: head"]
    assert cmds.ls(type="wrap") == ["shirt_wrap"]
    assert not cmds.ls(type="proximityWrap")


def test_all_missing_is_a_warning_not_an_error(new_scene, tmp_path):
    _wrap(_cloth(), _body())
    path, _ = _publish(tmp_path, "shirt")
    cmds.file(new=True, force=True)
    with runlog.capture() as run:
        message = wrap.PRODUCT.run(path)
    assert run.warnings == ["Skipped missing meshes: shirt"]
    assert "no" in message.lower()
    assert not cmds.ls(type="wrap")


@pytest.mark.parametrize("duplicate", ["shirt", "body"])
def test_ambiguous_names_raise_and_change_nothing(new_scene, tmp_path, duplicate):
    body = _body()
    shirt = _cloth()
    _proximity(shirt, body)
    path, _ = _publish(tmp_path, shirt)

    cmds.file(new=True, force=True)
    body = _body()
    shirt = _cloth()
    _proximity(shirt, body, settings={"falloffScale": 3.0}, driver_settings={}, painted={})
    group = cmds.group(empty=True, name="grp")
    other = _body("other") if duplicate == "body" else _cloth("other")
    cmds.rename(cmds.parent(other, group)[0], duplicate)
    with pytest.raises(RuntimeError) as info:
        wrap.PRODUCT.run(path)
    assert duplicate in str(info.value)
    assert cmds.getAttr("shirt_pwrap.falloffScale") == pytest.approx(3.0)
    assert cmds.ls(type="proximityWrap") == ["shirt_pwrap"]


def test_vertex_count_mismatch_with_painted_weights_raises(new_scene, tmp_path):
    body = _body()
    shirt = _cloth()
    _proximity(shirt, body)
    path, _ = _publish(tmp_path, shirt)

    cmds.file(new=True, force=True)
    _body()
    cmds.polyCylinder(name="shirt", radius=1.1, height=1, sx=6, sy=1, ch=False)  # 12 vertices, not 24
    with pytest.raises(RuntimeError) as info:
        wrap.PRODUCT.run(path)
    assert "shirt" in str(info.value) and "24" in str(info.value) and "12" in str(info.value)
    assert not cmds.ls(type="proximityWrap")


def test_vertex_count_change_without_weights_rebinds(new_scene, tmp_path):
    # A wrap has no per-vertex data, so it binds whatever the topology.
    body = _body()
    shirt = _cloth()
    _wrap(shirt, body)
    path, _ = _publish(tmp_path, shirt)

    cmds.file(new=True, force=True)
    _body()
    cmds.polyCylinder(name="shirt", radius=1.1, height=1, sx=6, sy=1, ch=False)
    wrap.PRODUCT.run(path)
    assert cmds.ls(type="wrap") == ["shirt_wrap"]


def test_name_taken_by_another_node_raises_and_changes_nothing(new_scene, tmp_path):
    body = _body()
    shirt = _cloth()
    _wrap(shirt, body)
    path, _ = _publish(tmp_path, shirt)
    cmds.delete("shirt_wrap")
    cmds.createNode("transform", name="shirt_wrap")
    with pytest.raises(RuntimeError) as info:
        wrap.PRODUCT.run(path)
    assert "shirt_wrap" in str(info.value)
    assert not cmds.ls(type="wrap")


def test_empty_file_is_skipped(new_scene, tmp_path):
    path = wrap.PRODUCT.create(str(tmp_path), "wrap")
    _cloth()
    assert logic.run_steps([path]) == [path]
    assert not cmds.ls(type=["wrap", "proximityWrap"])


@pytest.mark.parametrize("make", [_wrap, _proximity])
def test_one_undo_reverts_a_fresh_run(new_scene, tmp_path, make):
    body = _body()
    shirt = _cloth()
    make(shirt, body, name="shirt_def")
    path, _ = _publish(tmp_path, shirt)
    cmds.file(new=True, force=True)
    _body()
    shirt = _cloth()
    nodes = sorted(cmds.ls())
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    wrap.PRODUCT.run(path)
    assert _deformers(shirt) == ["shirt_def"]
    cmds.undo()
    assert not _deformers(shirt)
    assert sorted(cmds.ls()) == nodes


@pytest.mark.parametrize("make", [_wrap, _proximity])
def test_one_undo_reverts_a_replacing_run(new_scene, tmp_path, make):
    body = _body()
    shirt = _cloth()
    node = make(shirt, body, name="shirt_def")
    path, _ = _publish(tmp_path, shirt)
    cmds.setAttr(f"{node}.envelope", 0.3)
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    wrap.PRODUCT.run(path)
    assert cmds.getAttr("shirt_def.envelope") != pytest.approx(0.3)
    cmds.undo()
    assert _deformers(shirt) == ["shirt_def"]
    assert cmds.getAttr("shirt_def.envelope") == pytest.approx(0.3)


# -- publish checks and versions --------------------------------------------


def test_publish_problems(new_scene, tmp_path):
    path = wrap.PRODUCT.create(str(tmp_path), "wrap")
    cmds.select(clear=True)
    (problem,) = versions.publish_problems(path)
    assert "Nothing selected" in problem

    cmds.select(cmds.createNode("transform"))
    (problem,) = versions.publish_problems(path)
    assert "mesh" in problem.lower()

    body = _body()
    shirt = _cloth("shirt")
    coat = _cloth("coat", 1.3)
    cmds.select(shirt, coat)
    (problem,) = versions.publish_problems(path)
    assert "wrap" in problem and "shirt" in problem and "coat" in problem

    _wrap(shirt, body)
    cmds.select(shirt, coat)
    (problem,) = versions.publish_problems(path)
    assert "coat" in problem and "shirt" not in problem

    cmds.select(shirt)
    assert versions.publish_problems(path) == []


def test_publish_without_wrap_raises_and_writes_nothing(new_scene, tmp_path):
    path = wrap.PRODUCT.create(str(tmp_path), "wrap")
    cmds.select(_cloth())
    with pytest.raises(RuntimeError):
        versions.publish_action(path).fn()
    assert os.path.getsize(path) == 0


def test_republishing_adds_a_version_only_on_change(new_scene, tmp_path):
    body = _body()
    shirt = _cloth()
    _wrap(shirt, body)
    path, message = _publish(tmp_path, shirt)
    assert message.endswith("v001")

    cmds.select(shirt)
    assert versions.publish_action(path).fn().endswith("v001")
    assert [v.number for v in versions.list_versions(path)] == [1]

    cmds.setAttr("shirt_wrap.maxDistance", 4)
    assert versions.publish_action(path).fn().endswith("v002")


def test_panel_describes_the_nodes(new_scene, tmp_path):
    body = _body()
    shirt = _cloth("shirt")
    coat = _cloth("coat", 1.3)
    _wrap(shirt, body, "shirt_wrap")
    _proximity(coat, body, "coat_pwrap")
    path, _ = _publish(tmp_path, shirt, coat)
    assert wrap.PRODUCT.panel(path).info == [
        "1 wrap, 1 proximityWrap",
        "Meshes: shirt, coat",
        "Drivers: body",
    ]
