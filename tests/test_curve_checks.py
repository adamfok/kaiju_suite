"""datatypes.curves.CHECKS: QC checks on given NURBS curves, run by the
Curve Tool's QC tab and before Builder publishes a NurbsCurve item. They
report problems and change nothing."""

from maya import cmds

from kaiju_suite import datatypes
from kaiju_suite.core import checks
from kaiju_suite.datatypes import curves

_POINTS = [(0, 0, 0), (1, 2, 0), (3, 1, 1), (4, 4, 2)]


def _curve(name, parent=None, points=_POINTS, degree=3):
    node = cmds.curve(name=name, degree=degree, point=points)
    cmds.rename(cmds.listRelatives(node, shapes=True)[0], f"{name}Shape")
    if parent:
        node = cmds.parent(node, parent)[0]
    return cmds.ls(node, long=True)[0]


def _long(*nodes):
    return cmds.ls(nodes, long=True)


def _run(key, nodes, **options):
    return checks.get(key, curves.CHECKS).run(nodes=nodes, **options)


def test_the_curve_checks_and_their_defaults():
    assert [c.key for c in curves.CHECKS] == ["duplicate_names", "rational", "history", "degenerate"]
    assert checks.defaults(curves.CHECKS) == {
        "duplicate_names": {"enabled": True},
        "rational": {"enabled": True},
        "history": {"enabled": True},
        "degenerate": {"enabled": True, "tolerance": 0.0001},
    }


def test_every_check_has_a_label_and_description_and_runs_before_publish():
    for check in curves.CHECKS:
        assert check.label and check.description
        assert check.publish
        assert check.fix is None


def test_clean_curves_have_no_problems(new_scene):
    grp = cmds.createNode("transform", name="guides_grp")
    spine = _curve("spine_crv", grp)
    ring = cmds.circle(name="ring_crv", constructionHistory=False)[0]

    found = datatypes.run_qc(curves, _long(spine, ring), checks.defaults(curves.CHECKS))

    assert [(c.key, p) for c, p in found] == [(c.key, []) for c in curves.CHECKS]


# -- duplicate names ----------------------------------------------------------


def test_duplicate_names_finds_curves_sharing_a_name(new_scene):
    for group in ("a_grp", "b_grp"):
        _curve("spine_crv", cmds.createNode("transform", name=group))

    found = _run("duplicate_names", _long("a_grp|spine_crv"))

    assert found == ["a_grp|spine_crv: 2 nodes are called spine_crv"]
    assert checks.selection_of(found[0]) == ["a_grp|spine_crv", "b_grp|spine_crv"]


def test_duplicate_names_finds_a_parent_sharing_a_name(new_scene):
    # Run finds a curve's parent by name; two of them stop it.
    for group in ("a", "b"):
        cmds.createNode("transform", name="guides_grp", parent=cmds.createNode("transform", name=group))
    spine = _curve("spine_crv", "a|guides_grp")

    found = _run("duplicate_names", [spine])

    assert found == ["spine_crv: parent a|guides_grp: 2 nodes are called guides_grp"]
    assert checks.selection_of(found[0]) == ["a|guides_grp", "b|guides_grp"]


# -- rational ---------------------------------------------------------------


def test_rational_finds_curves_with_cv_weights(new_scene):
    node = cmds.curve(name="arc_crv", degree=3, pointWeight=[(0, 0, 0, 1), (1, 1, 0, 2), (2, 0, 0, 1), (3, 1, 0, 1)])
    plain = _curve("spine_crv")

    found = _run("rational", _long(node, plain))

    assert found == ["arc_crv: rational (CV weights aren't saved)"]
    assert checks.selection_of(found[0]) == ["arc_crv"]


# -- construction history ---------------------------------------------------


def test_history_finds_curves_driven_by_their_inputs(new_scene):
    ring = cmds.circle(name="ring_crv")[0]
    plain = _curve("spine_crv")

    found = _run("history", _long(ring, plain))

    assert found == ["ring_crv: driven by makeNurbCircle1 (only the current shape is saved)"]
    assert checks.selection_of(found[0]) == ["ring_crv"]


def test_a_deformed_curve_counts_as_history(new_scene):
    spine = _curve("spine_crv")
    cmds.cluster(spine, name="spine_cluster")

    [problem] = _run("history", [spine])

    assert problem.startswith("spine_crv: driven by spine_cluster")


# -- degenerate -------------------------------------------------------------


def test_degenerate_finds_curves_with_all_cvs_on_one_spot(new_scene):
    dot = _curve("dot_crv", points=[(1, 1, 1)] * 4)
    plain = _curve("spine_crv")

    found = _run("degenerate", _long(dot, plain))

    assert found == ["dot_crv: all CVs on one spot"]
    assert checks.selection_of(found[0]) == ["dot_crv"]


def test_degenerate_finds_zero_length_curves_within_the_tolerance(new_scene):
    tiny = _curve("tiny_crv", points=[(0, 0, 0), (0.00001, 0, 0)], degree=1)

    assert _run("degenerate", [tiny]) == ["tiny_crv: all CVs on one spot"]
    assert _run("degenerate", [tiny], tolerance=0.000001) == []


def test_degenerate_leaves_a_curve_whose_ends_meet(new_scene):
    # Both ends on one spot, the middle away: it still has length.
    there_and_back = _curve("loop_crv", points=[(0, 0, 0), (1, 0, 0), (0, 0, 0)], degree=1)

    assert _run("degenerate", [there_and_back]) == []


# -- in general -------------------------------------------------------------


def test_checks_name_each_shape_when_a_curve_has_several(new_scene):
    a = _curve("a_crv")
    dot = _curve("dot_crv", points=[(1, 1, 1)] * 4)
    cmds.parent(cmds.listRelatives(dot, shapes=True, fullPath=True)[0], a, shape=True, relative=True)

    assert _run("degenerate", [a]) == ["a_crv: all CVs on one spot (dot_crvShape)"]


def test_checks_skip_what_isnt_a_curve(new_scene):
    cube = cmds.polyCube(name="box")[0]

    for check in curves.CHECKS:
        assert check.run(nodes=_long(cube)) == []


def test_curve_checks_change_nothing(new_scene):
    ring = cmds.circle(name="ring_crv")[0]
    cmds.select(ring)
    before = (cmds.ls(long=True), cmds.getAttr(f"{ring}.translate"), cmds.ls(selection=True))

    datatypes.run_qc(curves, _long(ring), checks.defaults(curves.CHECKS))

    assert (cmds.ls(long=True), cmds.getAttr(f"{ring}.translate"), cmds.ls(selection=True)) == before
