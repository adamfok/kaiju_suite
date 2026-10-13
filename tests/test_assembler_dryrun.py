import os

from maya import cmds

from kaiju_suite.rigging.rig_module import spec
from kaiju_suite.tools.assembler import dryrun, logic


def _joint(name, parent=None, translate=(0, 0, 0)):
    node = cmds.createNode("joint", name=name, parent=parent, skipSelect=True)
    cmds.setAttr(f"{node}.translate", *translate)


def _arm():
    _joint("shoulder", translate=(0, 10, 0))
    _joint("elbow", "shoulder", translate=(5, 0, -1))
    _joint("wrist", "elbow", translate=(5, 0, 1))


def _rig(folder, file_name, key, **params):
    os.makedirs(folder, exist_ok=True)
    spec.write(os.path.join(folder, file_name), key, params)
    logic.append_to_order(folder, [file_name])


def _arm_rig(folder, file_name="L_arm.rig", **params):
    _rig(folder, file_name, "simple_ik", name="L_arm", start_joint="shoulder", end_joint="wrist", **params)


def test_nothing_to_report_when_every_node_is_in_the_scene_or_made_earlier(new_scene, tmp_path):
    _arm()
    _rig(str(tmp_path), "root.rig", "root", name="main")
    _arm_rig(str(tmp_path), parent="main_offset_ctrl")

    assert dryrun.problems(str(tmp_path)) == []


def test_reports_a_node_nothing_makes(new_scene, tmp_path):
    _arm()
    _arm_rig(str(tmp_path), parent="main_offset_ctrl")

    assert dryrun.problems(str(tmp_path)) == [
        "L_arm.rig: Parent 'main_offset_ctrl' isn't in the scene, and no earlier item makes it."
    ]


def test_reports_a_node_a_later_item_makes(new_scene, tmp_path):
    _arm()
    _arm_rig(str(tmp_path), parent="main_offset_ctrl")
    _rig(str(tmp_path), "root.rig", "root", name="main")

    assert dryrun.problems(str(tmp_path)) == [
        "L_arm.rig: Parent 'main_offset_ctrl' is made by a later item, root.rig; move L_arm.rig below it."
    ]


def test_reports_every_missing_node_with_the_item_path(new_scene, tmp_path):
    _arm_rig(str(tmp_path / "arms"))
    _rig(str(tmp_path / "arms"), "hand_space.rig", "space_switch", control="L_arm_ik_ctrl", spaces="world=world_space")

    assert dryrun.problems(str(tmp_path)) == [
        "arms/L_arm.rig: Start joint 'shoulder' isn't in the scene, and no earlier item makes it.",
        "arms/L_arm.rig: End joint 'wrist' isn't in the scene, and no earlier item makes it.",
        "arms/hand_space.rig: Space 'world' node 'world_space' isn't in the scene, and no earlier item makes it.",
    ]


def test_names_earlier_items_that_cannot_say_what_they_make(new_scene, tmp_path):
    _arm()
    with open(tmp_path / "setup.py", "w") as f:
        f.write("from maya import cmds\ncmds.createNode('transform', name='world_space')\n")
    logic.append_to_order(str(tmp_path), ["setup.py"])
    _arm_rig(str(tmp_path), parent="world_space")

    assert dryrun.problems(str(tmp_path)) == [
        "L_arm.rig: Parent 'world_space' isn't in the scene, and no earlier Rig Module item makes it"
        " (setup.py might: it can't say what it makes)."
    ]


def test_skips_disabled_items(new_scene, tmp_path):
    _arm()
    _rig(str(tmp_path), "root.rig", "root", name="main")
    _arm_rig(str(tmp_path), parent="main_offset_ctrl")
    logic.set_enabled(str(tmp_path / "root.rig"), False)

    assert dryrun.problems(str(tmp_path)) == [
        "L_arm.rig: Parent 'main_offset_ctrl' isn't in the scene, and no earlier item makes it."
    ]


def test_reports_rig_items_it_cannot_read(new_scene, tmp_path):
    spec.write(str(tmp_path / "odd.rig"), "no_such_module", {})

    assert dryrun.problems(str(tmp_path)) == ["odd.rig: Unknown rig module 'no_such_module' (known: fk_chain, ik_fk, root, simple_ik, single_fk, space_switch, spline_ik, stretchy_ik)."]


def test_changes_nothing_in_the_scene(new_scene, tmp_path):
    _arm()
    _rig(str(tmp_path), "root.rig", "root", name="main")
    _arm_rig(str(tmp_path), parent="main_offset_ctrl")
    before = set(cmds.ls())

    dryrun.problems(str(tmp_path))

    assert set(cmds.ls()) == before
