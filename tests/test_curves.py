import pytest
from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.core import curves, nodes


def _cvs(shape):
    curve = om.MFnNurbsCurve(om.MSelectionList().add(shape).getDagPath(0))
    return [[p.x, p.y, p.z] for p in curve.cvPositions(om.MSpace.kObject)]


def _circle(name="ctrl"):
    return cmds.circle(name=name, normal=(0, 1, 0), radius=2, constructionHistory=False)[0]


def test_shapes_lists_the_curve_shapes(new_scene):
    ctrl = _circle()
    cmds.spaceLocator(name="loc")
    cmds.parent(cmds.listRelatives("loc", shapes=True)[0], ctrl, shape=True, relative=True)

    assert curves.shapes(ctrl) == [cmds.ls("ctrlShape", long=True)[0]]


def test_a_record_rebuilds_the_same_curve(new_scene):
    ctrl = _circle()
    shape = curves.shapes(ctrl)[0]
    cmds.setAttr(f"{shape}.overrideEnabled", True)
    cmds.setAttr(f"{shape}.overrideColor", 13)
    cmds.setAttr(f"{shape}.lineWidth", 3)
    record = curves.record(shape)
    other = cmds.createNode("transform", name="other")

    built = curves.build(other, record)

    assert cmds.listRelatives(built, parent=True) == ["other"]
    assert cmds.getAttr(f"{built}.form") == cmds.getAttr(f"{shape}.form")
    for got, want in zip(_cvs(built), _cvs(shape)):
        assert got == pytest.approx(want)
    assert cmds.getAttr(f"{built}.overrideColor") == 13
    assert cmds.getAttr(f"{built}.lineWidth") == 3


def test_a_record_is_relative_to_the_pivot(new_scene):
    shape = curves.shapes(_circle())[0]
    record = curves.record(shape, pivot=(1, 0, 0))
    other = cmds.createNode("transform", name="other")

    built = curves.build(other, record, pivot=(0, 5, 0))

    for got, want in zip(_cvs(built), _cvs(shape)):
        assert got == pytest.approx([want[0] - 1, want[1] + 5, want[2]])


def test_build_without_display_settings_keeps_maya_defaults(new_scene):
    record = {"name": "box", "degree": 1, "form": 0, "knots": [0, 1, 2], "cvs": [[0, 0, 0], [1, 0, 0], [1, 1, 0]]}
    parent = cmds.createNode("transform", name="ctrl")

    built = curves.build(parent, record)

    assert _cvs(built) == [[0, 0, 0], [1, 0, 0], [1, 1, 0]]
    assert not cmds.getAttr(f"{built}.overrideEnabled")


def test_build_picks_a_free_name(new_scene):
    shape = curves.shapes(_circle())[0]
    record = curves.record(shape)
    other = cmds.createNode("transform", name="other")

    built = curves.build(other, record)

    assert cmds.ls(built) == ["ctrlShape1"]


def test_unique_name_numbers_a_taken_name(new_scene):
    cmds.createNode("transform", name="spine_jnt")
    cmds.createNode("transform", name="joint1")

    assert nodes.unique_name("free") == "free"
    assert nodes.unique_name("spine_jnt") == "spine_jnt1"
    assert nodes.unique_name("joint1") == "joint2"
