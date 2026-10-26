import pytest
from maya import cmds

from kaiju_suite.tools.deltamush_tool import logic


def _plane(name="body", sx=2):
    plane = cmds.polyPlane(name=name, width=2, height=2, sx=sx, sy=1, constructionHistory=False)[0]
    return cmds.ls(plane, long=True)[0]


# -- QC tab -----------------------------------------------------------------


def test_qc_needs_meshes(new_scene):
    group = cmds.createNode("transform", name="grp")

    with pytest.raises(ValueError, match="No meshes selected"):
        logic.run_qc(cmds.ls(group, long=True))
    with pytest.raises(ValueError, match="No meshes selected"):
        logic.run_qc([])


def test_qc_options_are_saved_for_publish_too(new_scene, monkeypatch):
    from kaiju_suite import datatypes
    from kaiju_suite.datatypes import deltamush

    saved = []
    monkeypatch.setattr(datatypes, "save_qc_setting", lambda *a: saved.append(a))

    logic.save_qc_setting("missing", "enabled", True)

    assert saved == [(deltamush, "missing", "enabled", True)]
    assert logic.qc_settings() == datatypes.qc_settings(deltamush)


def test_select_problem_selects_the_mesh(new_scene):
    body = _plane("body")
    found = dict((check.key, problems) for check, problems in logic.run_qc([body]))

    assert logic.select_problem(found["missing"][0]) == ["body"]
    assert cmds.ls(selection=True) == ["body"]
