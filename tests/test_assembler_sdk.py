import os

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import data, logic, products, runlog, versions
from kaiju_suite.tools.assembler.products import sdk

KEY_FIELDS = (
    "driverValue",
    "value",
    "inTangentType",
    "outTangentType",
    "inAngle",
    "outAngle",
    "inWeight",
    "outWeight",
    "lock",
    "weightLock",
)


def _nodes():
    """A foot control with a ``roll`` attribute, and the groups it drives."""
    ctl = cmds.createNode("transform", name="foot_ctl", skipSelect=True)
    cmds.addAttr(ctl, longName="roll", attributeType="double", keyable=True)
    for name in ("heel_grp", "toe_grp"):
        node = cmds.createNode("transform", name=name, skipSelect=True)
        cmds.addAttr(node, longName="squash", attributeType="double", keyable=True)


def _sdk(driven, driver, keys, **tangents):
    for driver_value, value in keys:
        cmds.setDrivenKeyframe(driven, currentDriver=driver, driverValue=driver_value, value=value)
        if tangents:
            cmds.keyTangent(driven, edit=True, float=(driver_value, driver_value), **tangents)


def _curve_of(driven, driver):
    """The driven key curve from ``driver`` into ``driven``."""
    for curve in cmds.ls(type="animCurve"):
        source = cmds.listConnections(f"{curve}.input", source=True, destination=False, plugs=True, scn=True)
        if source and source[0] == driver and driven in _outputs(curve):
            return curve
    raise AssertionError(f"No curve from {driver} into {driven}")


def _outputs(curve):
    """Every plug ``curve`` ends up driving, through blendWeighted nodes."""
    found = []
    for plug in cmds.listConnections(f"{curve}.output", source=False, destination=True, plugs=True, scn=True) or []:
        node = plug.split(".", 1)[0]
        if cmds.nodeType(node) == "blendWeighted":
            found.extend(cmds.listConnections(f"{node}.output", source=False, destination=True, plugs=True, scn=True))
        else:
            found.append(plug)
    return found


def _rig():
    """heel rotateX: mixed tangents and infinity. toe rotateX: weighted
    tangents. toe translateY: two drivers (a blendWeighted, one of them a
    rotation). heel squash: a user attribute driven by a translation."""
    _sdk("heel_grp.rotateX", "foot_ctl.roll", [(-10, 20), (0, 0), (10, -30)])
    heel = _curve_of("heel_grp.rotateX", "foot_ctl.roll")
    cmds.keyTangent(heel, edit=True, float=(-10, -10), inTangentType="linear", outTangentType="linear")
    cmds.keyTangent(heel, edit=True, float=(0, 0), lock=False)
    cmds.keyTangent(heel, edit=True, float=(0, 0), inAngle=15, outAngle=-40)
    cmds.keyTangent(heel, edit=True, float=(0, 0), inTangentType="fixed", outTangentType="fixed")
    cmds.keyTangent(heel, edit=True, float=(10, 10), inTangentType="flat", outTangentType="step")
    cmds.setInfinity("heel_grp.rotateX", preInfinite="linear", postInfinite="cycle")

    _sdk("toe_grp.rotateX", "foot_ctl.roll", [(0, 0), (5, 30), (10, 45)])
    toe = _curve_of("toe_grp.rotateX", "foot_ctl.roll")
    cmds.keyTangent(toe, edit=True, weightedTangents=True)
    cmds.keyTangent(toe, edit=True, float=(5, 5), lock=False, weightLock=False)
    cmds.keyTangent(toe, edit=True, float=(5, 5), inAngle=10, outAngle=35, inWeight=2.5, outWeight=6.75)
    cmds.keyTangent(toe, edit=True, float=(5, 5), inTangentType="fixed", outTangentType="fixed")
    cmds.keyTangent(toe, edit=True, float=(10, 10), weightLock=True)

    _sdk("toe_grp.translateY", "foot_ctl.roll", [(0, 0), (10, 1.5)], inTangentType="linear", outTangentType="linear")
    _sdk("toe_grp.translateY", "foot_ctl.rotateZ", [(0, 0), (90, -2)])
    cmds.setAttr(f"{_curve_of('toe_grp.translateY', 'foot_ctl.rotateZ')}.preInfinity", 5)  # oscillate

    _sdk("heel_grp.squash", "foot_ctl.translateY", [(0, 1), (2, 0.25)])


def _round(value, digits=3):
    return round(value, digits)


def _state(curve):
    def q(**flag):
        return cmds.keyTangent(curve, query=True, **flag)

    return {
        "type": cmds.nodeType(curve),
        "pre": cmds.getAttr(f"{curve}.preInfinity"),
        "post": cmds.getAttr(f"{curve}.postInfinity"),
        "weighted": bool(q(weightedTangents=True)[0]),
        "inputs": [_round(v) for v in cmds.keyframe(curve, query=True, floatChange=True)],
        "values": [_round(v) for v in cmds.keyframe(curve, query=True, valueChange=True)],
        "inTypes": q(inTangentType=True),
        "outTypes": q(outTangentType=True),
        "angles": [_round(v) for v in q(inAngle=True) + q(outAngle=True)],
        "weights": [_round(v) for v in q(inWeight=True) + q(outWeight=True)],
        "locks": [bool(v) for v in q(lock=True) + q(weightLock=True)],
    }


PAIRS = (
    ("heel_grp.rotateX", "foot_ctl.roll"),
    ("toe_grp.rotateX", "foot_ctl.roll"),
    ("toe_grp.translateY", "foot_ctl.roll"),
    ("toe_grp.translateY", "foot_ctl.rotateZ"),
    ("heel_grp.squash", "foot_ctl.translateY"),
)
DRIVEN = sorted({driven for driven, _ in PAIRS})
POSES = [
    {"roll": -25, "rotateZ": -30, "translateY": -1},
    {"roll": -4, "rotateZ": 20, "translateY": 0.5},
    {"roll": 2.5, "rotateZ": 45, "translateY": 1.25},
    {"roll": 7, "rotateZ": 120, "translateY": 3},
    {"roll": 13, "rotateZ": 200, "translateY": 5},
    {"roll": 31, "rotateZ": 300, "translateY": 9},
]


def _states():
    return {pair: _state(_curve_of(*pair)) for pair in PAIRS}


def _samples():
    found = []
    for pose in POSES:
        for attr, value in pose.items():
            cmds.setAttr(f"foot_ctl.{attr}", value)
        found.append([_round(cmds.getAttr(plug), 4) for plug in DRIVEN])
    for attr in POSES[0]:
        cmds.setAttr(f"foot_ctl.{attr}", 0)
    return found


def _publish(tmp_path, *selection, name="foot"):
    path = sdk.PRODUCT.create(str(tmp_path), name)
    cmds.select(selection)
    message = versions.publish_action(path).fn()
    return path, message


# -- product ----------------------------------------------------------------


def test_sdk_is_discovered_and_owns_sdk(tmp_path):
    assert sdk.PRODUCT in products.discover()
    assert sdk.PRODUCT.name == "Set Driven Keys"
    assert sdk.PRODUCT.kind == "sdk"
    assert sdk.PRODUCT.extensions == (".sdk",)
    assert sdk.PRODUCT.order == 115
    assert sdk.PRODUCT.menu_slot == (4, 2)
    assert sdk.PRODUCT.runnable and sdk.PRODUCT.versioned
    path = sdk.PRODUCT.creators[0].fn(str(tmp_path), "foot", None)
    assert path == str(tmp_path / "foot.sdk") and os.path.getsize(path) == 0
    assert products.product_for(path) is sdk.PRODUCT


# -- publish and run --------------------------------------------------------


def test_round_trip_restores_curves_and_what_they_drive(new_scene, tmp_path):
    _nodes()
    _rig()
    before = _states()
    sampled = _samples()
    path, message = _publish(tmp_path, "heel_grp", "toe_grp")
    assert message == "Published Set Driven Keys foot.sdk v001"

    cmds.file(new=True, force=True)
    _nodes()
    logic.run_steps([path])

    assert _states() == before
    assert _samples() == sampled
    assert cmds.ls(type="blendWeighted")  # toe translateY has two drivers
    # Curves keep their names.
    assert cmds.ls("heel_grp_rotateX", type="animCurveUA")
    # Attributes that weren't driven stay free.
    assert not cmds.listConnections("heel_grp.translateZ", source=True, destination=False)


def test_file_holds_the_saved_fields(new_scene, tmp_path):
    _nodes()
    _rig()
    path, _ = _publish(tmp_path, "heel_grp", "toe_grp")
    curves = data.read(path, "sdk")["curves"]
    assert [(c["node"], c["attribute"], c["driver"], c["driverAttribute"]) for c in curves] == [
        ("heel_grp", "rotateX", "foot_ctl", "roll"),
        ("heel_grp", "squash", "foot_ctl", "translateY"),
        ("toe_grp", "rotateX", "foot_ctl", "roll"),
        ("toe_grp", "translateY", "foot_ctl", "roll"),
        ("toe_grp", "translateY", "foot_ctl", "rotateZ"),
    ]
    heel = curves[0]
    assert heel["name"] == "heel_grp_rotateX"
    assert heel["type"] == "animCurveUA"
    assert heel["preInfinity"] == "linear" and heel["postInfinity"] == "cycle"
    assert heel["weightedTangents"] is False
    assert tuple(heel["keys"][0]) == KEY_FIELDS
    assert [k["driverValue"] for k in heel["keys"]] == [-10, 0, 10]
    assert [k["value"] for k in heel["keys"]] == pytest.approx([20, 0, -30])
    assert curves[1]["type"] == "animCurveUU"
    assert curves[2]["weightedTangents"] is True
    assert curves[4]["type"] == "animCurveUL" and curves[4]["preInfinity"] == "oscillate"
    assert [k["driverValue"] for k in curves[4]["keys"]] == pytest.approx([0, 90])


def test_time_keys_are_not_saved(new_scene, tmp_path):
    _nodes()
    _sdk("heel_grp.rotateX", "foot_ctl.roll", [(0, 0), (10, 30)])
    cmds.setKeyframe("heel_grp.translateX", time=1, value=1)
    path, _ = _publish(tmp_path, "heel_grp")
    curves = data.read(path, "sdk")["curves"]
    assert [(c["node"], c["attribute"]) for c in curves] == [("heel_grp", "rotateX")]


def test_short_unique_names_are_saved(new_scene, tmp_path):
    _nodes()
    for group in ("L", "R"):
        cmds.createNode("transform", name=group)
        child = cmds.createNode("transform", name="toe", parent=group)
        _sdk(f"{child}.rotateX", "foot_ctl.roll", [(0, 0), (10, 30)])
    path, _ = _publish(tmp_path, "|L|toe", "|R|toe")
    nodes = sorted(c["node"] for c in data.read(path, "sdk")["curves"])
    assert nodes == ["L|toe", "R|toe"]


def test_rerunning_replaces_the_driven_keys_of_file_attributes(new_scene, tmp_path):
    _nodes()
    _rig()
    before = _states()
    path, _ = _publish(tmp_path, "heel_grp", "toe_grp")
    # Change a curve, and add a third driver to a file attribute.
    cmds.keyframe(_curve_of("heel_grp.rotateX", "foot_ctl.roll"), edit=True, float=(10, 10), valueChange=-90)
    _sdk("toe_grp.translateY", "foot_ctl.translateX", [(0, 0), (1, 1)])

    sdk.PRODUCT.run(path)
    sdk.PRODUCT.run(path)
    assert _states() == before
    assert len(cmds.ls(type="animCurve")) == len(PAIRS)
    assert len(cmds.ls(type="blendWeighted")) == 1


def test_driven_keys_on_other_attributes_are_untouched(new_scene, tmp_path):
    _nodes()
    _sdk("heel_grp.rotateX", "foot_ctl.roll", [(0, 0), (10, 30)])
    path, _ = _publish(tmp_path, "heel_grp")
    _sdk("heel_grp.rotateY", "foot_ctl.roll", [(0, 0), (10, 5), (20, 8)])
    other = _state(_curve_of("heel_grp.rotateY", "foot_ctl.roll"))

    sdk.PRODUCT.run(path)
    assert _state(_curve_of("heel_grp.rotateY", "foot_ctl.roll")) == other


def test_missing_nodes_and_attributes_are_skipped_with_a_warning(new_scene, tmp_path):
    _nodes()
    cmds.createNode("transform", name="ball_grp")
    _sdk("heel_grp.rotateX", "foot_ctl.roll", [(0, 0), (10, 30)])
    _sdk("heel_grp.squash", "foot_ctl.roll", [(0, 1), (10, 0)])
    _sdk("toe_grp.rotateX", "foot_ctl.roll", [(0, 0), (10, 45)])
    _sdk("ball_grp.rotateX", "foot_ctl.translateZ", [(0, 0), (1, 20)])
    path, _ = _publish(tmp_path, "heel_grp", "toe_grp", "ball_grp")

    cmds.file(new=True, force=True)
    cmds.createNode("transform", name="foot_ctl")  # no roll attribute
    cmds.createNode("transform", name="heel_grp")  # no squash attribute
    cmds.createNode("transform", name="ball_grp")  # toe_grp is missing
    with runlog.capture() as run:
        message = sdk.PRODUCT.run(path)
    assert run.warnings == [
        "Skipped missing nodes and attributes: foot_ctl.roll, heel_grp.squash, toe_grp"
    ]
    assert message == "Set driven keys on 1 attribute (1 curve, 2 keys)"
    assert _state(_curve_of("ball_grp.rotateX", "foot_ctl.translateZ"))["values"] == [0, 20]


def test_all_missing_is_a_warning_not_an_error(new_scene, tmp_path):
    _nodes()
    _sdk("heel_grp.rotateX", "foot_ctl.roll", [(0, 0), (10, 30)])
    path, _ = _publish(tmp_path, "heel_grp")
    cmds.file(new=True, force=True)
    with runlog.capture() as run:
        sdk.PRODUCT.run(path)
    assert run.warnings == ["Skipped missing nodes: foot_ctl, heel_grp"]
    assert not cmds.ls(type="animCurve")


@pytest.mark.parametrize("duplicate", ["heel_grp", "foot_ctl"])
def test_ambiguous_names_raise_and_change_nothing(new_scene, tmp_path, duplicate):
    _nodes()
    _sdk("heel_grp.rotateX", "foot_ctl.roll", [(0, 0), (10, 30)])
    _sdk("toe_grp.rotateX", "foot_ctl.roll", [(0, 0), (10, 45)])
    path, _ = _publish(tmp_path, "heel_grp", "toe_grp")

    cmds.delete(cmds.ls(type="animCurve"))
    group = cmds.createNode("transform", name="grp")
    copy = cmds.createNode("transform", name=duplicate, parent=group)
    if duplicate == "foot_ctl":
        cmds.addAttr(copy, longName="roll", attributeType="double", keyable=True)
    with pytest.raises(RuntimeError) as info:
        sdk.PRODUCT.run(path)
    assert duplicate in str(info.value)
    assert not cmds.ls(type="animCurve")


def test_attribute_driven_by_something_else_raises_and_changes_nothing(new_scene, tmp_path):
    _nodes()
    _sdk("heel_grp.rotateX", "foot_ctl.roll", [(0, 0), (10, 30)])
    _sdk("toe_grp.translateX", "foot_ctl.roll", [(0, 0), (10, 2)])
    path, _ = _publish(tmp_path, "heel_grp", "toe_grp")
    cmds.delete(cmds.ls(type="animCurve"))
    cmds.connectAttr("foot_ctl.translateZ", "toe_grp.translateX")
    cmds.setAttr("heel_grp.rotateX", lock=True)

    with pytest.raises(RuntimeError) as info:
        sdk.PRODUCT.run(path)
    assert "toe_grp.translateX" in str(info.value) and "heel_grp.rotateX" in str(info.value)
    assert not cmds.ls(type="animCurve")
    assert cmds.listConnections("toe_grp.translateX", source=True, destination=False) == ["foot_ctl"]


def test_empty_file_is_skipped(new_scene, tmp_path):
    _nodes()
    path = sdk.PRODUCT.create(str(tmp_path), "foot")
    assert logic.run_steps([path]) == [path]
    assert not cmds.ls(type="animCurve")


def test_one_undo_reverts_a_run(new_scene, tmp_path):
    _nodes()
    _rig()
    path, _ = _publish(tmp_path, "heel_grp", "toe_grp")
    heel = _curve_of("heel_grp.rotateX", "foot_ctl.roll")
    cmds.keyframe(heel, edit=True, float=(10, 10), valueChange=-90)
    before = _states()
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    sdk.PRODUCT.run(path)
    assert _state(_curve_of("heel_grp.rotateX", "foot_ctl.roll"))["values"][-1] == -30
    cmds.undo()
    assert _states() == before


def test_one_undo_reverts_a_fresh_run(new_scene, tmp_path):
    _nodes()
    _rig()
    path, _ = _publish(tmp_path, "heel_grp", "toe_grp")
    cmds.delete(cmds.ls(type="animCurve"))
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    sdk.PRODUCT.run(path)
    assert len(cmds.ls(type="animCurve")) == len(PAIRS)
    cmds.undo()
    assert not cmds.ls(type="animCurve")
    assert not cmds.ls(type="blendWeighted")


def test_run_message_counts_attributes_curves_and_keys(new_scene, tmp_path):
    _nodes()
    _rig()
    path, _ = _publish(tmp_path, "heel_grp", "toe_grp")
    assert sdk.PRODUCT.run(path) == "Set driven keys on 4 attributes (5 curves, 12 keys)"


# -- publish checks, versions and panel -------------------------------------


def test_publish_problems(new_scene, tmp_path):
    path = sdk.PRODUCT.create(str(tmp_path), "foot")
    cmds.select(clear=True)
    (problem,) = versions.publish_problems(path)
    assert "Nothing selected" in problem

    _nodes()
    cmds.select("heel_grp")
    (problem,) = versions.publish_problems(path)
    assert "driven keys" in problem.lower()

    # Time keys don't count.
    cmds.setKeyframe("heel_grp.translateY", time=1, value=1)
    cmds.select("heel_grp")
    (problem,) = versions.publish_problems(path)
    assert "driven keys" in problem.lower()

    _sdk("heel_grp.rotateX", "foot_ctl.roll", [(0, 0), (10, 30)])
    cmds.select("heel_grp")
    assert versions.publish_problems(path) == []


def test_publish_without_driven_keys_raises_and_writes_nothing(new_scene, tmp_path):
    _nodes()
    path = sdk.PRODUCT.create(str(tmp_path), "foot")
    cmds.select("heel_grp")
    with pytest.raises(RuntimeError):
        versions.publish_action(path).fn()
    assert os.path.getsize(path) == 0


def test_republishing_adds_a_version_only_on_change(new_scene, tmp_path):
    _nodes()
    _rig()
    path, message = _publish(tmp_path, "heel_grp", "toe_grp")
    assert message.endswith("v001")

    cmds.select("heel_grp", "toe_grp")
    assert versions.publish_action(path).fn().endswith("v001")
    assert [v.number for v in versions.list_versions(path)] == [1]

    _sdk("heel_grp.rotateX", "foot_ctl.roll", [(20, -45)])
    assert versions.publish_action(path).fn().endswith("v002")


def test_panel_describes_the_driven_keys(new_scene, tmp_path):
    _nodes()
    _rig()
    path, _ = _publish(tmp_path, "heel_grp", "toe_grp")
    assert sdk.PRODUCT.panel(path).info == [
        "5 driven key curves on 4 attributes of 2 nodes, 12 keys",
        "Drivers: foot_ctl.roll, foot_ctl.rotateZ, foot_ctl.translateY",
    ]
