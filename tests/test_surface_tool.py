"""Surface Tool: QC for NURBS surfaces. The checks live in
kaiju_suite.datatypes.nurbs_surface (CHECKS), shared with Builder's Publish."""

import pytest
from maya import cmds

from kaiju_suite import datatypes, registry
from kaiju_suite.core import checks
from kaiju_suite.datatypes import nurbs_surface
from kaiju_suite.tools.surface_tool import logic


def _plane(name="ribbon", **kwargs):
    kwargs.setdefault("constructionHistory", False)
    return cmds.ls(cmds.nurbsPlane(name=name, patchesU=2, patchesV=2, **kwargs)[0], long=True)[0]


def _shape(transform):
    return cmds.listRelatives(transform, shapes=True, fullPath=True, type="nurbsSurface")[0]


def _found(surface, key):
    """What check ``key`` points at on ``surface``, as long names."""
    problems = checks.get(key, nurbs_surface.CHECKS).run(nodes=[surface])
    assert len(problems) <= 1
    return checks.selection_of(problems[0]) if problems else []


def _problems(selection):
    return {check.key: problems for check, problems in logic.run_qc(selection) if problems}


def _trimmed(name="ribbon"):
    plane = _plane(name)
    loop = [(0.3, 0.3), (0.7, 0.3), (0.7, 0.7), (0.3, 0.7), (0.3, 0.3)]
    curve = cmds.curveOnSurface(plane, degree=1, uv=loop)
    cmds.trim(plane, curve, locatorU=0.5, locatorV=0.5, selected=0, shrink=False, constructionHistory=False)
    return plane


# -- the tool ---------------------------------------------------------------


def test_the_tool_is_registered_under_utilities():
    tool = registry.find("Surface Tool")

    assert tool is not None
    assert tool.get("category") == "Utilities"
    assert callable(tool["launch"])


# -- the checks -------------------------------------------------------------


def test_the_surface_checks():
    assert [c.key for c in nurbs_surface.CHECKS] == ["names", "rational", "trimmed", "history"]


def test_every_check_has_a_label_and_description_and_runs_before_publish():
    for check in nurbs_surface.CHECKS:
        assert check.label and check.description
        assert check.publish


def test_no_check_fixes_anything():
    assert [c.key for c in nurbs_surface.CHECKS if c.fix] == []


def test_a_clean_surface_passes_every_check(new_scene):
    assert _problems([_plane()]) == {}


def test_duplicate_names(new_scene):
    a = _plane()
    group = cmds.createNode("transform", name="grp")
    cmds.parent(_plane("other"), group)
    cmds.rename("grp|other", "ribbon")

    assert _found(a, "names") == [a]
    assert checks.get("names", nurbs_surface.CHECKS).run(nodes=[a]) == ["|ribbon: another node is called ribbon"]


def test_rational_surfaces(new_scene):
    plane = _plane()
    cmds.setAttr(f"{_shape(plane)}.weights[5]", 2.0)
    cmds.setAttr(f"{_shape(plane)}.weights[7]", 0.5)

    found = _found(plane, "rational")

    assert len(found) == 2 and all(".cv[" in item for item in found)
    assert checks.get("rational", nurbs_surface.CHECKS).run(nodes=[plane]) == [
        "ribbon: 2 CVs with weights (weights aren't saved)"
    ]


def test_trimmed_surfaces(new_scene):
    plane = _trimmed()

    assert _found(plane, "trimmed") == [plane]
    assert checks.get("trimmed", nurbs_surface.CHECKS).run(nodes=[plane]) == [
        "ribbon: trimmed (trim curves aren't saved)"
    ]


def test_construction_history(new_scene):
    plane = _plane(constructionHistory=True)

    assert _found(plane, "history") == [plane]
    assert checks.get("history", nurbs_surface.CHECKS).run(nodes=[plane]) == [
        "ribbon: construction history (isn't saved)"
    ]


def test_deformers_are_not_history(new_scene):
    plane = _plane()
    joint = cmds.createNode("joint")
    cmds.skinCluster(joint, plane)
    cmds.cluster(plane)

    assert _found(plane, "history") == []


# -- QC ---------------------------------------------------------------------


def test_qc_takes_transforms_shapes_and_cvs_and_skips_other_nodes(new_scene):
    a, b, c = _plane("a"), _plane("b"), _plane("c")
    for plane in (a, b, c):
        cmds.setAttr(f"{_shape(plane)}.weights[0]", 2.0)
    joint = cmds.ls(cmds.createNode("joint"), long=True)[0]

    found = _problems([a, _shape(b), f"{c}.cv[0][0]", joint, a])

    assert [p.split(":")[0] for p in found["rational"]] == ["a", "b", "c"]


def test_qc_needs_surfaces(new_scene):
    _plane()
    joint = cmds.ls(cmds.createNode("joint"), long=True)[0]

    with pytest.raises(ValueError, match="No NURBS surfaces selected"):
        logic.run_qc([joint])
    with pytest.raises(ValueError, match="No NURBS surfaces selected"):
        logic.run_qc([])


def test_qc_changes_nothing_and_adds_no_undo_step(new_scene):
    plane = _plane(constructionHistory=True)
    cmds.undoInfo(state=True)
    cmds.flushUndo()
    before = cmds.ls(long=True)

    logic.run_qc([plane])

    assert cmds.ls(long=True) == before
    assert not cmds.undoInfo(query=True, undoName=True)


def test_qc_options_are_saved_for_publish_too(new_scene):
    assert logic.qc_settings() == datatypes.qc_settings(nurbs_surface)


def test_select_problem_selects_the_cvs(new_scene):
    plane = _plane()
    cmds.setAttr(f"{_shape(plane)}.weights[0]", 2.0)
    [problem] = _problems([plane])["rational"]

    logic.select_problem(problem)

    assert cmds.ls(selection=True)
    assert all(".cv[" in item for item in cmds.ls(selection=True))
