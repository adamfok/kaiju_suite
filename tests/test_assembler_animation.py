import os

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import data, logic, products, runlog, versions
from kaiju_suite.tools.assembler.products import animation

KEY_FIELDS = (
    "time",
    "value",
    "inTangentType",
    "outTangentType",
    "inAngle",
    "outAngle",
    "inWeight",
    "outWeight",
    "breakdown",
    "lock",
    "weightLock",
)


def _box(name="box"):
    node = cmds.createNode("transform", name=name, skipSelect=True)
    cmds.addAttr(node, longName="squash", attributeType="double", keyable=True)
    return node


def _key(plug, time, value, **tangents):
    cmds.setKeyframe(plug, time=time, value=value)
    if tangents:
        cmds.keyTangent(plug, edit=True, time=(time, time), **tangents)


def _animate(node="box"):
    """translateX: spline/linear/step/fixed keys, a breakdown, cycle infinity.
    rotateY: weighted tangents with custom weights. squash: a user attr."""
    tx = f"{node}.translateX"
    _key(tx, 1, 0.0, inTangentType="spline", outTangentType="spline")
    _key(tx, 5, 3.0, inTangentType="linear", outTangentType="linear")
    _key(tx, 10, 1.0, inTangentType="linear", outTangentType="step")
    _key(tx, 15, 4.0)
    cmds.keyTangent(tx, edit=True, time=(15, 15), lock=False)
    cmds.keyTangent(tx, edit=True, time=(15, 15), inAngle=30, outAngle=-20)
    cmds.keyTangent(tx, edit=True, time=(15, 15), inTangentType="fixed", outTangentType="fixed")
    _key(tx, 20, 2.0, inTangentType="clamped", outTangentType="auto")
    cmds.keyframe(tx, edit=True, time=(5, 5), breakdown=True)
    cmds.setInfinity(tx, preInfinite="cycle", postInfinite="cycleRelative")

    ry = f"{node}.rotateY"
    _key(ry, 0, 0.0)
    _key(ry, 12, 90.0)
    _key(ry, 24, 45.0)
    cmds.keyTangent(ry, edit=True, weightedTangents=True)
    cmds.keyTangent(ry, edit=True, time=(12, 12), lock=False, weightLock=False)
    cmds.keyTangent(ry, edit=True, time=(12, 12), inAngle=10, outAngle=40, inWeight=3.5, outWeight=7.25)
    cmds.keyTangent(ry, edit=True, time=(12, 12), inTangentType="fixed", outTangentType="fixed")
    cmds.keyTangent(ry, edit=True, time=(24, 24), weightLock=True)
    cmds.setInfinity(ry, postInfinite="oscillate")

    _key(f"{node}.squash", 3, 0.5, inTangentType="plateau", outTangentType="plateau")
    _key(f"{node}.squash", 9, 1.5, inTangentType="flat", outTangentType="flat")


def _keys(plug):
    """Every key of ``plug`` as a list of dicts, rounded, for comparison."""
    times = cmds.keyframe(plug, query=True, timeChange=True) or []
    values = cmds.keyframe(plug, query=True, valueChange=True)
    breakdowns = set(cmds.keyframe(plug, query=True, breakdown=True) or [])
    found = []
    for time, value in zip(times, values):
        t = (time, time)

        def q(**flag):
            return cmds.keyTangent(plug, query=True, time=t, **flag)[0]

        found.append(
            {
                "time": round(time, 4),
                "value": round(value, 4),
                "inTangentType": q(inTangentType=True),
                "outTangentType": q(outTangentType=True),
                "inAngle": round(q(inAngle=True), 3),
                "outAngle": round(q(outAngle=True), 3),
                "inWeight": round(q(inWeight=True), 3),
                "outWeight": round(q(outWeight=True), 3),
                "breakdown": time in breakdowns,
                "lock": bool(q(lock=True)),
                "weightLock": bool(q(weightLock=True)),
            }
        )
    return found


def _curve_state(plug):
    curve = cmds.listConnections(plug, source=True, destination=False, type="animCurve")[0]
    return {
        "type": cmds.nodeType(curve),
        "pre": cmds.setInfinity(plug, query=True, preInfinite=True)[0],
        "post": cmds.setInfinity(plug, query=True, postInfinite=True)[0],
        "weighted": bool(cmds.keyTangent(plug, query=True, weightedTangents=True)[0]),
        "keys": _keys(plug),
    }


def _samples(plug, times):
    return [round(cmds.getAttr(plug, time=t), 4) for t in times]


PLUGS = ("translateX", "rotateY", "squash")
# In-between frames, plus some before and after the keys to check infinity.
FRAMES = [-12.5, -3, 0.5, 2.5, 4, 7.25, 9.9, 12.5, 17, 19.5, 23, 31, 47.5]


def _publish(tmp_path, *selection, name="walk"):
    path = animation.PRODUCT.create(str(tmp_path), name)
    cmds.select(selection)
    message = versions.publish_action(path).fn()
    return path, message


# -- product ----------------------------------------------------------------


def test_animation_is_discovered_and_owns_anim(tmp_path):
    assert animation.PRODUCT in products.discover()
    assert animation.PRODUCT.name == "Animation"
    assert animation.PRODUCT.kind == "animation"
    assert animation.PRODUCT.extensions == (".anim",)
    assert animation.PRODUCT.order == 110
    assert animation.PRODUCT.runnable and animation.PRODUCT.versioned
    path = animation.PRODUCT.creators[0].fn(str(tmp_path), "walk", None)
    assert path == str(tmp_path / "walk.anim") and os.path.getsize(path) == 0
    assert products.product_for(path) is animation.PRODUCT


# -- publish and run --------------------------------------------------------


def test_round_trip_restores_keys_tangents_and_infinity(new_scene, tmp_path):
    _box()
    _animate()
    before = {p: _curve_state(f"box.{p}") for p in PLUGS}
    sampled = {p: _samples(f"box.{p}", FRAMES) for p in PLUGS}
    path, message = _publish(tmp_path, "box")
    assert message == "Published Animation walk.anim v001"

    cmds.file(new=True, force=True)
    _box()
    logic.run_steps([path])

    assert {p: _curve_state(f"box.{p}") for p in PLUGS} == before
    assert {p: _samples(f"box.{p}", FRAMES) for p in PLUGS} == sampled
    # Attributes that weren't animated stay unanimated.
    assert not cmds.listConnections("box.translateY", source=True, destination=False)


def test_file_holds_the_saved_fields(new_scene, tmp_path):
    _box()
    _animate()
    path, _ = _publish(tmp_path, "box")
    curves = data.read(path, "animation")["curves"]
    assert sorted((c["node"], c["attribute"]) for c in curves) == [
        ("box", "rotateY"),
        ("box", "squash"),
        ("box", "translateX"),
    ]
    tx = next(c for c in curves if c["attribute"] == "translateX")
    assert tx["type"] == "animCurveTL"
    assert tx["preInfinity"] == "cycle" and tx["postInfinity"] == "cycleRelative"
    assert tx["weightedTangents"] is False
    assert set(tx["keys"][0]) == set(KEY_FIELDS)
    assert [k["breakdown"] for k in tx["keys"]] == [False, True, False, False, False]
    ry = next(c for c in curves if c["attribute"] == "rotateY")
    assert ry["type"] == "animCurveTA" and ry["weightedTangents"] is True


def test_short_unique_names_are_saved(new_scene, tmp_path):
    for group in ("a", "b"):
        cmds.createNode("transform", name=group)
        child = cmds.createNode("transform", name="ctl", parent=group)
        cmds.setKeyframe(child, attribute="translateX", time=1, value=1)
    path, _ = _publish(tmp_path, "|a|ctl", "|b|ctl")
    nodes = sorted(c["node"] for c in data.read(path, "animation")["curves"])
    assert nodes == ["a|ctl", "b|ctl"]


def test_existing_keys_on_a_file_attribute_are_replaced(new_scene, tmp_path):
    _box()
    _animate()
    before = _curve_state("box.translateX")
    path, _ = _publish(tmp_path, "box")

    cmds.cutKey("box", clear=True)
    for t in (2, 7, 13, 30, 50):
        cmds.setKeyframe("box.translateX", time=t, value=t * 10)
    animation.PRODUCT.run(path)
    assert _curve_state("box.translateX") == before


def test_other_attributes_keys_are_untouched(new_scene, tmp_path):
    _box()
    cmds.setKeyframe("box.translateX", time=1, value=1)
    cmds.setKeyframe("box.translateX", time=10, value=5)
    path, _ = _publish(tmp_path, "box")

    cmds.setKeyframe("box.scaleZ", time=4, value=2)
    cmds.setKeyframe("box.scaleZ", time=8, value=3)
    other = _curve_state("box.scaleZ")
    animation.PRODUCT.run(path)
    assert _curve_state("box.scaleZ") == other


def test_driven_keys_are_not_saved(new_scene, tmp_path):
    _box()
    driver = cmds.createNode("transform", name="driver")
    cmds.setDrivenKeyframe("box.translateZ", currentDriver=f"{driver}.translateX", driverValue=0, value=0)
    cmds.setDrivenKeyframe("box.translateZ", currentDriver=f"{driver}.translateX", driverValue=1, value=5)
    cmds.setKeyframe("box.translateX", time=1, value=1)
    path, _ = _publish(tmp_path, "box")
    curves = data.read(path, "animation")["curves"]
    assert [(c["node"], c["attribute"]) for c in curves] == [("box", "translateX")]


def test_missing_nodes_and_attributes_are_skipped_with_a_warning(new_scene, tmp_path):
    _box()
    other = _box("other")
    for node in ("box", other):
        cmds.setKeyframe(f"{node}.translateX", time=1, value=1)
        cmds.setKeyframe(f"{node}.squash", time=1, value=2)
    path, _ = _publish(tmp_path, "box", other)

    cmds.file(new=True, force=True)
    cmds.createNode("transform", name="box")  # no squash attribute
    cmds.setKeyframe("box.translateX", time=3, value=9)
    with runlog.capture() as run:
        message = animation.PRODUCT.run(path)
    assert run.warnings == ["Skipped missing nodes and attributes: box.squash, other"]
    assert message == "Keyed 1 attribute (1 key)"
    assert cmds.keyframe("box.translateX", query=True, timeChange=True) == [1]


def test_empty_file_is_skipped(new_scene, tmp_path):
    _box()
    path = animation.PRODUCT.create(str(tmp_path), "walk")
    assert logic.run_steps([path]) == [path]
    assert not cmds.ls(type="animCurve")


def test_one_undo_reverts_a_run(new_scene, tmp_path):
    _box()
    _animate()
    path, _ = _publish(tmp_path, "box")
    cmds.cutKey("box", clear=True)
    cmds.setKeyframe("box.translateX", time=2, value=7)
    before = _curve_state("box.translateX")
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    animation.PRODUCT.run(path)
    assert len(_keys("box.translateX")) == 5
    cmds.undo()
    assert _curve_state("box.translateX") == before
    assert not cmds.listConnections("box.rotateY", source=True, destination=False)


def test_run_message_counts_attributes(new_scene, tmp_path):
    _box()
    _animate()
    path, _ = _publish(tmp_path, "box")
    message = animation.PRODUCT.run(path)
    assert "3" in message and "10" in message


# -- publish checks, versions and panel -------------------------------------


def test_publish_problems(new_scene, tmp_path):
    path = animation.PRODUCT.create(str(tmp_path), "walk")
    cmds.select(clear=True)
    (problem,) = versions.publish_problems(path)
    assert "Nothing selected" in problem

    _box()
    cmds.select("box")
    (problem,) = versions.publish_problems(path)
    assert "keys" in problem.lower()

    # Driven keys don't count.
    cmds.setDrivenKeyframe("box.translateZ", currentDriver="box.translateX", driverValue=0, value=0)
    cmds.select("box")
    (problem,) = versions.publish_problems(path)
    assert "keys" in problem.lower()

    cmds.setKeyframe("box.translateY", time=1, value=1)
    cmds.select("box")
    assert versions.publish_problems(path) == []


def test_publish_without_keys_raises_and_writes_nothing(new_scene, tmp_path):
    path = animation.PRODUCT.create(str(tmp_path), "walk")
    cmds.select(_box())
    with pytest.raises(RuntimeError):
        versions.publish_action(path).fn()
    assert os.path.getsize(path) == 0


def test_republishing_adds_a_version_only_on_change(new_scene, tmp_path):
    _box()
    _animate()
    path, message = _publish(tmp_path, "box")
    assert message.endswith("v001")

    cmds.select("box")
    assert versions.publish_action(path).fn().endswith("v001")
    assert [v.number for v in versions.list_versions(path)] == [1]

    cmds.setKeyframe("box.translateX", time=30, value=8)
    assert versions.publish_action(path).fn().endswith("v002")


def test_panel_describes_the_animation(new_scene, tmp_path):
    _box()
    _animate()
    other = _box("other")
    cmds.setKeyframe(f"{other}.translateZ", time=-4, value=1)
    path, _ = _publish(tmp_path, "box", other)
    assert animation.PRODUCT.panel(path).info == [
        "4 animated attributes on 2 nodes, 11 keys",
        "Frames -4 to 24",
    ]
