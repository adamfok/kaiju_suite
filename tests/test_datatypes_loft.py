"""Loft save/load (kaiju_suite.datatypes.loft): lofted NURBS surfaces saved
with their loft settings and input curves, and rebuilt with live history.
Builder only."""

import pytest
from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite import datatypes
from kaiju_suite.datatypes import loft


def _long(nodes):
    return cmds.ls(nodes, long=True)


def _curve(name, z, y=0.0, reverse=False):
    points = [(0, y, z), (1, y + 0.5, z), (2, y, z), (3, y, z)]
    return cmds.curve(name=name, degree=3, point=points[::-1] if reverse else points)


def _curves(z_values=(0, 2), names=("crv_a", "crv_b")):
    return [_curve(name, z) for name, z in zip(names, z_values)]


def _ribbon(name="ribbon", curves=None, **kwargs):
    """A surface lofted between ``curves`` (two new ones by default), with history."""
    curves = curves or _curves()
    kwargs.setdefault("degree", 3)
    kwargs.setdefault("sectionSpans", 2)
    surface, node = cmds.loft(*curves, name=name, constructionHistory=True, **kwargs)
    return surface, node


def _shape(transform):
    return cmds.listRelatives(transform, shapes=True, fullPath=True, type="nurbsSurface")[0]


def _driver(surface):
    """The node driving ``surface``'s shape, or ``None``."""
    found = cmds.listConnections(f"{_shape(surface)}.create", source=True, destination=False) or []
    return found[0] if found else None


def _inputs(node):
    """The transforms of the curves feeding loft ``node``, in input order."""
    out = []
    for index in cmds.getAttr(f"{node}.inputCurve", multiIndices=True) or []:
        [shape] = cmds.listConnections(f"{node}.inputCurve[{index}]", source=True, destination=False, shapes=True)
        out.append(cmds.listRelatives(shape, parent=True)[0])
    return out


def _cvs(surface):
    """The surface's world-space CV positions, as Maya evaluates them."""
    fn = om.MFnNurbsSurface(om.MSelectionList().add(_shape(surface)).getDagPath(0))
    return [(round(p.x, 6), round(p.y, 6), round(p.z, 6)) for p in fn.cvPositions(om.MSpace.kWorld)]


def _round_trip(surface, curves):
    """Gather ``surface``, start a new scene with curves of the same names
    (rebuilt flat), apply. Returns the payload."""
    payload = loft.gather(_long(surface))
    names = list(curves)
    cmds.file(new=True, force=True)
    for i, name in enumerate(names):
        _curve(name, 2 * i)
    loft.apply(payload)
    return payload


def test_kind_and_extension():
    assert loft.KIND == "loft"
    assert loft.EXTENSION == ".loft"


# -- gather -----------------------------------------------------------------


def test_gather_saves_the_settings_and_the_curves_in_order(new_scene):
    curves = _curves((0, 2, 4), ("crv_a", "crv_b", "crv_c"))
    surface, node = _ribbon(curves=curves, uniform=False, close=False, degree=1, sectionSpans=3,
                            autoReverse=False, reverseSurfaceNormals=True)  # fmt: skip
    cmds.setAttr(f"{node}.reverse[1]", True)

    [record] = loft.gather(_long(surface))["lofts"]

    assert record["name"] == "ribbon"
    assert record["loft"] == node
    assert [c["name"] for c in record["curves"]] == ["crv_a", "crv_b", "crv_c"]
    assert [c["reverse"] for c in record["curves"]] == [False, True, False]
    assert record["settings"] == {
        "uniform": False,
        "close": False,
        "degree": 1,
        "sectionSpans": 3,
        "autoReverse": False,
        "reverseSurfaceNormals": True,
    }


def test_a_selected_shape_counts_as_its_surface(new_scene):
    surface, _ = _ribbon()

    [record] = loft.gather([_shape(surface)])["lofts"]

    assert record["name"] == "ribbon"


def test_nodes_names_the_surfaces_and_describe_lists_them(new_scene):
    surface, _ = _ribbon()
    payload = loft.gather(_long(surface))

    assert loft.nodes(payload) == ["ribbon"]
    assert loft.describe(payload) == ["1 loft", "ribbon (2 curves)"]


@pytest.mark.parametrize(
    "make, problem",
    [
        (lambda: [], "Nothing selected"),
        (lambda: [cmds.polyCube(name="box")[0]], "Not NURBS surfaces: box"),
        (lambda: [cmds.nurbsPlane(name="flat", constructionHistory=False)[0]], "Not lofted: flat"),
    ],
)
def test_selection_problems(new_scene, make, problem):
    found = loft.selection_problems(_long(make()))

    assert len(found) == 1 and found[0].startswith(problem)


def test_a_loft_from_an_isoparm_can_not_be_published(new_scene):
    plane = cmds.nurbsPlane(name="flat", constructionHistory=False)[0]
    surface, _ = cmds.loft(f"{plane}.v[0.5]", _curve("crv_a", 3), name="ribbon", constructionHistory=True)

    [problem] = loft.selection_problems(_long(surface))
    assert problem.startswith("Loft inputs that aren't curves: ribbon")
    with pytest.raises(RuntimeError):
        loft.gather(_long(surface))


def test_no_problems_for_a_lofted_surface(new_scene):
    surface, _ = _ribbon()

    assert loft.selection_problems(_long(surface)) == []


# -- apply: a new surface ---------------------------------------------------


def test_apply_builds_the_surface_with_live_history(new_scene):
    group = cmds.createNode("transform", name="ribbons_grp")
    surface, _ = _ribbon()
    surface = cmds.parent(surface, group)[0]
    cmds.setAttr(f"{surface}.translateX", 5)
    payload = loft.gather(_long(surface))
    cmds.file(new=True, force=True)
    cmds.createNode("transform", name="ribbons_grp")
    _curves()

    loft.apply(payload)

    assert cmds.listRelatives("ribbon", parent=True) == ["ribbons_grp"]
    assert cmds.getAttr("ribbon.translateX") == 5
    node = _driver("ribbon")
    assert cmds.nodeType(node) == "loft"
    assert _inputs(node) == ["crv_a", "crv_b"]
    assert "initialShadingGroup" in (cmds.listConnections(_shape("ribbon"), type="shadingEngine") or [])
    # Live: moving a curve moves the surface.
    before = _cvs("ribbon")
    cmds.move(0, 3, 0, "crv_a.cv[*]", relative=True)
    assert _cvs("ribbon") != before


def test_the_rebuilt_surface_has_the_same_shape(new_scene):
    surface, _ = _ribbon(curves=[_curve("crv_a", 0), _curve("crv_b", 2, y=1.0)])
    before = _cvs(surface)
    payload = loft.gather(_long(surface))
    cmds.file(new=True, force=True)
    _curve("crv_a", 0), _curve("crv_b", 2, y=1.0)

    loft.apply(payload)

    assert _cvs("ribbon") == before


def test_apply_keeps_the_loft_settings_and_names(new_scene):
    curves = _curves((0, 2, 4), ("crv_a", "crv_b", "crv_c"))
    surface, node = _ribbon(curves=curves, uniform=False, degree=1, sectionSpans=3, autoReverse=False,
                            reverseSurfaceNormals=True)  # fmt: skip
    cmds.rename(node, "ribbon_loft")
    cmds.setAttr("ribbon_loft.reverse[2]", True)

    _round_trip(surface, ["crv_a", "crv_b", "crv_c"])

    assert _driver("ribbon") == "ribbon_loft"
    assert cmds.getAttr("ribbon_loft.uniform") is False
    assert cmds.getAttr("ribbon_loft.degree") == 1
    assert cmds.getAttr("ribbon_loft.sectionSpans") == 3
    assert cmds.getAttr("ribbon_loft.autoReverse") is False
    assert cmds.getAttr("ribbon_loft.reverseSurfaceNormals") is True
    assert cmds.getAttr("ribbon_loft.reverse[2]") is True
    assert _inputs("ribbon_loft") == ["crv_a", "crv_b", "crv_c"]


def test_apply_says_what_it_did(new_scene):
    surface, _ = _ribbon()
    payload = loft.gather(_long(surface))
    cmds.file(new=True, force=True)
    _curves()

    assert loft.apply(payload) == "Built 1 loft"


# -- apply: the surface is already there ------------------------------------


def test_an_existing_surface_keeps_its_node_and_connections_and_gets_new_history(new_scene):
    surface, old = _ribbon()
    payload = loft.gather(_long(surface))
    uuid = cmds.ls(surface, uuid=True)[0]
    follicle = cmds.createNode("follicle")
    cmds.connectAttr(f"{_shape(surface)}.local", f"{follicle}.inputSurface")
    cmds.setAttr(f"{old}.degree", 1)  # the scene's loft differs from the file's

    message = loft.apply(payload)

    assert cmds.ls(uuid, long=True) == _long("ribbon")
    assert cmds.listConnections(f"{follicle}.inputSurface") == ["ribbon"]
    node = _driver("ribbon")
    assert cmds.nodeType(node) == "loft" and cmds.getAttr(f"{node}.degree") == 3
    # The old loft is gone; the new one takes the saved name.
    assert cmds.ls(type="loft") == [node] == [old]
    assert message == "Replaced the history of 1 loft"


def test_an_existing_surface_without_history_gets_lofted(new_scene):
    surface, _ = _ribbon()
    payload = loft.gather(_long(surface))
    cmds.delete(surface, constructionHistory=True)

    loft.apply(payload)

    assert cmds.nodeType(_driver("ribbon")) == "loft"
    assert _inputs(_driver("ribbon")) == ["crv_a", "crv_b"]


def test_the_existing_surfaces_transform_is_left_alone(new_scene):
    surface, _ = _ribbon()
    payload = loft.gather(_long(surface))
    cmds.setAttr(f"{surface}.translateY", 4)

    loft.apply(payload)

    assert cmds.getAttr("ribbon.translateY") == 4


# -- apply: what's missing --------------------------------------------------


def test_a_loft_whose_curves_are_missing_is_skipped_with_a_warning(new_scene, monkeypatch):
    first, _ = _ribbon("ribbon", _curves((0, 2), ("crv_a", "crv_b")))
    second, _ = _ribbon("strap", _curves((5, 7), ("crv_c", "crv_d")))
    payload = loft.gather(_long([first, second]))
    cmds.file(new=True, force=True)
    _curves((0, 2), ("crv_a", "crv_b"))
    _curve("crv_c", 5)
    warnings = []
    monkeypatch.setattr(datatypes, "warning", warnings.append)

    message = loft.apply(payload)

    assert cmds.objExists("ribbon") and not cmds.objExists("strap")
    assert warnings == ["Skipped lofts with missing curves: strap (crv_d)"]
    assert message == "Built 1 loft"


def test_an_ambiguous_curve_name_stops_before_anything_changes(new_scene):
    surface, _ = _ribbon()
    payload = loft.gather(_long(surface))
    cmds.file(new=True, force=True)
    _curves()
    group = cmds.createNode("transform", name="grp")
    other = cmds.parent(_curve("other", 9), group)[0]
    cmds.rename(f"grp|{other}", "crv_a")
    assert len(cmds.ls("crv_a")) == 2

    with pytest.raises(RuntimeError, match="crv_a"):
        loft.apply(payload)
    assert not cmds.objExists("ribbon")
    assert not cmds.ls(type="loft")
