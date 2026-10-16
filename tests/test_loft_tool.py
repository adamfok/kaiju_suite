"""Loft Tool: QC for lofted NURBS surfaces. The checks live in
kaiju_suite.datatypes.loft (CHECKS), shared with Builder's Publish."""

import pytest
from maya import cmds

from kaiju_suite import registry
from kaiju_suite.core import checks
from kaiju_suite.datatypes import loft
from kaiju_suite.tools.loft_tool import logic


def _curve(name, z, reverse=False):
    points = [(0, 0, z), (1, 0.5, z), (2, 0, z), (3, 0, z)]
    return cmds.curve(name=name, degree=3, point=points[::-1] if reverse else points)


def _ribbon(name="ribbon", flip=False, **kwargs):
    curves = [_curve(f"{name}_a", 0), _curve(f"{name}_b", 2, reverse=flip), _curve(f"{name}_c", 4)]
    surface, node = cmds.loft(*curves, name=name, constructionHistory=True, **kwargs)
    return cmds.ls(surface, long=True)[0], node


def _found(surface, key):
    """What check ``key`` points at on ``surface``, as long names."""
    problems = checks.get(key, loft.CHECKS).run(nodes=[surface])
    assert len(problems) <= 1
    return checks.selection_of(problems[0]) if problems else []


def _problems(selection):
    return {check.key: problems for check, problems in logic.run_qc(selection) if problems}


# -- the tool ---------------------------------------------------------------


def test_the_tool_is_registered_under_utilities():
    tool = registry.find("Loft Tool")

    assert tool is not None
    assert tool.get("category") == "Utilities"
    assert callable(tool["launch"])


def test_the_tool_shares_the_loft_checks():
    assert logic.QC_CHECKS is loft.CHECKS


# -- the checks -------------------------------------------------------------


def test_the_loft_checks():
    assert [c.key for c in loft.CHECKS] == ["not_loft", "unsupported", "names", "flipped"]


def test_every_check_has_a_label_and_description_and_runs_before_publish():
    for check in loft.CHECKS:
        assert check.label and check.description
        assert check.publish


def test_no_check_fixes_anything():
    assert all(check.fix is None for check in loft.CHECKS)


def test_a_clean_loft_has_no_problems(new_scene):
    surface, _ = _ribbon()

    assert _problems([surface]) == {}


def test_not_a_loft(new_scene):
    plane = cmds.ls(cmds.nurbsPlane(name="flat", constructionHistory=False)[0], long=True)[0]

    assert _found(plane, "not_loft") == [plane]


def test_unsupported_inputs_point_at_the_loft(new_scene):
    plane = cmds.nurbsPlane(name="flat", constructionHistory=False)[0]
    surface, node = cmds.loft(f"{plane}.v[0.5]", _curve("crv_a", 3), name="ribbon", constructionHistory=True)

    assert _found(cmds.ls(surface, long=True)[0], "unsupported") == cmds.ls(node, long=True)


def test_duplicate_names_find_the_surface_and_its_curves(new_scene):
    surface, _ = _ribbon()
    group = cmds.createNode("transform", name="grp")
    for name in ("ribbon", "ribbon_b"):
        other = cmds.parent(cmds.createNode("transform", name="tmp"), group)[0]
        cmds.rename(f"grp|{other}", name)

    found = _found(surface, "names")

    assert found == [surface, cmds.ls("|ribbon_b", long=True)[0]]


def test_flipped_curves_with_auto_reverse_off(new_scene):
    surface, _ = _ribbon(flip=True, autoReverse=False)

    assert _found(surface, "flipped") == cmds.ls(["|ribbon_b", "|ribbon_c"], long=True)


def test_flipped_curves_are_fine_with_auto_reverse_on(new_scene):
    surface, _ = _ribbon(flip=True, autoReverse=True)

    assert _found(surface, "flipped") == []


def test_a_reverse_flag_unflips_a_curve(new_scene):
    surface, node = _ribbon(flip=True, autoReverse=False)
    cmds.setAttr(f"{node}.reverse[1]", True)

    assert _found(surface, "flipped") == []


def test_checks_change_nothing_and_add_no_undo_step(new_scene):
    surface, _ = _ribbon(flip=True, autoReverse=False)
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    logic.run_qc([surface])

    assert not cmds.undoInfo(query=True, undoName=True)


def test_run_qc_needs_a_surface(new_scene):
    box = cmds.ls(cmds.polyCube(name="box")[0], long=True)

    with pytest.raises(ValueError, match="No NURBS surfaces selected"):
        logic.run_qc(box)


def test_run_qc_uses_the_settings_shared_with_builder(new_scene, monkeypatch):
    surface, _ = _ribbon()
    seen = []
    monkeypatch.setattr(logic.datatypes, "run_qc", lambda module, nodes, settings=None: seen.append(module) or [])

    logic.run_qc([surface])

    assert seen == [loft]
