"""ControlShape save/load (kaiju_suite.datatypes.controlshape), without the Assembler.

The Assembler's ControlShape product (tests/test_assembler_controlshape.py)
goes through this module.
"""

import pytest
from maya import cmds

from kaiju_suite import datatypes
from kaiju_suite.datatypes import controlshape


def _circle_ctrl(name="ctrl"):
    node = cmds.rename(cmds.circle(normal=(0, 1, 0), radius=2, constructionHistory=False)[0], name)
    cmds.rename(_shapes(node)[0], f"{name}Shape")
    return cmds.ls(node, long=True)[0]


def _square_ctrl(name="ctrl"):
    points = [(-1, 0, -1), (1, 0, -1), (1, 0, 1), (-1, 0, 1), (-1, 0, -1)]
    node = cmds.curve(name=name, degree=1, point=points)
    cmds.rename(_shapes(node)[0], f"{name}Shape")
    return cmds.ls(node, long=True)[0]


def _shapes(node):
    return cmds.listRelatives(node, shapes=True, fullPath=True, type="nurbsCurve") or []


def test_kind_and_extension():
    assert controlshape.KIND == "controlShape"
    assert controlshape.EXTENSION == ".ctrl"


def test_gather_then_apply_replaces_the_shapes(new_scene):
    ctrl = _circle_ctrl()
    payload = controlshape.gather([ctrl])
    assert [r["name"] for r in payload["controls"]] == ["ctrl"]

    cmds.delete(ctrl)
    ctrl = _square_ctrl()
    lines = []
    message = controlshape.apply(payload, info=lines.append)

    assert message == "Replaced the shapes of 1 control"
    assert lines == ["ctrl: replaced with 1 curve shape"]
    (shape,) = _shapes(ctrl)
    assert cmds.getAttr(f"{shape}.degree") == 3


def test_a_selected_shape_stands_for_its_control(new_scene):
    a, b = _circle_ctrl("a"), _circle_ctrl("b")
    payload = controlshape.gather([_shapes(a)[0], a, b])
    assert controlshape.nodes(payload) == ["a", "b"]


def test_gather_needs_curve_shapes(new_scene):
    bare = cmds.createNode("transform", name="bare")
    with pytest.raises(RuntimeError, match="bare"):
        controlshape.gather(cmds.ls(bare, long=True))


def test_apply_skips_missing_controls_with_a_warning(new_scene, monkeypatch):
    payload = controlshape.gather([_circle_ctrl(), _circle_ctrl("other")])
    cmds.delete("other")
    warnings = []
    monkeypatch.setattr(datatypes, "warning", warnings.append)

    assert controlshape.apply(payload) == "Replaced the shapes of 1 control"
    assert warnings == ["Skipped missing controls: other"]


def test_selection_problems(new_scene):
    assert controlshape.selection_problems([]) == [
        "Nothing selected. Select the controls whose shapes to publish."
    ]
    bare = cmds.createNode("transform", name="bare")
    (problem,) = controlshape.selection_problems([_circle_ctrl(), cmds.ls(bare, long=True)[0]])
    assert "bare" in problem and "curve" in problem.lower()
    assert controlshape.selection_problems([_circle_ctrl("other")]) == []


def test_describe_and_nodes(new_scene):
    payload = controlshape.gather([_circle_ctrl(), _circle_ctrl("other")])
    assert controlshape.describe(payload) == ["2 controls", "2 curve shapes", "Controls: ctrl, other"]
    assert controlshape.nodes(payload) == ["ctrl", "other"]
    assert controlshape.compare_view(payload) == payload


def test_save_and_load_a_file(new_scene, tmp_path):
    ctrl = _circle_ctrl()
    path = str(tmp_path / "ctrls.ctrl")
    datatypes.save(controlshape, path, [ctrl])
    cmds.delete(_shapes(ctrl))

    assert datatypes.load(controlshape, path) == "Replaced the shapes of 1 control"
    assert len(_shapes(ctrl)) == 1
