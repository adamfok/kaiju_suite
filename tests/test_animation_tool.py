import pytest
from maya import cmds

from kaiju_suite import registry
from kaiju_suite.tools.animation_tool import logic

_TR = ("translateX", "translateY", "translateZ", "rotateX", "rotateY", "rotateZ")


def _ctrl(name, x=0.0, parent=None):
    """A control under an offset group at ``(x, 0, 0)``, world-aligned."""
    group = cmds.createNode("transform", name=f"{name}_grp", parent=parent)
    cmds.setAttr(f"{group}.translateX", x)
    return cmds.ls(cmds.createNode("transform", name=name, parent=group), long=True)[0]


def _key(node, frame, values, attrs=_TR):
    for attr, value in zip(attrs, values):
        cmds.setKeyframe(node, attribute=attr, time=frame, value=value)


# -- reset controls ---------------------------------------------------------


def test_reset_controls_is_no_longer_its_own_menu_item():
    assert registry.find("Reset Controls") is None


# -- QC tab -----------------------------------------------------------------


def test_qc_runs_the_animation_checks_on_the_selected_nodes(new_scene):
    keyed = _ctrl("L_arm_ctl")
    _key(keyed, 1, (1, 0, 0, 0, 0, 0))
    still = _ctrl("R_arm_ctl")

    found = {check.key: problems for check, problems in logic.run_qc([keyed, still])}

    assert list(found) == ["not_animated", "unsaved", "duplicate_names"]
    assert found["not_animated"] == ["R_arm_ctl: no keys"]


def test_qc_needs_a_selection(new_scene):
    with pytest.raises(ValueError, match="Nothing selected"):
        logic.run_qc([])


def test_qc_options_are_saved_for_publish_too(new_scene):
    from kaiju_suite import datatypes
    from kaiju_suite.datatypes import animation

    assert logic.QC_CHECKS is animation.CHECKS
    assert logic.qc_settings() == datatypes.qc_settings(animation)


def test_select_problem_selects_the_node(new_scene):
    still = _ctrl("still_ctl")
    found = dict((check.key, problems) for check, problems in logic.run_qc([still]))

    assert logic.select_problem(found["not_animated"][0]) == ["still_ctl"]
    assert cmds.ls(selection=True) == ["still_ctl"]
