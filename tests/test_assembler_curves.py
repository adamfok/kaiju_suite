import os

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import data, logic, products, versions
from kaiju_suite.tools.assembler.products import curves as curves_product

PRODUCT = curves_product.PRODUCT


def _curve(name, parent=None, periodic=False, degree=3, **values):
    """A curve transform ``name`` with one curve shape, under ``parent``."""
    if periodic:
        node = cmds.circle(name=name, degree=degree, sections=6, constructionHistory=False)[0]
    else:
        points = [(0, 0, 0), (1, 2, 0), (3, 1, 1), (4, 4, 2), (6, 3, 0)]
        node = cmds.curve(name=name, degree=degree, point=points)
    if parent:
        node = cmds.parent(node, parent)[0]
    for attr, value in values.items():
        if isinstance(value, (tuple, list)):
            cmds.setAttr(f"{node}.{attr}", *value)
        else:
            cmds.setAttr(f"{node}.{attr}", value)
    return cmds.ls(node, long=True)[0]


def _values(transform):
    """What a curve is: its transform values and its shapes' curve data."""
    found = {}
    for attr in ("translate", "rotate", "scale"):
        found[attr] = [round(v, 5) for v in cmds.getAttr(f"{transform}.{attr}")[0]]
    found["rotateOrder"] = cmds.getAttr(f"{transform}.rotateOrder")
    shapes = cmds.listRelatives(transform, shapes=True, fullPath=True, type="nurbsCurve") or []
    found["shapes"] = []
    for shape in shapes:
        cvs = cmds.getAttr(f"{shape}.cv[*]")
        found["shapes"].append(
            {
                "degree": cmds.getAttr(f"{shape}.degree"),
                "form": cmds.getAttr(f"{shape}.form"),
                "spans": cmds.getAttr(f"{shape}.spans"),
                "cvs": [[round(v, 5) for v in cv] for cv in cvs],
            }
        )
    return found


def _publish(tmp_path, *selection, name="guides"):
    path = PRODUCT.create(str(tmp_path), name)
    cmds.select(selection)
    message = versions.publish_action(path).fn()
    return path, message


# -- product ----------------------------------------------------------------


def test_curves_is_discovered_and_owns_crv(tmp_path):
    assert PRODUCT in products.discover()
    assert PRODUCT.name == "Curves"
    assert PRODUCT.extensions == (".crv",)
    assert PRODUCT.runnable and PRODUCT.versioned
    path = PRODUCT.creators[0].fn(str(tmp_path), "guides", None)
    assert path == str(tmp_path / "guides.crv") and os.path.getsize(path) == 0
    assert products.product_for(path) is PRODUCT


# -- publish and run --------------------------------------------------------


def test_round_trip_restores_curves(new_scene, tmp_path):
    grp = cmds.createNode("transform", name="guides_grp")
    spine = _curve("spine_crv", grp, translate=(1, 2, 3), rotate=(10, 20, 30), scale=(1, 2, 1), rotateOrder=2)
    ring = _curve("ring_crv", periodic=True, translate=(0, 5, 0))
    linear = _curve("linear_crv", degree=1)
    before = [_values(c) for c in (spine, ring, linear)]
    path, message = _publish(tmp_path, spine, ring, linear)
    assert message == "Published Curves guides.crv v001"

    cmds.file(new=True, force=True)
    cmds.createNode("transform", name="guides_grp")
    logic.run_steps([path])

    after = ["|guides_grp|spine_crv", "|ring_crv", "|linear_crv"]
    assert [_values(c) for c in after] == before
    assert cmds.getAttr("|ring_crv|ring_crvShape.form") == 2
    assert cmds.listRelatives("|guides_grp|spine_crv", shapes=True) == ["spine_crvShape"]


def test_a_selected_shape_stands_for_its_curve(new_scene, tmp_path):
    spine = _curve("spine_crv")
    shape = cmds.listRelatives(spine, shapes=True, fullPath=True)[0]
    path, _ = _publish(tmp_path, shape, spine)
    assert [r["name"] for r in data.read(path, "curves")["curves"]] == ["spine_crv"]


def test_curves_under_selected_curves_keep_their_parent(new_scene, tmp_path):
    parent = _curve("a_crv", translate=(1, 0, 0))
    child = _curve("b_crv", parent, translate=(0, 1, 0))
    # Child selected first: it's still created after its parent.
    path, _ = _publish(tmp_path, child, parent)

    PRODUCT.run(path)
    assert cmds.objExists("|a_crv1|b_crv1")
    assert cmds.getAttr("|a_crv1|b_crv1.translateY") == 1


def test_several_shapes_are_kept(new_scene, tmp_path):
    a = _curve("a_crv")
    b = _curve("b_crv", periodic=True)
    shape = cmds.listRelatives(b, shapes=True, fullPath=True)[0]
    cmds.parent(shape, a, shape=True, relative=True)
    before = _values(a)
    path, _ = _publish(tmp_path, a)

    cmds.file(new=True, force=True)
    PRODUCT.run(path)
    assert _values("|a_crv") == before


def test_running_twice_makes_numbered_copies(new_scene, tmp_path):
    spine = _curve("spine_crv", translate=(1, 2, 3))
    before = _values(spine)
    path, _ = _publish(tmp_path, spine)

    message = PRODUCT.run(path)
    assert "1 curve" in message and "spine_crv1" in message
    assert _values(spine) == before
    assert _values("|spine_crv1") == before


def test_parent_missing_from_the_scene_means_world(new_scene, tmp_path):
    grp = cmds.createNode("transform", name="guides_grp")
    spine = _curve("spine_crv", grp)
    path, _ = _publish(tmp_path, spine)
    saved = data.read(path, "curves")["curves"][0]
    assert saved["parent"] == "guides_grp" and saved["parent_index"] is None

    cmds.file(new=True, force=True)
    PRODUCT.run(path)
    assert cmds.objExists("|spine_crv")


def test_ambiguous_outside_parent_creates_nothing(new_scene, tmp_path):
    grp = cmds.createNode("transform", name="guides_grp")
    spine = _curve("spine_crv", grp)
    path, _ = _publish(tmp_path, spine)

    cmds.file(new=True, force=True)
    for group in ("a", "b"):
        cmds.createNode("transform", name="guides_grp", parent=cmds.createNode("transform", name=group))
    with pytest.raises(RuntimeError) as info:
        PRODUCT.run(path)
    assert "guides_grp" in str(info.value)
    assert not cmds.ls(type="nurbsCurve")


def test_empty_file_is_skipped(new_scene, tmp_path):
    path = PRODUCT.create(str(tmp_path), "guides")
    assert logic.run_steps([path]) == [path]
    assert not cmds.ls(type="nurbsCurve")


def test_one_undo_reverts_a_run(new_scene, tmp_path):
    a = _curve("a_crv")
    b = _curve("b_crv", a)
    ring = _curve("ring_crv", periodic=True)
    path, _ = _publish(tmp_path, a, b, ring)
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    PRODUCT.run(path)
    assert len(cmds.ls(type="nurbsCurve")) == 3
    cmds.undo()
    assert not cmds.ls(type="nurbsCurve")
    assert not cmds.ls("a_crv", "b_crv", "ring_crv")


# -- publish checks and versions --------------------------------------------


def test_publish_problems(new_scene, tmp_path):
    path = PRODUCT.create(str(tmp_path), "guides")
    cmds.select(clear=True)
    (problem,) = versions.publish_problems(path)
    assert "Nothing selected" in problem

    cmds.select(cmds.createNode("transform", name="empty_grp"))
    (problem,) = versions.publish_problems(path)
    assert "empty_grp" in problem and "curve" in problem.lower()

    cmds.select(_curve("spine_crv"))
    assert versions.publish_problems(path) == []


def test_publish_without_curves_raises_and_writes_nothing(new_scene, tmp_path):
    path = PRODUCT.create(str(tmp_path), "guides")
    cmds.select(cmds.createNode("transform"))
    with pytest.raises(RuntimeError):
        versions.publish_action(path).fn()
    assert os.path.getsize(path) == 0


def test_republishing_adds_a_version_only_on_change(new_scene, tmp_path):
    spine = _curve("spine_crv")
    path, message = _publish(tmp_path, spine)
    assert message.endswith("v001")

    cmds.select(spine)
    assert versions.publish_action(path).fn().endswith("v001")

    cmds.setAttr(f"{spine}.cv[2]", 9, 9, 9)
    cmds.select(spine)
    assert versions.publish_action(path).fn().endswith("v002")


def test_panel_describes_the_curves(new_scene, tmp_path):
    spine = _curve("spine_crv")
    ring = _curve("ring_crv", periodic=True)
    path, _ = _publish(tmp_path, spine, ring)
    assert PRODUCT.panel(path).info == ["2 curves", "spine_crv, ring_crv"]
