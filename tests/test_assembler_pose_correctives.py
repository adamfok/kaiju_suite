import os

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import data, logic, products, runlog, versions
from kaiju_suite.tools.assembler.products import pose_correctives

SETTINGS = {
    "regularization": 0.2,
    "outputSmoothing": 0.3,
    "interpolation": 1,
    "allowNegativeWeights": False,
    "enableRotation": True,
    "enableTranslation": True,
}


def setup_module():
    cmds.loadPlugin("poseInterpolator", quiet=True)


def _joints():
    cmds.select(clear=True)
    cmds.joint(name="arm_jnt", position=(0, 0, 0))
    cmds.joint(name="elbow_jnt", position=(2, 0, 0))
    cmds.joint(name="wrist_jnt", position=(4, 0, 0))
    cmds.select(clear=True)


def _mesh():
    """A cube with a blendShape ``body_bs`` holding two targets, ``elbow_bend`` and ``elbow_up``."""
    body = cmds.polyCube(name="body", ch=False)[0]
    targets = []
    for name, offset in (("elbow_bend", 1.0), ("elbow_up", 0.5)):
        target = cmds.duplicate(body, name=name)[0]
        cmds.move(0, offset, 0, f"{target}.vtx[0:3]", relative=True)
        targets.append(target)
    cmds.blendShape(*targets, body, name="body_bs")
    cmds.delete(targets)
    return body


def _scene():
    _joints()
    _mesh()


def _interpolator(name="elbow_pi", drivers=("elbow_jnt",), connect=True):
    """A poseInterpolator on ``drivers`` with a neutral pose and two posed ones."""
    cmds.select(list(drivers))
    transform = cmds.poseInterpolator(name=name)[0]
    shape = cmds.listRelatives(transform, shapes=True)[0]
    cmds.select(clear=True)
    for attr, value in SETTINGS.items():
        cmds.setAttr(f"{shape}.{attr}", value)
    cmds.setAttr(f"{shape}.driver[0].driverTwistAxis", 1)
    cmds.setAttr(f"{shape}.driver[0].driverEulerTwist", True)
    driver = drivers[0]
    cmds.poseInterpolator(shape, edit=True, addPose="neutral")
    cmds.setAttr(f"{driver}.rotateZ", 90)
    cmds.setAttr(f"{driver}.translateY", 0.5)
    cmds.poseInterpolator(shape, edit=True, addPose="bend")
    cmds.setAttr(f"{driver}.rotateZ", 0)
    cmds.setAttr(f"{driver}.rotateY", -60)
    cmds.setAttr(f"{driver}.translateY", 0)
    cmds.poseInterpolator(shape, edit=True, addPose="up")
    cmds.setAttr(f"{driver}.rotateY", 0)
    cmds.setAttr(f"{shape}.pose[1].poseType", 2)
    cmds.setAttr(f"{shape}.pose[1].poseFalloff", 0.7)
    cmds.setAttr(f"{shape}.pose[1].poseRotationFalloff", 120)
    cmds.setAttr(f"{shape}.pose[1].poseTranslationFalloff", 2.5)
    cmds.setAttr(f"{shape}.pose[2].isIndependent", True)
    cmds.setAttr(f"{shape}.pose[2].isEnabled", False)
    if connect:
        cmds.connectAttr(f"{shape}.output[1]", "body_bs.elbow_bend")
        cmds.connectAttr(f"{shape}.output[2]", "body_bs.elbow_up")
    return shape


def _shape(name="elbow_pi"):
    return cmds.listRelatives(name, shapes=True, type="poseInterpolator")[0]


def _snapshot(name="elbow_pi"):
    """What a poseInterpolator holds, for comparing two scenes."""
    shape = _shape(name)
    poses = {}
    for index in cmds.getAttr(f"{shape}.pose", multiIndices=True) or []:
        plug = f"{shape}.pose[{index}]"
        poses[index] = {
            attr: cmds.getAttr(f"{plug}.{attr}")
            for attr in ("poseName", "poseType", "poseFalloff", "poseRotationFalloff", "poseTranslationFalloff",
                         "isIndependent", "isEnabled")
        }
        poses[index]["rotation"] = [round(v, 6) for v in cmds.getAttr(f"{plug}.poseRotation[0]")]
        poses[index]["translation"] = [round(v, 6) for v in cmds.getAttr(f"{plug}.poseTranslation[0]")]
    return {
        "settings": {attr: round(cmds.getAttr(f"{shape}.{attr}"), 5) for attr in SETTINGS},
        "drivers": cmds.poseInterpolator(shape, query=True, drivers=True),
        "twist": [cmds.getAttr(f"{shape}.driver[0].{a}") for a in ("driverTwistAxis", "driverEulerTwist")],
        "poses": poses,
        "outputs": sorted(cmds.listConnections(f"{shape}.output", source=False, plugs=True, connections=True) or []),
    }


def _weights():
    cmds.setAttr("elbow_jnt.rotateZ", 50)
    cmds.setAttr("elbow_jnt.translateY", 0.2)
    values = [round(cmds.getAttr(f"body_bs.{t}"), 5) for t in ("elbow_bend", "elbow_up")]
    cmds.setAttr("elbow_jnt.rotateZ", 0)
    cmds.setAttr("elbow_jnt.translateY", 0)
    return values


def _publish(tmp_path, *selection, name="correctives"):
    path = pose_correctives.PRODUCT.create(str(tmp_path), name)
    cmds.select(selection)
    message = versions.publish_action(path).fn()
    return path, message


def _published(tmp_path):
    _scene()
    _interpolator()
    path, _ = _publish(tmp_path, "elbow_pi")
    return path


# -- product ----------------------------------------------------------------


def test_product_is_discovered_and_owns_psd(tmp_path):
    product = pose_correctives.PRODUCT
    assert product in products.discover()
    assert product.name == "Pose Correctives"
    assert product.kind == "pose_correctives"
    assert product.extensions == (".psd",)
    assert product.runnable and product.versioned
    assert product.menu_slot == (3, 5)
    path = product.creators[0].fn(str(tmp_path), "correctives", None)
    assert path == str(tmp_path / "correctives.psd") and os.path.getsize(path) == 0
    assert products.product_for(path) is product


def test_new_menu_puts_it_in_the_blendshapes_group():
    names = [entry[0].name if entry else None for entry in products.new_menu()]
    group = names[names.index("BlendShapes"):]
    assert "Pose Correctives" in group[: group.index(None)]


# -- publish ----------------------------------------------------------------


def test_publish_saves_drivers_settings_poses_and_outputs(new_scene, tmp_path):
    _scene()
    _interpolator()
    path, message = _publish(tmp_path, "elbow_pi")
    assert message == "Published Pose Correctives correctives.psd v001"

    (record,) = data.read(path, "pose_correctives")["interpolators"]
    assert record["name"] == "elbow_pi"
    assert record["drivers"] == [{"node": "elbow_jnt", "twist_axis": 1, "euler_twist": True}]
    for attr, value in SETTINGS.items():
        assert record["settings"][attr] == pytest.approx(value)
    poses = {p["name"]: p for p in record["poses"]}
    assert [p["index"] for p in record["poses"]] == [0, 1, 2]
    assert poses["bend"]["type"] == 2
    assert poses["bend"]["falloff"] == pytest.approx(0.7)
    assert poses["bend"]["rotation_falloff"] == pytest.approx(120)
    assert poses["bend"]["translation_falloff"] == pytest.approx(2.5)
    assert poses["bend"]["translations"] == [pytest.approx([2.0, 0.5, 0.0])]
    assert len(poses["bend"]["rotations"][0]) == 4
    assert poses["up"]["independent"] and not poses["up"]["enabled"]
    assert record["outputs"] == [
        {"pose": 1, "node": "body_bs", "attr": "elbow_bend"},
        {"pose": 2, "node": "body_bs", "attr": "elbow_up"},
    ]


def test_publish_from_the_driver_joint(new_scene, tmp_path):
    _scene()
    _interpolator("elbow_pi")
    _interpolator("elbow2_pi", connect=False)
    _interpolator("wrist_pi", drivers=("wrist_jnt",), connect=False)
    path, _ = _publish(tmp_path, "elbow_jnt")
    records = data.read(path, "pose_correctives")["interpolators"]
    assert [r["name"] for r in records] == ["elbow2_pi", "elbow_pi"]


def test_publish_saves_several_drivers_in_order(new_scene, tmp_path):
    _scene()
    _interpolator("two_pi", drivers=("elbow_jnt", "wrist_jnt"), connect=False)
    path, _ = _publish(tmp_path, "two_pi")
    (record,) = data.read(path, "pose_correctives")["interpolators"]
    assert [d["node"] for d in record["drivers"]] == ["elbow_jnt", "wrist_jnt"]
    assert all(len(p["rotations"]) == 2 for p in record["poses"])


# -- run --------------------------------------------------------------------


def test_round_trip_rebuilds_and_reconnects(new_scene, tmp_path):
    _scene()
    _interpolator()
    before, weights = _snapshot(), _weights()
    path, _ = _publish(tmp_path, "elbow_pi")

    cmds.file(new=True, force=True)
    _scene()
    assert logic.run_steps([path]) == [path]

    assert _snapshot() == before
    assert _weights() == weights
    assert weights[0] > 0


def test_round_trip_without_a_pose_interpolator_manager(new_scene, tmp_path):
    path = _published(tmp_path)
    cmds.file(new=True, force=True)
    cmds.delete(cmds.ls(type="poseInterpolatorManager"))
    _scene()
    with runlog.capture() as run:
        pose_correctives.PRODUCT.run(path)
    assert not run.has_problems
    assert _snapshot()["poses"][1]["poseName"] == "bend"
    assert _weights()[0] > 0


def test_run_files_it_in_the_pose_interpolator_manager(new_scene, tmp_path):
    # Maya's Pose Editor keeps its interpolators in this node; Run uses Maya's
    # command when it exists, so the rebuilt node is filed there too.
    path = _published(tmp_path)
    cmds.file(new=True, force=True)
    manager = cmds.createNode("poseInterpolatorManager", name="poseInterpolatorManager")
    _scene()
    cmds.select("body")
    with runlog.capture() as run:
        pose_correctives.PRODUCT.run(path)
    assert not run.has_problems
    assert cmds.listConnections(f"{_shape()}.midLayerParent", source=False) == [manager]
    assert cmds.ls(selection=True) == ["body"]
    assert _weights()[0] > 0

    cmds.delete("elbow_pi")
    cmds.undoInfo(state=True)
    cmds.flushUndo()
    pose_correctives.PRODUCT.run(path)
    cmds.undo()
    assert not cmds.ls(type="poseInterpolator")
    assert not cmds.listConnections("body_bs.elbow_bend", source=True, destination=False)


def test_run_message(new_scene, tmp_path):
    path = _published(tmp_path)
    cmds.file(new=True, force=True)
    _scene()
    message = pose_correctives.PRODUCT.run(path)
    assert message == "Built 1 poseInterpolator with 3 poses, 2 connections"


def test_rerunning_replaces_the_same_named_node(new_scene, tmp_path):
    path = _published(tmp_path)
    shape = _shape()
    cmds.setAttr(f"{shape}.regularization", 0.9)
    cmds.setAttr(f"{shape}.pose[1].poseName", "changed", type="string")
    cmds.disconnectAttr(f"{shape}.output[1]", "body_bs.elbow_bend")

    pose_correctives.PRODUCT.run(path)
    pose_correctives.PRODUCT.run(path)
    assert cmds.ls(type="poseInterpolator") == ["elbow_piShape"]
    snapshot = _snapshot()
    assert snapshot["settings"]["regularization"] == pytest.approx(0.2)
    assert snapshot["poses"][1]["poseName"] == "bend"
    assert len(snapshot["outputs"]) == 4


def test_missing_driver_skips_the_interpolator_with_a_warning(new_scene, tmp_path):
    _scene()
    _interpolator("elbow_pi")
    _interpolator("wrist_pi", drivers=("wrist_jnt",), connect=False)
    path, _ = _publish(tmp_path, "elbow_pi", "wrist_pi")

    cmds.file(new=True, force=True)
    _scene()
    cmds.delete("wrist_jnt")
    with runlog.capture() as run:
        pose_correctives.PRODUCT.run(path)
    assert run.warnings == ["Skipped missing drivers: wrist_jnt"]
    assert cmds.ls(type="poseInterpolator") == ["elbow_piShape"]


def test_missing_blendshape_and_target_are_skipped_with_a_warning(new_scene, tmp_path):
    path = _published(tmp_path)
    cmds.file(new=True, force=True)
    _joints()
    with runlog.capture() as run:
        pose_correctives.PRODUCT.run(path)
    assert run.warnings == ["Skipped missing outputs: body_bs.elbow_bend, body_bs.elbow_up"]
    assert cmds.ls(type="poseInterpolator") == ["elbow_piShape"]

    cmds.file(new=True, force=True)
    _joints()
    body = cmds.polyCube(name="body", ch=False)[0]
    target = cmds.duplicate(body, name="elbow_bend")[0]
    cmds.blendShape(target, body, name="body_bs")
    with runlog.capture() as run:
        pose_correctives.PRODUCT.run(path)
    assert run.warnings == ["Skipped missing outputs: body_bs.elbow_up"]
    assert cmds.listConnections("body_bs.elbow_bend", source=True, destination=False, shapes=True) == ["elbow_piShape"]


def test_ambiguous_driver_raises_and_changes_nothing(new_scene, tmp_path):
    path = _published(tmp_path)
    cmds.file(new=True, force=True)
    _scene()
    cmds.joint(cmds.group(empty=True, name="other"), name="elbow_jnt")
    with pytest.raises(RuntimeError) as info:
        pose_correctives.PRODUCT.run(path)
    assert "elbow_jnt" in str(info.value)
    assert not cmds.ls(type="poseInterpolator")


def test_ambiguous_output_node_raises_and_changes_nothing(new_scene, tmp_path):
    _scene()
    shape = _interpolator()
    cmds.createNode("transform", name="flex")
    cmds.connectAttr(f"{shape}.output[1]", "flex.translateX")
    path, _ = _publish(tmp_path, "elbow_pi")

    cmds.file(new=True, force=True)
    _scene()
    for parent in ("a_grp", "b_grp"):
        cmds.createNode("transform", name="flex", parent=cmds.group(empty=True, name=parent))
    with pytest.raises(RuntimeError) as info:
        pose_correctives.PRODUCT.run(path)
    assert "flex" in str(info.value)
    assert not cmds.ls(type="poseInterpolator")


def test_name_taken_by_another_node_raises_and_changes_nothing(new_scene, tmp_path):
    path = _published(tmp_path)
    cmds.delete("elbow_pi")
    cmds.createNode("transform", name="elbow_pi")
    with pytest.raises(RuntimeError) as info:
        pose_correctives.PRODUCT.run(path)
    assert "elbow_pi" in str(info.value)
    assert not cmds.ls(type="poseInterpolator")


def test_empty_file_is_skipped(new_scene, tmp_path):
    path = pose_correctives.PRODUCT.create(str(tmp_path), "correctives")
    _scene()
    assert logic.run_steps([path]) == [path]
    assert not cmds.ls(type="poseInterpolator")


def test_one_undo_reverts_a_run(new_scene, tmp_path):
    path = _published(tmp_path)
    before = _snapshot()
    cmds.setAttr(f"{_shape()}.regularization", 0.9)
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    pose_correctives.PRODUCT.run(path)
    assert cmds.getAttr(f"{_shape()}.regularization") == pytest.approx(0.2)
    cmds.undo()
    assert cmds.ls(type="poseInterpolator") == ["elbow_piShape"]
    assert cmds.getAttr(f"{_shape()}.regularization") == pytest.approx(0.9)
    assert _snapshot()["outputs"] == before["outputs"]


def test_one_undo_reverts_a_fresh_run(new_scene, tmp_path):
    path = _published(tmp_path)
    cmds.delete("elbow_pi")
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    pose_correctives.PRODUCT.run(path)
    assert cmds.ls(type="poseInterpolator") == ["elbow_piShape"]
    cmds.undo()
    assert not cmds.ls(type="poseInterpolator")
    assert not cmds.listConnections("body_bs.elbow_bend", source=True, destination=False)


# -- publish checks, versions, panel ----------------------------------------


def test_publish_problems(new_scene, tmp_path):
    path = pose_correctives.PRODUCT.create(str(tmp_path), "correctives")
    cmds.select(clear=True)
    (problem,) = versions.publish_problems(path)
    assert "Nothing selected" in problem

    _scene()
    cmds.select("body")
    (problem,) = versions.publish_problems(path)
    assert "poseInterpolator" in problem

    _interpolator()
    cmds.select("elbow_pi")
    assert versions.publish_problems(path) == []
    cmds.select("elbow_jnt")
    assert versions.publish_problems(path) == []


def test_publish_without_interpolators_raises_and_writes_nothing(new_scene, tmp_path):
    path = pose_correctives.PRODUCT.create(str(tmp_path), "correctives")
    _scene()
    cmds.select("elbow_jnt")
    with pytest.raises(RuntimeError):
        versions.publish_action(path).fn()
    assert os.path.getsize(path) == 0


def test_republishing_adds_a_version_only_on_change(new_scene, tmp_path):
    path = _published(tmp_path)
    cmds.select("elbow_pi")
    assert versions.publish_action(path).fn().endswith("v001")
    cmds.setAttr(f"{_shape()}.outputSmoothing", 0.6)
    assert versions.publish_action(path).fn().endswith("v002")


def test_panel_describes_the_interpolators(new_scene, tmp_path):
    _scene()
    _interpolator("elbow_pi")
    _interpolator("wrist_pi", drivers=("wrist_jnt",), connect=False)
    path, _ = _publish(tmp_path, "elbow_pi", "wrist_pi")
    assert pose_correctives.PRODUCT.panel(path).info == [
        "2 poseInterpolators, 6 poses",
        "Drivers: elbow_jnt, wrist_jnt",
        "Drives: body_bs",
    ]
