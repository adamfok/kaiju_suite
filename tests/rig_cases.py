"""A scene and parameters to build each rig module with, for tests that go
over every rig module (see test_rig_controls.py and test_rig_outputs.py).

``CASES[key]()`` makes the scene in an empty scene and returns
``(params, controls)``: complete parameters, and the controls the build
should make or change.
"""

from maya import cmds

from kaiju_suite.rigging.rig_module import get_rig_module


def _joint(name, parent=None, translate=(0, 0, 0)):
    node = cmds.createNode("joint", name=name, parent=parent, skipSelect=True)
    cmds.setAttr(f"{node}.translate", *translate)
    return node


def _arm():
    """shoulder > elbow > wrist, bent at the elbow toward -Z."""
    _joint("shoulder", translate=(0, 10, 0))
    _joint("elbow", "shoulder", translate=(5, 0, -1))
    _joint("wrist", "elbow", translate=(5, 0, 1))


def _params(key, **values):
    params = get_rig_module(key).defaults()
    params.update(values)
    return params


def _root():
    return _params("root", name="main"), ["main_root_ctrl", "main_offset_ctrl"]


def _single_fk():
    _joint("elbow")
    return _params("single_fk", name="L_elbow", joint="elbow"), ["L_elbow_fk_ctrl"]


def _fk_chain():
    _joint("knuckle")
    _joint("middle", "knuckle", translate=(1, 0, 0))
    _joint("tip", "middle", translate=(1, 0, 0))
    params = _params("fk_chain", name="L_finger", start_joint="knuckle", end_joint="tip")
    return params, ["L_finger_01_fk_ctrl", "L_finger_02_fk_ctrl", "L_finger_03_fk_ctrl"]


def _ik(key):
    def case():
        _arm()
        return _params(key, name="L_arm", start_joint="shoulder", end_joint="wrist"), ["L_arm_ik_ctrl", "L_arm_pv_ctrl"]

    return case


def _ik_fk():
    _arm()
    params = _params("ik_fk", name="L_arm", start_joint="shoulder", end_joint="wrist")
    fk = [f"L_arm_{i:02d}_fk_ctrl" for i in (1, 2, 3)]
    return params, ["L_arm_switch_ctrl", "L_arm_ik_ctrl", "L_arm_pv_ctrl"] + fk


def _spline_ik():
    _joint("hips")
    _joint("spine", "hips", translate=(0, 2, 0))
    _joint("chest", "spine", translate=(0, 2, 0))
    params = _params("spline_ik", name="spine", start_joint="hips", end_joint="chest")
    return params, ["spine_hip_ctrl", "spine_chest_ctrl"]


def _space_switch():
    cmds.createNode("transform", name="world_space", skipSelect=True)
    cmds.createNode("transform", name="chest_space", skipSelect=True)
    group = cmds.createNode("transform", name="hand_ctrl_grp", skipSelect=True)
    cmds.parent(cmds.circle(name="hand_ctrl", constructionHistory=False)[0], group)
    params = _params("space_switch", control="hand_ctrl", spaces="world=world_space, chest=chest_space")
    return params, ["hand_ctrl"]


CASES = {
    "root": _root,
    "single_fk": _single_fk,
    "fk_chain": _fk_chain,
    "simple_ik": _ik("simple_ik"),
    "stretchy_ik": _ik("stretchy_ik"),
    "ik_fk": _ik_fk,
    "spline_ik": _spline_ik,
    "space_switch": _space_switch,
}
