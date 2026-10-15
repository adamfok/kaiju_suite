import pytest
from maya import cmds

from kaiju_suite import registry
from kaiju_suite.core import checks
from kaiju_suite.datatypes import proximity_wrap
from kaiju_suite.tools.proximitywrap_tool import logic


def _body(name="body"):
    return cmds.polySphere(name=name, radius=1, sx=8, sy=8, ch=False)[0]


def _cloth(name="shirt", radius=1.1):
    return cmds.polyCylinder(name=name, radius=radius, height=1, sx=8, sy=2, ch=False)[0]


def _shape(transform):
    return cmds.listRelatives(transform, shapes=True, noIntermediate=True, fullPath=True)[0]


def _proximity(driven, driver, name="shirt_pwrap"):
    node = cmds.proximityWrap(driven, name=name)[0]
    cmds.proximityWrap(node, edit=True, addDrivers=[_shape(driver)])
    return node


def _long(nodes):
    return cmds.ls(nodes, long=True)


def _problems(selection):
    return {check.key: problems for check, problems in logic.run_qc(selection) if problems}


def _run(key, nodes):
    return checks.get(key, proximity_wrap.CHECKS).run(nodes=_long(nodes))


# -- the tool ---------------------------------------------------------------


def test_the_wrap_tool_is_now_the_proximitywrap_tool():
    tool = registry.find("ProximityWrap Tool")
    assert tool is not None and tool.get("category") == "Utilities"
    assert registry.find("Wrap Tool") is None


def test_the_assembler_wrap_product_opens_it():
    from kaiju_suite.tools.assembler.products import wrap

    assert wrap.PRODUCT.utility == "ProximityWrap Tool"


# -- the checks -------------------------------------------------------------


def test_the_proximity_wrap_checks():
    assert [c.key for c in proximity_wrap.CHECKS] == [
        "no_proximity", "missing_driver", "below_skin", "disabled", "duplicate_names",
    ]  # fmt: skip
    for check in proximity_wrap.CHECKS:
        assert check.label and check.description and check.publish


def test_a_clean_proximity_wrap_passes_every_check(new_scene):
    shirt = _cloth()
    _proximity(shirt, _body())

    assert _problems(_long(shirt)) == {}


def test_no_proximity_wrap(new_scene):
    shirt, coat = _cloth("shirt"), _cloth("coat", 1.3)
    _proximity(shirt, _body())

    problems = _run("no_proximity", [shirt, coat])

    assert problems == ["coat: no proximityWrap"]
    assert checks.selection_of(problems[0]) == ["coat"]


def test_missing_driver_disconnected(new_scene):
    shirt, body = _cloth(), _body()
    node = _proximity(shirt, body)
    cmds.disconnectAttr(f"{_shape(body)}.worldMesh[0]", f"{node}.drivers[0].driverGeometry")

    problems = _run("missing_driver", [shirt])

    assert problems == ["shirt_pwrap: driver 0 isn't connected"]
    assert checks.selection_of(problems[0]) == ["shirt_pwrap"]


def test_missing_driver_not_a_mesh(new_scene):
    shirt = _cloth()
    node = _proximity(shirt, _body())
    curve = cmds.circle(name="ring", constructionHistory=False)[0]
    curve_shape = cmds.listRelatives(curve, shapes=True)[0]
    cmds.connectAttr(f"{curve_shape}.worldSpace[0]", f"{node}.drivers[0].driverGeometry", force=True)

    assert _run("missing_driver", [shirt]) == ["shirt_pwrap: driver ring isn't a mesh"]


def test_missing_driver_with_no_drivers_at_all(new_scene):
    shirt = _cloth()
    cmds.proximityWrap(shirt, name="shirt_pwrap")

    assert _run("missing_driver", [shirt]) == ["shirt_pwrap: no drivers"]


def test_below_skin(new_scene):
    shirt = _cloth()
    cmds.select(clear=True)
    cmds.joint(name="root_jnt")
    cmds.skinCluster("root_jnt", shirt, toSelectedBones=True, name="shirt_skin")
    _proximity(shirt, _body())
    assert _run("below_skin", [shirt]) == []  # made after the skin, it sits on top

    cmds.reorderDeformers("shirt_skin", "shirt_pwrap", shirt)

    problems = _run("below_skin", [shirt])
    assert problems == ["shirt: shirt_pwrap evaluates before shirt_skin"]
    assert checks.selection_of(problems[0]) == ["shirt_pwrap", "shirt_skin"]


@pytest.mark.parametrize("attr, value, text", [
    ("envelope", 0, "shirt_pwrap: envelope is 0"),
    ("nodeState", 1, "shirt_pwrap: node state is HasNoEffect"),
])
def test_disabled(new_scene, attr, value, text):
    shirt = _cloth()
    node = _proximity(shirt, _body())
    cmds.setAttr(f"{node}.{attr}", value)

    assert _run("disabled", [shirt]) == [text]


def test_duplicate_names_of_meshes_and_drivers(new_scene):
    shirt, body = _cloth(), _body()
    _proximity(shirt, body)
    group = cmds.group(empty=True, name="grp")
    cmds.parent(_body("other"), group)
    cmds.rename("grp|other", "body")

    problems = _run("duplicate_names", [shirt])

    assert problems == ["body: 2 nodes are called body"]
    assert sorted(checks.selection_of(problems[0])) == ["|body", "|grp|body"]


# -- logic ------------------------------------------------------------------


def test_run_qc_needs_meshes_selected(new_scene):
    with pytest.raises(ValueError, match="No meshes selected"):
        logic.run_qc([])
    with pytest.raises(ValueError, match="No meshes selected"):
        logic.run_qc(_long(cmds.createNode("transform", name="grp")))


def test_run_qc_takes_a_shape_or_component_for_its_mesh(new_scene):
    shirt = _cloth()
    assert _problems([f"{_long(shirt)[0]}.vtx[0]"]) == {"no_proximity": ["shirt: no proximityWrap"]}


def test_run_qc_changes_nothing_and_adds_no_undo_step(new_scene):
    shirt = _cloth()
    node = _proximity(shirt, _body())
    cmds.setAttr(f"{node}.envelope", 0)
    cmds.undoInfo(state=True)
    cmds.flushUndo()
    nodes = sorted(cmds.ls())

    logic.run_qc(_long(shirt))

    assert sorted(cmds.ls()) == nodes
    assert cmds.undoInfo(query=True, undoName=True) == ""


def test_qc_settings_save_per_user(new_scene, monkeypatch):
    saved = {}
    monkeypatch.setattr(checks.user_settings, "get", lambda tool, key: saved.get((tool, key)))
    monkeypatch.setattr(checks.user_settings, "set", lambda tool, key, value: saved.__setitem__((tool, key), value))

    logic.save_qc_setting("disabled", "enabled", False)

    # Checks can't be turned off: every one runs, as Scripter's Publish runs them.
    assert logic.qc_settings()["disabled"]["enabled"] is True


def test_select_problem_selects_what_it_points_at(new_scene):
    shirt = _cloth()
    node = _proximity(shirt, _body())
    cmds.setAttr(f"{node}.envelope", 0)
    [problem] = _run("disabled", [shirt])

    assert logic.select_problem(problem) == ["shirt_pwrap"]
