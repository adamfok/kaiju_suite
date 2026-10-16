"""Curves save/load (kaiju_suite.datatypes.curves), without the Assembler.

The Assembler's Curves product (tests/test_assembler_curves.py) goes through
this module, keeping its own ``.crv`` extension; Builder's NurbsCurve items
use ``.curve``. The file contents are the same.
"""

import os
import shutil

import pytest
from maya import cmds

from kaiju_suite import datatypes
from kaiju_suite.datatypes import curves


def _curve(name, parent=None):
    node = cmds.curve(name=name, degree=3, point=[(0, 0, 0), (1, 2, 0), (3, 1, 1), (4, 4, 2)])
    if parent:
        node = cmds.parent(node, parent)[0]
    return cmds.ls(node, long=True)[0]


def test_kind_and_extension():
    assert curves.KIND == "curves"
    assert curves.EXTENSION == ".curve"


def test_gather_then_apply_rebuilds_the_curves(new_scene):
    grp = cmds.createNode("transform", name="guides_grp")
    spine = _curve("spine_crv", grp)
    cmds.setAttr(f"{spine}.translate", 1, 2, 3)
    ring = cmds.ls(cmds.circle(name="ring_crv", constructionHistory=False)[0], long=True)[0]
    payload = curves.gather([spine, ring])
    # Shallower curves first, so a parent curve is created before its children.
    assert [r["name"] for r in payload["curves"]] == ["ring_crv", "spine_crv"]

    cmds.file(new=True, force=True)
    cmds.createNode("transform", name="guides_grp")
    message = curves.apply(payload)

    assert message == "Created 2 curves"
    assert cmds.listRelatives("spine_crv", parent=True) == ["guides_grp"]
    assert cmds.getAttr("spine_crv.translate")[0] == pytest.approx((1.0, 2.0, 3.0))
    assert cmds.getAttr("ring_crvShape.form") == 2


def test_selection_problems(new_scene):
    assert curves.selection_problems([]) == ["Nothing selected. Select the NURBS curves to publish."]
    grp = cmds.ls(cmds.createNode("transform", name="empty_grp"), long=True)
    assert curves.selection_problems(grp) == ["Not NURBS curves: empty_grp. Select only curves to publish."]
    assert curves.selection_problems([_curve("spine_crv")]) == []


def test_gather_refuses_what_isnt_a_curve(new_scene):
    grp = cmds.ls(cmds.createNode("transform", name="empty_grp"), long=True)
    with pytest.raises(RuntimeError, match="Not NURBS curves: empty_grp"):
        curves.gather(grp)


def test_curve_transforms_finds_curves_from_shapes_and_components(new_scene):
    a, b, c = _curve("a_crv"), _curve("b_crv"), _curve("c_crv")
    shape = cmds.listRelatives(b, shapes=True, fullPath=True)[0]
    grp = cmds.ls(cmds.createNode("transform", name="grp"), long=True)[0]

    assert curves.curve_transforms([a, shape, f"{c}.cv[1]", grp, a]) == [a, b, c]


def test_describe_and_nodes(new_scene):
    payload = curves.gather([_curve("spine_crv"), _curve("tail_crv")])
    assert curves.describe(payload) == ["2 curves", "spine_crv, tail_crv"]
    assert curves.nodes(payload) == ["spine_crv", "tail_crv"]


def test_nodes_gather_the_same_payload_again(new_scene):
    spine = _curve("spine_crv")
    payload = curves.gather([spine])
    found, problems = datatypes.resolve_nodes(curves.nodes(payload))
    assert problems == []
    assert curves.gather(found) == payload


def test_compare_view_leaves_out_parent_index(new_scene):
    parent = _curve("a_crv")
    _curve("b_crv", parent)
    payload = curves.gather(cmds.ls("a_crv", "b_crv", long=True))
    view = curves.compare_view(payload)
    assert all("parent_index" not in r for r in view["curves"])
    assert [r["parent"] for r in view["curves"]] == [None, "a_crv"]


def test_save_and_load_through_datatypes(new_scene, tmp_path):
    path = datatypes.save(curves, str(tmp_path / "spine.curve"), [_curve("spine_crv")])
    cmds.file(new=True, force=True)
    assert datatypes.load(curves, path) == "Created 1 curve"
    assert cmds.objExists("spine_crv")
