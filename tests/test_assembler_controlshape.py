import os

import pytest
from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.tools.assembler import data, logic, products, versions
from kaiju_suite.tools.assembler.products import controlshape


def _circle_ctrl(name="ctrl", parent=None):
    """A control with one circle shape, centered on its own origin."""
    node = cmds.circle(normal=(0, 1, 0), radius=2, constructionHistory=False)[0]
    if parent:
        node = cmds.parent(node, parent)[0]
    node = cmds.rename(node, name)
    cmds.rename(_shapes(node)[0], f"{name}Shape")
    return cmds.ls(node, long=True)[0]


def _square_ctrl(name="ctrl"):
    """A control with a linear square shape: 5 CVs, unlike the circle's 11."""
    points = [(-1, 0, -1), (1, 0, -1), (1, 0, 1), (-1, 0, 1), (-1, 0, -1)]
    node = cmds.curve(name=name, degree=1, point=points)
    cmds.rename(_shapes(node)[0], f"{name}Shape")
    return cmds.ls(node, long=True)[0]


def _shapes(node):
    return cmds.listRelatives(node, shapes=True, fullPath=True, type="nurbsCurve") or []


def _cvs(shape, space="object"):
    """Every CV, including the ones a periodic curve repeats (``cv[*]`` skips those)."""
    curve = om.MFnNurbsCurve(om.MSelectionList().add(shape).getDagPath(0))
    space = om.MSpace.kWorld if space == "world" else om.MSpace.kObject
    return [[p.x, p.y, p.z] for p in curve.cvPositions(space)]


def _publish(tmp_path, *selection, name="ctrls"):
    path = controlshape.PRODUCT.create(str(tmp_path), name)
    cmds.select(selection)
    message = versions.publish_action(path).fn()
    return path, message


def _saved(path):
    return {c["name"]: c["shapes"] for c in data.read(path, "controlShape")["controls"]}


def _assert_points(got, want):
    assert len(got) == len(want)
    for g, w in zip(got, want):
        assert g == pytest.approx(w, abs=1e-6)


# -- product ----------------------------------------------------------------


def test_controlshape_is_discovered_and_owns_ctrl(tmp_path):
    assert controlshape.PRODUCT in products.discover()
    assert controlshape.PRODUCT.name == "ControlShape"
    assert controlshape.PRODUCT.extensions == (".ctrl",)
    assert controlshape.PRODUCT.order == 120
    assert controlshape.PRODUCT.runnable and controlshape.PRODUCT.versioned
    path = controlshape.PRODUCT.creators[0].fn(str(tmp_path), "ctrls", None)
    assert path == str(tmp_path / "ctrls.ctrl") and os.path.getsize(path) == 0
    assert products.product_for(path) is controlshape.PRODUCT


# -- publish ----------------------------------------------------------------


def test_publish_saves_cvs_in_the_controls_space(new_scene, tmp_path):
    ctrl = _circle_ctrl()
    shape = _shapes(ctrl)[0]
    local = _cvs(shape)
    cmds.xform(ctrl, translation=(5, 1, 2), rotation=(0, 45, 30), scale=(2, 2, 2))
    path, message = _publish(tmp_path, ctrl)
    assert message == "Published ControlShape ctrls.ctrl v001"

    (saved,) = _saved(path)["ctrl"]
    assert saved["name"] == "ctrlShape"
    assert saved["degree"] == 3 and saved["form"] == 2
    assert len(saved["knots"]) == 13
    _assert_points(saved["cvs"], local)


def test_publish_saves_cvs_relative_to_the_pivot(new_scene, tmp_path):
    ctrl = _circle_ctrl()
    local = _cvs(_shapes(ctrl)[0])
    cmds.xform(ctrl, objectSpace=True, rotatePivot=(1, 0, 3))
    path, _ = _publish(tmp_path, ctrl)
    (saved,) = _saved(path)["ctrl"]
    _assert_points(saved["cvs"], [[x - 1, y, z - 3] for x, y, z in local])


def test_publish_saves_every_curve_shape_and_its_display(new_scene, tmp_path):
    ctrl = _circle_ctrl()
    extra = _square_ctrl("extra")
    extra_shape = _shapes(extra)[0]
    cmds.parent(extra_shape, ctrl, shape=True, relative=True)
    cmds.delete(extra)
    first = _shapes(ctrl)[0]
    cmds.setAttr(f"{first}.overrideEnabled", True)
    cmds.setAttr(f"{first}.overrideColor", 13)
    cmds.setAttr(f"{first}.lineWidth", 3)
    cmds.spaceLocator(name="loc")
    loc_shape = cmds.listRelatives("loc", shapes=True)[0]
    cmds.parent(loc_shape, ctrl, shape=True, relative=True)

    path, _ = _publish(tmp_path, ctrl)
    shapes = _saved(path)["ctrl"]
    assert [s["name"] for s in shapes] == ["ctrlShape", "extraShape"]
    assert shapes[0]["overrideEnabled"] is True
    assert shapes[0]["overrideColor"] == 13
    assert shapes[0]["lineWidth"] == pytest.approx(3)
    assert shapes[1]["degree"] == 1 and len(shapes[1]["cvs"]) == 5


def test_selecting_a_shape_counts_as_its_control(new_scene, tmp_path):
    a = _circle_ctrl("a")
    b = _circle_ctrl("b")
    path, _ = _publish(tmp_path, _shapes(a)[0], a, b)
    assert list(_saved(path)) == ["a", "b"]


def test_publish_stores_shortest_unique_names(new_scene, tmp_path):
    a = _circle_ctrl("ctrl", cmds.createNode("transform", name="L"))
    b = _circle_ctrl("ctrl", cmds.createNode("transform", name="R"))
    path, _ = _publish(tmp_path, a, b)
    assert list(_saved(path)) == ["L|ctrl", "R|ctrl"]


def test_publish_problems(new_scene, tmp_path):
    path = controlshape.PRODUCT.create(str(tmp_path), "ctrls")
    cmds.select(clear=True)
    (problem,) = versions.publish_problems(path)
    assert "Nothing selected" in problem

    bare = cmds.createNode("transform", name="bare")
    cmds.select(_circle_ctrl(), bare)
    (problem,) = versions.publish_problems(path)
    assert "bare" in problem and "curve" in problem.lower()

    cmds.select(_circle_ctrl("other"))
    assert versions.publish_problems(path) == []


# -- run --------------------------------------------------------------------


def test_run_replaces_shapes_with_a_different_cv_count(new_scene, tmp_path):
    ctrl = _circle_ctrl()
    circle = _cvs(_shapes(ctrl)[0])
    path, _ = _publish(tmp_path, ctrl)
    cmds.delete(ctrl)
    ctrl = _square_ctrl("ctrl")

    message = controlshape.PRODUCT.run(path)
    assert message == "Replaced the shapes of 1 control"
    (shape,) = _shapes(ctrl)
    assert shape.endswith("|ctrl|ctrlShape")
    assert cmds.getAttr(f"{shape}.degree") == 3
    assert cmds.getAttr(f"{shape}.form") == 2
    _assert_points(_cvs(shape), circle)


def test_run_follows_the_controls_new_position(new_scene, tmp_path):
    ctrl = _circle_ctrl()
    path, _ = _publish(tmp_path, ctrl)
    cmds.xform(ctrl, translation=(10, 0, 0), rotation=(90, 0, 0))
    expected = _cvs(_shapes(ctrl)[0], "world")
    cmds.delete(_shapes(ctrl))

    controlshape.PRODUCT.run(path)
    _assert_points(_cvs(_shapes(ctrl)[0], "world"), expected)
    assert expected[0][0] > 9  # moved with the control, not left at the origin


def test_run_follows_the_controls_pivot(new_scene, tmp_path):
    ctrl = _circle_ctrl()
    local = _cvs(_shapes(ctrl)[0])
    path, _ = _publish(tmp_path, ctrl)
    cmds.xform(ctrl, objectSpace=True, rotatePivot=(0, 2, 0))

    controlshape.PRODUCT.run(path)
    _assert_points(_cvs(_shapes(ctrl)[0]), [[x, y + 2, z] for x, y, z in local])


def test_run_restores_every_shape_and_its_display_and_keeps_other_shapes(new_scene, tmp_path):
    ctrl = _circle_ctrl()
    extra = _square_ctrl("extra")
    cmds.parent(_shapes(extra)[0], ctrl, shape=True, relative=True)
    cmds.delete(extra)
    first = _shapes(ctrl)[0]
    cmds.setAttr(f"{first}.overrideEnabled", True)
    cmds.setAttr(f"{first}.overrideRGBColors", True)
    cmds.setAttr(f"{first}.overrideColorRGB", 1, 0.5, 0)
    cmds.setAttr(f"{first}.lineWidth", 2)
    path, _ = _publish(tmp_path, ctrl)

    cmds.delete(_shapes(ctrl))
    cmds.parent(_shapes(_circle_ctrl("tmp"))[0], ctrl, shape=True, relative=True)
    cmds.delete("tmp")
    loc_shape = cmds.listRelatives(cmds.spaceLocator(name="loc")[0], shapes=True)[0]
    cmds.parent(loc_shape, ctrl, shape=True, relative=True)

    controlshape.PRODUCT.run(path)
    shapes = _shapes(ctrl)
    assert [s.rsplit("|", 1)[-1] for s in shapes] == ["ctrlShape", "extraShape"]
    assert cmds.getAttr(f"{shapes[0]}.overrideEnabled") is True
    assert cmds.getAttr(f"{shapes[0]}.overrideRGBColors") is True
    assert cmds.getAttr(f"{shapes[0]}.overrideColorRGB")[0] == pytest.approx((1, 0.5, 0))
    assert cmds.getAttr(f"{shapes[0]}.lineWidth") == pytest.approx(2)
    assert len(_cvs(shapes[1])) == 5
    assert cmds.listRelatives(ctrl, shapes=True, type="locator")


def test_round_trip_into_a_new_scene(new_scene, tmp_path):
    path, _ = _publish(tmp_path, _circle_ctrl())
    cmds.file(new=True, force=True)
    ctrl = _square_ctrl("ctrl")
    logic.run_steps([path])
    assert cmds.getAttr(f"{_shapes(ctrl)[0]}.degree") == 3


def test_missing_control_raises_and_changes_nothing(new_scene, tmp_path):
    ctrl = _circle_ctrl()
    other = _circle_ctrl("other")
    path, _ = _publish(tmp_path, ctrl, other)
    cmds.delete(other, _shapes(ctrl))
    square = _shapes(_square_ctrl("sq"))[0]
    cmds.parent(square, ctrl, shape=True, relative=True)

    with pytest.raises(data.MissingNodesError) as info:
        controlshape.PRODUCT.run(path)
    assert "other" in str(info.value)
    assert len(_cvs(_shapes(ctrl)[0])) == 5


def test_ambiguous_name_raises_and_changes_nothing(new_scene, tmp_path):
    ctrl = _circle_ctrl()
    path, _ = _publish(tmp_path, ctrl)
    cmds.delete(_shapes(ctrl))
    _circle_ctrl("ctrl", cmds.createNode("transform", name="grp"))

    with pytest.raises(RuntimeError) as info:
        controlshape.PRODUCT.run(path)
    assert "ctrl" in str(info.value)
    assert not _shapes(ctrl)


def test_empty_file_is_skipped(new_scene, tmp_path):
    ctrl = _square_ctrl()
    path = controlshape.PRODUCT.create(str(tmp_path), "ctrls")
    assert logic.run_steps([path]) == [path]
    assert len(_cvs(_shapes(ctrl)[0])) == 5


def test_one_undo_reverts_a_run(new_scene, tmp_path):
    path, _ = _publish(tmp_path, _circle_ctrl())
    cmds.file(new=True, force=True)
    ctrl = _square_ctrl("ctrl")
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    controlshape.PRODUCT.run(path)
    assert len(_cvs(_shapes(ctrl)[0])) == 11
    cmds.undo()
    (shape,) = _shapes(ctrl)
    assert len(_cvs(shape)) == 5


# -- versions and panel -----------------------------------------------------


def test_republishing_adds_a_version_only_on_change(new_scene, tmp_path):
    ctrl = _circle_ctrl()
    path, message = _publish(tmp_path, ctrl)
    assert message.endswith("v001")
    cmds.select(ctrl)
    assert versions.publish_action(path).fn().endswith("v001")
    cmds.move(0, 1, 0, f"{_shapes(ctrl)[0]}.cv[0]", relative=True)
    assert versions.publish_action(path).fn().endswith("v002")


def test_panel_describes_the_controls(new_scene, tmp_path):
    path, _ = _publish(tmp_path, _circle_ctrl(), _circle_ctrl("other"))
    assert controlshape.PRODUCT.panel(path).info == ["2 controls", "2 curve shapes", "Controls: ctrl, other"]
