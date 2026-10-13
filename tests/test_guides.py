"""Guide building in core (kaiju_suite.core.guides), shared by the Guide Tool
and the Assembler's Guide items. The Guide Tool's behaviour is covered in
tests/test_guide_tool.py; this covers what core adds for saving and
rebuilding a chain's layout."""

import pytest
from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.core import guides

POSITIONS = [(0, 0, 0), (3, 1, 0.5), (6, -1, 0), (10, 0, 0)]
UP = (5, 6, 0)


def _pos(node):
    return [round(v, 5) for v in cmds.xform(node, query=True, worldSpace=True, translation=True)]


def test_build_at_puts_every_guide_where_given(new_scene):
    group = guides.build_at("arm", POSITIONS, UP, aim="-x", up="z")
    found = guides.guides(group)
    assert [_pos(g) for g in found["chain"]] == [list(map(float, p)) for p in POSITIONS]
    assert _pos(found["up"]) == [5.0, 6.0, 0.0]
    assert len(guides.joints(group)) == 4
    assert cmds.getAttr(f"{group}.previewAxes") == "-x z"


def test_build_at_joints_follow_the_guides(new_scene):
    group = guides.build_at("arm", POSITIONS, UP)
    end_joint = guides.joints(group)[-1]
    end = om.MVector(cmds.xform(end_joint, query=True, worldSpace=True, translation=True))
    assert (end - om.MVector(10, 0, 0)).length() < 1e-4


def test_layout_reads_back_what_build_at_made(new_scene):
    group = guides.build_at("arm", POSITIONS, UP, aim="y", up="-z")
    assert guides.layout(group) == {
        "name": "arm",
        "aim": "y",
        "up": "-z",
        "guides": [list(map(float, p)) for p in POSITIONS],
        "up_guide": [5.0, 6.0, 0.0],
    }


def test_layout_follows_moved_guides(new_scene):
    group = guides.build_guides("leg", 1, start=(0, 0, 0), end=(0, -8, 0))
    cmds.xform(guides.guides(group)["chain"][1], worldSpace=True, translation=(0.5, -4, 1))
    assert guides.layout(group)["guides"][1] == [0.5, -4.0, 1.0]


def test_build_at_needs_two_positions(new_scene):
    with pytest.raises(ValueError, match="2 guides or more"):
        guides.build_at("arm", [(0, 0, 0)], UP)
    assert cmds.ls(type="joint") == []


def test_build_at_refuses_an_up_guide_in_line(new_scene):
    with pytest.raises(ValueError, match="in line"):
        guides.build_at("arm", POSITIONS, (20, 0, 0))
    assert cmds.ls(type="joint") == []


def test_build_at_refuses_names_in_use(new_scene):
    cmds.createNode("transform", name="arm_02_jnt")
    with pytest.raises(ValueError, match="arm_02_jnt"):
        guides.build_at("arm", POSITIONS, UP)
    assert not cmds.objExists("arm_guides_grp")


def test_taken_names_lists_names_in_use(new_scene):
    assert guides.taken_names("arm", 2) == []
    guides.build_at("arm", POSITIONS, UP)
    assert "arm_guides_grp" in guides.taken_names("arm", 2)

