"""datatypes.controlshape.CHECKS: QC checks on given controls, run by the
ControlShape Tool's QC tab and before Builder publishes a ControlShape
item. They report problems and change nothing."""

from maya import cmds, mel

from kaiju_suite import datatypes
from kaiju_suite.core import checks
from kaiju_suite.datatypes import controlshape


def _ctrl(name="ctrl", color=17, parent=None):
    """A circle control with a well-named shape and an index color."""
    node = cmds.circle(normal=(0, 1, 0), constructionHistory=False)[0]
    if parent:
        node = cmds.parent(node, parent)[0]
    uuid = cmds.ls(node, uuid=True)[0]
    cmds.rename(node, name)
    node = cmds.ls(uuid, long=True)[0]
    shape = cmds.rename(_shapes(node)[0], f"{name}Shape")
    shape = _shapes(node)[0]
    if color:
        cmds.setAttr(f"{shape}.overrideEnabled", True)
        cmds.setAttr(f"{shape}.overrideColor", color)
    return node


def _shapes(node):
    return cmds.listRelatives(node, shapes=True, fullPath=True, type="nurbsCurve") or []


def _add_shape(control, name, rational=False):
    """Add a degree-2 curve shape named ``name`` under ``control``; with
    ``rational``, its middle CV has weight 0.5."""
    shape = cmds.createNode("nurbsCurve", name=name, parent=control, skipSelect=True)
    shape = cmds.ls(shape, long=True)[0]
    flag = "yes" if rational else "no"
    cvs = "0 0 0 1 0.5 1 0 0.5 1 0 0 1" if rational else "0 0 0 0.5 1 0 1 0 0"
    mel.eval(f'setAttr "{shape}.cc" -type "nurbsCurve" 2 1 0 {flag} 3 4 0 0 1 1 3 {cvs};')
    return shape


def _run(key, nodes, **options):
    return checks.get(key, controlshape.CHECKS).run(nodes=nodes, **options)


def test_the_controlshape_checks_and_their_defaults():
    assert [c.key for c in controlshape.CHECKS] == ["no_shapes", "shape_names", "color", "duplicate_names", "rational"]
    assert checks.defaults(controlshape.CHECKS) == {
        "no_shapes": {"enabled": True},
        "shape_names": {"enabled": True},
        "color": {"enabled": True},
        "duplicate_names": {"enabled": True},
        "rational": {"enabled": True},
    }
    assert all(c.fix is None for c in controlshape.CHECKS)  # no Fix buttons yet


def test_clean_controls_have_no_problems(new_scene):
    found = datatypes.run_qc(controlshape, [_ctrl("a"), _ctrl("b")], checks.defaults(controlshape.CHECKS))
    assert [(c.key, p) for c, p in found] == [(c.key, []) for c in controlshape.CHECKS]


def test_no_curve_shapes(new_scene):
    bare = cmds.createNode("transform", name="bare")
    assert _run("no_shapes", cmds.ls(bare, _ctrl(), long=True)) == ["bare: no NURBS curve shape"]
    assert _run("no_shapes", cmds.ls(bare, long=True))[0].select == ["bare"]


def test_a_selected_shape_stands_for_its_control(new_scene):
    ctrl = _ctrl(color=0)
    assert _run("color", _shapes(ctrl)) == ["ctrl: no color"]


def test_shape_name_mismatch(new_scene):
    ctrl = _ctrl()
    _add_shape(ctrl, "ctrlShape1")
    assert _run("shape_names", [ctrl]) == []

    cmds.rename(_shapes(ctrl)[0], "curveShape7")
    (problem,) = _run("shape_names", [ctrl])
    assert problem == "ctrl: curve shape curveShape7 isn't named ctrlShape"
    assert problem.select == ["curveShape7"]


def test_shape_names_use_the_controls_short_name(new_scene):
    group = cmds.createNode("transform", name="L_arm_grp")
    ctrl = cmds.parent(_ctrl("L_hand_ctrl"), group)[0]
    assert _run("shape_names", cmds.ls(ctrl, long=True)) == []


def test_no_color(new_scene):
    plain = _ctrl("plain", color=0)
    colored_shape = _ctrl("shape_colored")
    colored_node = _ctrl("node_colored", color=0)
    cmds.setAttr(f"{colored_node}.overrideEnabled", True)
    cmds.setAttr(f"{colored_node}.overrideColor", 6)
    rgb = _ctrl("rgb", color=0)
    cmds.setAttr(f"{_shapes(rgb)[0]}.overrideEnabled", True)
    cmds.setAttr(f"{_shapes(rgb)[0]}.overrideRGBColors", True)
    enabled_only = _ctrl("enabled_only", color=0)
    cmds.setAttr(f"{_shapes(enabled_only)[0]}.overrideEnabled", True)  # color index 0 is no color

    found = _run("color", [plain, colored_shape, colored_node, rgb, enabled_only])

    assert found == ["plain: no color", "enabled_only: no color"]
    assert found[0].select == ["plain"]


def test_duplicate_names(new_scene):
    group = cmds.createNode("transform", name="grp")
    ctrl = _ctrl()
    _ctrl(parent=group)
    (problem,) = _run("duplicate_names", [ctrl])
    assert problem == "|ctrl: 2 nodes are called ctrl"
    assert sorted(problem.select) == ["grp|ctrl", "|ctrl"]


def test_rational_curves(new_scene):
    ctrl = _ctrl()
    _add_shape(ctrl, "ctrlShape1")
    assert _run("rational", [ctrl]) == []

    _add_shape(ctrl, "ctrlShape2", rational=True)
    (problem,) = _run("rational", [ctrl])
    assert problem == "ctrl: ctrlShape2 has CV weights, which aren't saved"
    assert problem.select == ["ctrlShape2"]


def test_checks_change_nothing(new_scene):
    ctrl = _ctrl(color=0)
    before = cmds.ls(long=True)
    datatypes.run_qc(controlshape, [ctrl], checks.defaults(controlshape.CHECKS))
    assert cmds.ls(long=True) == before
    assert cmds.getAttr(f"{_shapes(ctrl)[0]}.overrideEnabled") is False


def test_every_check_runs_before_publishing():
    assert all(c.publish for c in controlshape.CHECKS)
