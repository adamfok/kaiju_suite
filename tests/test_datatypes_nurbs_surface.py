"""NurbsSurface save/load (kaiju_suite.datatypes.nurbs_surface): NURBS surfaces
saved as data and rebuilt as new surfaces. Builder only."""

import pytest
from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite import datatypes
from kaiju_suite.datatypes import nurbs_surface


def _long(nodes):
    return cmds.ls(nodes, long=True)


def _shape(transform):
    return cmds.listRelatives(transform, shapes=True, fullPath=True, type="nurbsSurface")[0]


def _geometry(transform):
    """What the rebuilt surface must match: degrees, forms, knots and
    object-space CVs."""
    shape = _shape(transform)
    fn = om.MFnNurbsSurface(om.MSelectionList().add(shape).getDagPath(0))
    return {
        "degree": (fn.degreeInU, fn.degreeInV),
        "form": (cmds.getAttr(f"{shape}.formU"), cmds.getAttr(f"{shape}.formV")),
        "cv_counts": (fn.numCVsInU, fn.numCVsInV),
        "knots": (list(fn.knotsInU()), list(fn.knotsInV())),
        "cvs": [(p.x, p.y, p.z) for p in fn.cvPositions(om.MSpace.kObject)],
    }


def _assert_same(before, after):
    for key in ("degree", "form", "cv_counts", "knots"):
        assert after[key] == before[key], key
    assert len(after["cvs"]) == len(before["cvs"])
    for a, b in zip(after["cvs"], before["cvs"]):
        assert a == pytest.approx(b, abs=1e-9)


def _round_trip(transform):
    """Gather ``transform``, start a new scene, apply; the geometry before."""
    before = _geometry(transform)
    payload = nurbs_surface.gather(_long(transform))
    cmds.file(new=True, force=True)
    nurbs_surface.apply(payload)
    return before


def test_kind_and_extension():
    assert nurbs_surface.KIND == "nurbs_surface"
    assert nurbs_surface.EXTENSION == ".surface"


@pytest.mark.parametrize("degree", [1, 3])
def test_open_surfaces_round_trip(new_scene, degree):
    plane = cmds.nurbsPlane(name="ribbon", degree=degree, patchesU=4, patchesV=2, lengthRatio=0.5,
                            constructionHistory=False)[0]  # fmt: skip
    cmds.move(0.3, 0.2, -0.1, f"{plane}.cv[1][1]", relative=True)

    before = _round_trip(plane)

    _assert_same(before, _geometry("ribbon"))
    assert _geometry("ribbon")["form"] == (0, 0)


@pytest.mark.parametrize("make", ["sphere", "cylinder", "torus"])
def test_periodic_surfaces_round_trip(new_scene, make):
    if make == "sphere":
        surface = cmds.sphere(name="ball", sections=6, spans=4, constructionHistory=False)[0]
    elif make == "cylinder":
        surface = cmds.cylinder(name="ball", sections=8, spans=3, constructionHistory=False)[0]
    else:
        surface = cmds.torus(name="ball", sections=8, spans=4, constructionHistory=False)[0]
    cmds.move(0.1, 0.4, 0, f"{surface}.cv[2][1]", relative=True)

    before = _round_trip(surface)

    _assert_same(before, _geometry("ball"))
    assert 2 in _geometry("ball")["form"]


def test_degree_1_periodic_surface_round_trips(new_scene):
    surface = cmds.cylinder(name="tube", degree=1, sections=6, spans=2, constructionHistory=False)[0]

    before = _round_trip(surface)

    _assert_same(before, _geometry("tube"))


def test_apply_restores_the_transform_and_display_overrides(new_scene):
    plane = cmds.nurbsPlane(name="ribbon", constructionHistory=False)[0]
    cmds.xform(plane, translation=(1, 2, 3), rotation=(10, 20, 30), scale=(1, 2, 3))
    cmds.setAttr(f"{plane}.rotateOrder", 4)
    shape = _shape(plane)
    cmds.setAttr(f"{shape}.overrideEnabled", True)
    cmds.setAttr(f"{shape}.overrideDisplayType", 2)
    cmds.setAttr(f"{shape}.overrideRGBColors", True)
    cmds.setAttr(f"{shape}.overrideColorRGB", 1, 0.5, 0)

    _round_trip(plane)

    assert cmds.getAttr("ribbon.translate")[0] == pytest.approx((1, 2, 3))
    assert cmds.getAttr("ribbon.rotate")[0] == pytest.approx((10, 20, 30))
    assert cmds.getAttr("ribbon.scale")[0] == pytest.approx((1, 2, 3))
    assert cmds.getAttr("ribbon.rotateOrder") == 4
    shape = _shape("ribbon")
    assert cmds.getAttr(f"{shape}.overrideEnabled")
    assert cmds.getAttr(f"{shape}.overrideDisplayType") == 2
    assert cmds.getAttr(f"{shape}.overrideRGBColors")
    assert cmds.getAttr(f"{shape}.overrideColorRGB")[0] == pytest.approx((1, 0.5, 0))


def test_apply_names_the_shape_after_the_transform_and_shades_it(new_scene):
    plane = cmds.nurbsPlane(name="ribbon", constructionHistory=False)[0]
    cmds.rename(_shape(plane), "oddName")

    _round_trip(plane)

    assert cmds.listRelatives("ribbon", shapes=True) == ["ribbonShape"]
    assert "ribbonShape" in (cmds.sets("initialShadingGroup", query=True) or [])


def test_apply_goes_under_the_saved_parent_by_name(new_scene):
    group = cmds.createNode("transform", name="ribbons_grp")
    plane = cmds.parent(cmds.nurbsPlane(name="ribbon", constructionHistory=False)[0], group)[0]
    payload = nurbs_surface.gather(_long(plane))

    cmds.file(new=True, force=True)
    cmds.createNode("transform", name="ribbons_grp")
    nurbs_surface.apply(payload)

    assert cmds.listRelatives("ribbon", parent=True) == ["ribbons_grp"]


def test_apply_goes_under_the_world_when_the_parent_is_missing(new_scene):
    group = cmds.createNode("transform", name="ribbons_grp")
    plane = cmds.parent(cmds.nurbsPlane(name="ribbon", constructionHistory=False)[0], group)[0]
    payload = nurbs_surface.gather(_long(plane))

    cmds.file(new=True, force=True)
    nurbs_surface.apply(payload)

    assert cmds.listRelatives("ribbon", parent=True) is None


def test_a_selected_surface_under_another_selected_surface_stays_under_it(new_scene):
    sheet = cmds.nurbsPlane(name="sheet", constructionHistory=False)[0]
    child = cmds.parent(cmds.nurbsPlane(name="child", constructionHistory=False)[0], sheet)[0]
    cmds.setAttr(f"{child}.translateX", 2)
    # Child first: gather still creates the parent first.
    payload = nurbs_surface.gather(_long([child, sheet]))

    cmds.file(new=True, force=True)
    cmds.createNode("transform", name="sheet")  # the name is taken: sheet becomes sheet1
    message = nurbs_surface.apply(payload)

    assert cmds.listRelatives("child", parent=True) == ["sheet1"]
    assert cmds.getAttr("child.translateX") == 2
    assert message == "Created 2 NURBS surfaces (names taken, renamed: sheet → sheet1)"


def test_apply_never_changes_existing_surfaces(new_scene):
    plane = cmds.nurbsPlane(name="ribbon", constructionHistory=False)[0]
    payload = nurbs_surface.gather(_long(plane))

    message = nurbs_surface.apply(payload)

    assert message == "Created 1 NURBS surface (names taken, renamed: ribbon → ribbon1)"
    assert cmds.objExists("ribbon") and cmds.objExists("ribbon1")


def test_an_ambiguous_parent_stops_before_creating_anything(new_scene):
    group = cmds.createNode("transform", name="grp")
    plane = cmds.parent(cmds.nurbsPlane(name="ribbon", constructionHistory=False)[0], group)[0]
    payload = nurbs_surface.gather(_long(plane))

    cmds.file(new=True, force=True)
    for holder in ("a", "b"):
        cmds.createNode("transform", name="grp", parent=cmds.createNode("transform", name=holder))
    with pytest.raises(RuntimeError, match="Several nodes"):
        nurbs_surface.apply(payload)

    assert not cmds.ls(type="nurbsSurface")


def test_a_transform_with_several_surface_shapes_keeps_them_all(new_scene):
    plane = cmds.nurbsPlane(name="ribbon", constructionHistory=False)[0]
    other = cmds.sphere(name="other", constructionHistory=False)[0]
    cmds.parent(_shape(other), plane, shape=True, relative=True)
    cmds.delete(other)

    _round_trip(plane)

    assert len(cmds.listRelatives("ribbon", shapes=True, type="nurbsSurface")) == 2


def test_deformed_surfaces_save_the_visible_shape_only(new_scene):
    plane = cmds.nurbsPlane(name="ribbon", constructionHistory=False)[0]
    cmds.cluster(plane)

    payload = nurbs_surface.gather(_long(plane))

    assert len(payload["surfaces"][0]["shapes"]) == 1


def test_a_selected_shape_or_cv_counts_as_its_surface(new_scene):
    plane = cmds.nurbsPlane(name="ribbon", constructionHistory=False)[0]
    sphere = cmds.sphere(name="ball", constructionHistory=False)[0]

    payload = nurbs_surface.gather(_long([_shape(plane), f"{sphere}.cv[0][0]"]))

    assert nurbs_surface.nodes(payload) == ["ribbon", "ball"]


def test_selection_problems(new_scene):
    assert nurbs_surface.selection_problems([]) == ["Nothing selected. Select the NURBS surfaces to publish."]
    locator = cmds.spaceLocator(name="loc")[0]
    assert nurbs_surface.selection_problems(_long(locator)) == [
        "Not NURBS surfaces: loc. Select only NURBS surfaces to publish."
    ]
    plane = cmds.nurbsPlane(name="ribbon", constructionHistory=False)[0]
    assert nurbs_surface.selection_problems(_long(plane)) == []


def test_gather_refuses_what_isnt_a_surface(new_scene):
    locator = cmds.spaceLocator(name="loc")[0]
    with pytest.raises(RuntimeError, match="Not NURBS surfaces: loc"):
        nurbs_surface.gather(_long(locator))
    with pytest.raises(RuntimeError, match="No NURBS surfaces"):
        nurbs_surface.gather([])


def test_describe_and_nodes(new_scene):
    a = cmds.nurbsPlane(name="a", constructionHistory=False)[0]
    b = cmds.sphere(name="b", constructionHistory=False)[0]
    payload = nurbs_surface.gather(_long([a, b]))

    assert nurbs_surface.describe(payload) == ["2 NURBS surfaces", "a, b"]
    assert nurbs_surface.nodes(payload) == ["a", "b"]
    assert nurbs_surface.compare_view(payload) == payload


def test_save_and_load_a_file(tmp_path, new_scene):
    plane = cmds.nurbsPlane(name="ribbon", constructionHistory=False)[0]
    path = str(tmp_path / f"ribbon{nurbs_surface.EXTENSION}")
    datatypes.save(nurbs_surface, path, _long(plane))

    cmds.file(new=True, force=True)
    message = datatypes.load(nurbs_surface, path)

    assert message == "Created 1 NURBS surface"
    assert cmds.objExists("ribbon")


def test_rational_weights_are_not_saved(new_scene):
    plane = cmds.nurbsPlane(name="ribbon", patchesU=2, patchesV=2, constructionHistory=False)[0]
    cmds.setAttr(f"{_shape(plane)}.weights[5]", 2.0)

    payload = nurbs_surface.gather(_long(plane))

    cvs = payload["surfaces"][0]["shapes"][0]["cvs"]
    assert all(len(cv) == 3 for cv in cvs)
