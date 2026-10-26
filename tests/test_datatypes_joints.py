"""Joints save/load (kaiju_suite.datatypes.joints)."""

import pytest
from maya import cmds

from kaiju_suite.datatypes import joints


def _chain():
    cmds.select(clear=True)
    made = [cmds.joint(name=name, position=(i * 2, 0, 0)) for i, name in enumerate(("hip", "knee", "ankle"))]
    cmds.select(clear=True)
    return made


def test_kind_and_extension():
    assert joints.KIND == "joints"
    assert joints.EXTENSION == ".jnt"


def test_gather_then_apply_rebuilds_the_chain(new_scene):
    hip = _chain()[0]
    cmds.setAttr("knee.jointOrient", 0, 0, 30)
    payload = joints.gather(cmds.ls(hip, long=True))
    assert [r["name"] for r in payload["joints"]] == ["hip", "knee", "ankle"]

    cmds.file(new=True, force=True)
    message = joints.apply(payload)

    assert message == "Created 3 joints"
    assert cmds.listRelatives("ankle", parent=True) == ["knee"]
    assert cmds.getAttr("knee.jointOrient")[0] == pytest.approx((0.0, 0.0, 30.0))


def test_selection_problems(new_scene):
    assert joints.selection_problems([]) == ["Nothing selected. Select the root joints to publish."]
    cube = cmds.polyCube(name="box")[0]
    assert joints.selection_problems(cmds.ls(cube, long=True)) == [
        "No joints selected. Select the root joints to publish."
    ]
    assert joints.selection_problems(cmds.ls(_chain()[0], long=True)) == []


def test_describe_and_nodes(new_scene):
    payload = joints.gather(cmds.ls(_chain()[0], long=True))
    assert joints.describe(payload) == ["3 joints", "Roots: hip"]
    assert joints.nodes(payload) == ["hip", "knee", "ankle"]
