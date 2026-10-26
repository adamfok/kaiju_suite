"""ProximityWrap save/load (kaiju_suite.datatypes.proximity_wrap)."""

import pytest
from maya import cmds, mel

from kaiju_suite import datatypes
from kaiju_suite.datatypes import proximity_wrap

SETTINGS = {"wrapMode": 0, "falloffScale": 1.5, "smoothNormals": 2, "envelope": 0.8}
DRIVER_SETTINGS = {"driverFalloffStart": 0.05, "driverFalloffEnd": 2.0, "driverStrength": 0.7}
PAINTED = {3: 0.25, 10: 0.0}


def _body(name="body"):
    return cmds.polySphere(name=name, radius=1, sx=8, sy=8, ch=False)[0]


def _cloth(name="shirt", radius=1.1):
    """24 vertices, no history."""
    return cmds.polyCylinder(name=name, radius=radius, height=1, sx=8, sy=2, ch=False)[0]


def _shape(transform):
    return cmds.listRelatives(transform, shapes=True, noIntermediate=True, fullPath=True)[0]


def _proximity(driven, driver, name="shirt_pwrap", painted=PAINTED):
    node = cmds.proximityWrap(driven, name=name)[0]
    cmds.proximityWrap(node, edit=True, addDrivers=[_shape(driver)])
    for attr, value in SETTINGS.items():
        cmds.setAttr(f"{node}.{attr}", value)
    for attr, value in DRIVER_SETTINGS.items():
        cmds.setAttr(f"{node}.drivers[0].{attr}", value)
    for vertex, weight in painted.items():
        cmds.setAttr(f"{node}.weightList[0].weights[{vertex}]", weight)
    return node


def _wrap(driven, driver, name="shirt_wrap"):
    """A classic wrap, made the way Maya's Create Wrap menu makes it."""
    cmds.select(driven, driver)
    mel.eval('doWrapArgList "7" { "1","0","1", "2", "1", "1", "0", "0" }')
    node = cmds.rename(cmds.ls(cmds.listHistory(driven), type="wrap")[0], name)
    cmds.select(clear=True)
    return node


def _long(nodes):
    return cmds.ls(nodes, long=True)


def _weights(node, mesh):
    return [round(w, 5) for w in cmds.percent(node, f"{mesh}.vtx[*]", query=True, value=True)]


def test_kind_and_extension():
    assert proximity_wrap.KIND == "proximity_wrap"
    assert proximity_wrap.EXTENSION == ".pwrap"


def test_gather_saves_the_proximity_wrap_its_driver_settings_and_weights(new_scene):
    shirt = _cloth()
    _proximity(shirt, _body())

    [record] = proximity_wrap.gather(_long(shirt))["deformers"]

    assert record["name"] == "shirt_pwrap" and record["type"] == "proximityWrap"
    assert record["meshes"][0]["mesh"] == "shirt" and record["meshes"][0]["vertex_count"] == 24
    assert sorted(map(tuple, record["meshes"][0]["weights"])) == sorted(PAINTED.items())
    assert [d["mesh"] for d in record["drivers"]] == ["body"]
    for attr, value in DRIVER_SETTINGS.items():
        assert record["drivers"][0][attr] == pytest.approx(value)
    for attr, value in SETTINGS.items():
        assert record["settings"][attr] == pytest.approx(value)


def test_gather_leaves_out_classic_wraps(new_scene):
    body = _body()
    shirt = _cloth()
    _wrap(shirt, body, "shirt_wrap")
    _proximity(shirt, body, painted={})

    payload = proximity_wrap.gather(_long(shirt))

    assert [r["name"] for r in payload["deformers"]] == ["shirt_pwrap"]


def test_gather_then_apply_rebuilds_it(new_scene):
    shirt = _cloth()
    _proximity(shirt, _body())
    payload = proximity_wrap.gather(_long(shirt))

    cmds.file(new=True, force=True)
    _body()
    shirt = _cloth()
    lines = []
    message = proximity_wrap.apply(payload, info=lines.append)

    assert message == "Created shirt_pwrap on shirt"
    assert lines == ["shirt_pwrap: on shirt, driven by body"]
    assert cmds.nodeType("shirt_pwrap") == "proximityWrap"
    for attr, value in SETTINGS.items():
        assert cmds.getAttr(f"shirt_pwrap.{attr}") == pytest.approx(value)
    for attr, value in DRIVER_SETTINGS.items():
        assert cmds.getAttr(f"shirt_pwrap.drivers[0].{attr}") == pytest.approx(value)
    expected = [1.0] * 24
    for vertex, weight in PAINTED.items():
        expected[vertex] = weight
    assert _weights("shirt_pwrap", shirt) == expected


def test_apply_replaces_the_same_named_node(new_scene):
    shirt = _cloth()
    _proximity(shirt, _body())
    payload = proximity_wrap.gather(_long(shirt))
    cmds.setAttr("shirt_pwrap.falloffScale", 7)

    proximity_wrap.apply(payload)

    assert cmds.ls(type="proximityWrap") == ["shirt_pwrap"]
    assert cmds.getAttr("shirt_pwrap.falloffScale") == pytest.approx(1.5)


def test_apply_skips_missing_meshes_and_drivers_with_a_warning(new_scene, monkeypatch):
    shirt = _cloth()
    _proximity(shirt, _body())
    payload = proximity_wrap.gather(_long(shirt))
    warnings = []
    monkeypatch.setattr(datatypes, "warning", warnings.append)

    cmds.file(new=True, force=True)
    _cloth()
    message = proximity_wrap.apply(payload)

    assert warnings == ["Skipped missing drivers: body"]
    assert message == "Created no proximityWraps"
    assert not cmds.ls(type="proximityWrap")


def test_apply_raises_on_a_changed_vertex_count_and_changes_nothing(new_scene):
    shirt = _cloth()
    _proximity(shirt, _body())
    payload = proximity_wrap.gather(_long(shirt))

    cmds.file(new=True, force=True)
    _body()
    cmds.polyCylinder(name="shirt", radius=1.1, height=1, sx=6, sy=1, ch=False)
    with pytest.raises(RuntimeError, match="24"):
        proximity_wrap.apply(payload)
    assert not cmds.ls(type="proximityWrap")


def test_selection_problems(new_scene):
    assert proximity_wrap.selection_problems([]) == [
        "Nothing selected. Select the meshes with a proximityWrap to publish."
    ]
    assert proximity_wrap.selection_problems(_long(cmds.createNode("transform", name="grp"))) == [
        "No meshes selected. Select the meshes with a proximityWrap to publish."
    ]
    body = _body()
    shirt = _cloth("shirt")
    coat = _cloth("coat", 1.3)
    _wrap(shirt, body)  # a classic wrap only
    assert proximity_wrap.selection_problems(_long([shirt, coat])) == ["No proximityWrap on: shirt, coat"]

    _proximity(coat, body, "coat_pwrap")
    assert proximity_wrap.selection_problems(_long(coat)) == []


def test_gather_without_a_proximity_wrap_raises(new_scene):
    with pytest.raises(RuntimeError, match="proximityWrap"):
        proximity_wrap.gather(_long(_cloth()))


def test_describe_and_nodes(new_scene):
    body = _body()
    shirt = _cloth("shirt")
    coat = _cloth("coat", 1.3)
    _proximity(shirt, body, "shirt_pwrap")
    _proximity(coat, body, "coat_pwrap")

    payload = proximity_wrap.gather(_long([shirt, coat]))

    assert proximity_wrap.describe(payload) == ["2 proximityWraps", "Meshes: shirt, coat", "Drivers: body"]
    assert proximity_wrap.nodes(payload) == ["shirt", "coat"]
    assert proximity_wrap.compare_view(payload) == payload


def test_save_and_load_a_pwrap_file(new_scene, tmp_path):
    shirt = _cloth()
    _proximity(shirt, _body())
    path = datatypes.save(proximity_wrap, str(tmp_path / "shirt.pwrap"), _long(shirt))

    cmds.delete("shirt_pwrap")
    datatypes.load(proximity_wrap, path)

    assert cmds.ls(type="proximityWrap") == ["shirt_pwrap"]
