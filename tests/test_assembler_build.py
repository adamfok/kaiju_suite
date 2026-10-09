"""End to end: publish every rig-data product from one scene into a folder,
then rebuild the rig from that folder in an empty scene with Run All."""

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import logic, versions
from kaiju_suite.tools.assembler.products import (
    animation,
    blendshape,
    deltamush,
    joints,
    material,
    mesh,
    pose,
    skin,
)

FRAME = 6


def _publish(product, folder, name, selection):
    path = product.create(str(folder), name)
    cmds.select(selection)
    assert versions.publish_problems(path) == []
    versions.publish_action(path).fn()
    return path


def _points(node):
    flat = cmds.xform(f"{node}.vtx[*]", query=True, worldSpace=True, translation=True)
    return [flat[i : i + 3] for i in range(0, len(flat), 3)]


def _source_rig(folder):
    cmds.select(clear=True)
    root = cmds.joint(name="root", position=(0, 0, 0))
    cmds.joint(name="mid", position=(0, 2, 0))
    cmds.joint(name="tip", position=(0, 4, 0))
    body = cmds.polyCylinder(name="body", height=4, subdivisionsHeight=8, constructionHistory=False)[0]
    cmds.move(0, 2, 0, body)
    cmds.makeIdentity(body, apply=True, translate=True)

    # Geometry first, before anything deforms it.
    _publish(joints.PRODUCT, folder, "01_skeleton", root)
    _publish(mesh.PRODUCT, folder, "02_body", body)

    target = cmds.duplicate(body, name="body_bulge")[0]
    cmds.scale(1.5, 1, 1.5, f"{target}.vtx[0:19]", relative=True)
    cmds.blendShape(target, body, frontOfChain=True, name="body_bs")
    cmds.setAttr("body_bs.body_bulge", 0.5)
    cmds.skinCluster("root", "mid", "tip", body, toSelectedBones=True, name="body_skin")
    cmds.deltaMush(body, name="body_dm", smoothingIterations=5)
    shader = cmds.shadingNode("lambert", asShader=True, name="body_mat")
    cmds.setAttr(f"{shader}.color", 0.8, 0.2, 0.1, type="double3")
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="body_SG")
    cmds.connectAttr(f"{shader}.outColor", f"{sg}.surfaceShader")
    cmds.sets(body, forceElement=sg)
    cmds.setAttr("root.rotateY", 30)
    cmds.setKeyframe("mid", attribute="rotateZ", time=1, value=0)
    cmds.setKeyframe("mid", attribute="rotateZ", time=10, value=45)

    _publish(blendshape.PRODUCT, folder, "03_blendshapes", body)
    _publish(skin.PRODUCT, folder, "04_skin", body)
    _publish(deltamush.PRODUCT, folder, "05_deltamush", body)
    _publish(material.PRODUCT, folder, "06_material", body)
    _publish(pose.PRODUCT, folder, "07_pose", root)
    _publish(animation.PRODUCT, folder, "08_animation", "mid")
    return body


def test_run_all_rebuilds_the_rig_in_an_empty_scene(new_scene, tmp_path):
    body = _source_rig(tmp_path)
    cmds.currentTime(FRAME)
    expected = _points(body)

    cmds.file(new=True, force=True)
    logic.run_folder(str(tmp_path))
    cmds.currentTime(FRAME)

    assert cmds.ls("root", "mid", "tip", type="joint") == ["root", "mid", "tip"]
    assert cmds.ls(cmds.listHistory("body"), type="skinCluster") == ["body_skin"]
    assert cmds.ls(cmds.listHistory("body"), type="deltaMush") == ["body_dm"]
    assert cmds.getAttr("body_bs.body_bulge") == pytest.approx(0.5)
    assert cmds.getAttr("root.rotateY") == pytest.approx(30)
    assert cmds.keyframe("mid.rotateZ", query=True, keyframeCount=True) == 2
    assert cmds.sets("body_SG", query=True) == ["bodyShape"]
    assert cmds.getAttr("body_mat.color")[0] == pytest.approx((0.8, 0.2, 0.1))

    for got, want in zip(_points("body"), expected):
        assert got == pytest.approx(want, abs=1e-4)
