"""core.checks: scene checks that report problems and change nothing."""

import pytest
from maya import cmds

from kaiju_suite.core import checks


def _snapshot():
    """Every node, with each transform's local values, and the selection."""
    nodes = sorted(cmds.ls(long=True))
    values = {
        node: [cmds.getAttr(f"{node}.{attr}")[0] for attr in ("translate", "rotate", "scale")]
        for node in cmds.ls(type="transform", long=True)
    }
    return nodes, values, cmds.ls(selection=True, long=True)


def _clean_mesh(name="body_geo"):
    mesh = cmds.polyCube(name=name)[0]
    cmds.delete(mesh, constructionHistory=True)
    return mesh


# -- the list ----------------------------------------------------------------


def test_the_four_checks_and_their_defaults():
    assert [c.key for c in checks.CHECKS] == ["naming", "transforms", "history", "unknown"]
    assert checks.get("naming").options == {"pattern": checks.DEFAULT_PATTERN}
    settings = checks.defaults()
    assert settings == {
        "naming": {"enabled": True, "pattern": checks.DEFAULT_PATTERN},
        "transforms": {"enabled": True},
        "history": {"enabled": True},
        "unknown": {"enabled": True},
    }
    with pytest.raises(LookupError):
        checks.get("nope")


@pytest.mark.parametrize("key", ["naming", "transforms", "history", "unknown"])
def test_each_check_finds_nothing_in_a_clean_scene(new_scene, key):
    assert checks.get(key).run() == []


# -- naming -----------------------------------------------------------------


def test_naming_flags_default_maya_names(new_scene):
    _clean_mesh("pCube1")
    _clean_mesh("body_geo")
    cmds.joint(name="joint1")
    cmds.select(clear=True)
    cmds.joint(name="L_arm_jnt")
    cmds.group(empty=True, name="null1")
    problems = checks.get("naming").run()
    assert len(problems) == 3
    for name in ("pCube1", "joint1", "null1"):
        assert any(p.startswith(f"{name}:") for p in problems)
    assert not any("body_geo" in p or "L_arm_jnt" in p for p in problems)


def test_naming_uses_the_given_pattern(new_scene):
    cmds.group(empty=True, name="arm_grp")
    cmds.group(empty=True, name="arm_ctrl")
    assert checks.get("naming").run(pattern=r".*_ctrl$") == ["arm_grp: doesn't match .*_ctrl$"]


def test_naming_ignores_namespaces(new_scene):
    cmds.namespace(add="hero")
    cmds.group(empty=True, name="hero:arm_grp")
    assert checks.get("naming").run() == []


def test_naming_with_a_bad_pattern_raises(new_scene):
    with pytest.raises(ValueError):
        checks.get("naming").run(pattern="(")


# -- unfrozen transforms ----------------------------------------------------


def test_transforms_flags_moved_controls_and_meshes(new_scene):
    ctrl = cmds.circle(name="arm_ctrl", constructionHistory=False)[0]
    cmds.setAttr(f"{ctrl}.translateX", 2)
    mesh = _clean_mesh()
    cmds.setAttr(f"{mesh}.scaleY", 3)
    still = cmds.circle(name="leg_ctrl", constructionHistory=False)[0]
    assert sorted(checks.get("transforms").run()) == [
        "arm_ctrl: translate not at its default",
        "body_geo: scale not at its default",
    ]
    assert still


def test_transforms_leaves_groups_and_joints_alone(new_scene):
    grp = cmds.group(empty=True, name="arm_grp")
    cmds.setAttr(f"{grp}.translate", 1, 2, 3)
    cmds.select(clear=True)
    cmds.joint(name="arm_jnt", position=(4, 0, 0))
    assert checks.get("transforms").run() == []


# -- history ----------------------------------------------------------------


def test_history_flags_modeling_history_on_meshes_and_curves(new_scene):
    cmds.polyCube(name="box_geo")
    cmds.circle(name="arm_ctrl")
    problems = checks.get("history").run()
    assert len(problems) == 2
    assert any(p.startswith("box_geo:") and "polyCube" in p for p in problems)
    assert any(p.startswith("arm_ctrl:") and "makeNurbCircle" in p for p in problems)


def test_history_ignores_deformers(new_scene):
    mesh = _clean_mesh()
    cmds.cluster(mesh)
    assert checks.get("history").run() == []


# -- unknown nodes ----------------------------------------------------------


def test_unknown_flags_unknown_nodes(new_scene):
    cmds.createNode("unknown", name="leftover")
    assert checks.get("unknown").run() == ["leftover (unknown)"]


# -- running several --------------------------------------------------------


def _messy_scene():
    cmds.polyCube(name="pCube1")
    cmds.setAttr("pCube1.translateX", 1)
    cmds.createNode("unknown", name="leftover")


def test_run_runs_every_check_by_default(new_scene):
    _messy_scene()
    found = dict((check.key, problems) for check, problems in checks.run())
    assert list(found) == ["naming", "transforms", "history", "unknown"]
    assert all(found.values())


def test_run_skips_turned_off_checks_and_uses_options(new_scene):
    _messy_scene()
    settings = checks.defaults()
    settings["history"]["enabled"] = False
    settings["naming"]["pattern"] = r"^p.*"
    found = dict((check.key, problems) for check, problems in checks.run(settings))
    assert list(found) == ["naming", "transforms", "unknown"]
    assert found["naming"] == []


def test_run_fills_in_missing_settings_with_defaults(new_scene):
    _messy_scene()
    found = dict((check.key, problems) for check, problems in checks.run({"unknown": {"enabled": False}}))
    assert list(found) == ["naming", "transforms", "history"]


def test_checks_change_nothing(new_scene):
    _messy_scene()
    cmds.circle(name="arm_ctrl")
    cmds.select("pCube1")
    before = _snapshot()
    checks.run()
    assert _snapshot() == before


# -- settings ---------------------------------------------------------------


def test_settings_problems():
    assert checks.settings_problems(checks.defaults()) == []
    assert checks.settings_problems({}) == []
    assert checks.settings_problems("x") == ["checks must be an object of check settings, not 'x'"]
    assert checks.settings_problems({"nope": {}}) == ["no check 'nope'; use one of naming, transforms, history, unknown"]
    assert checks.settings_problems({"history": {"enabled": "yes"}}) == ["history: enabled must be true or false"]
    assert checks.settings_problems({"naming": {"pattern": 3}}) == ["naming: pattern must be text, not 3"]
    assert checks.settings_problems({"naming": {"pattern": "("}})[0].startswith("naming: pattern isn't a valid regular expression")
    assert checks.settings_problems({"naming": {"colour": "red"}}) == ["naming: unknown option 'colour'"]
    assert checks.settings_problems({"naming": []}) == ["naming must be an object, not []"]
