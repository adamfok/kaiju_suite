import pytest
from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.core.selection import short_name
from kaiju_suite.tools.guide_tool import logic, templates

_FINGERS = ("index", "middle", "ring", "pinky")
_BIPED = [
    "root", "spine", "neck", "head", "l_shoulder", "l_arm", "l_hand",
    *(f"l_{f}_metacarpal" for f in _FINGERS), "l_thumb", *(f"l_{f}" for f in _FINGERS),
    "l_leg", "l_foot",
]


def _pos(node):
    return om.MVector(cmds.xform(node, query=True, worldSpace=True, translation=True))


def _close(a, b, tolerance=1e-3):
    return (om.MVector(a) - om.MVector(b)).length() < tolerance


def _axis(node, axis):
    m = om.MMatrix(cmds.xform(node, query=True, worldSpace=True, matrix=True))
    row = "xyz".index(axis)
    return om.MVector(m[row * 4], m[row * 4 + 1], m[row * 4 + 2]).normalize()


def _chains(name="biped"):
    return {chain["name"]: chain for chain in templates.TEMPLATES[name]}


# -- the data ---------------------------------------------------------------------


def test_biped_has_every_chain_in_order():
    assert list(templates.TEMPLATES) == ["biped"]
    assert [chain["name"] for chain in templates.TEMPLATES["biped"]] == _BIPED


def test_biped_chains_connect():
    c = _chains()
    for a, b in (("spine", "neck"), ("neck", "head"), ("l_shoulder", "l_arm"), ("l_arm", "l_hand"),
                 ("l_leg", "l_foot")):
        assert _close(c[a]["end"], c[b]["start"]), (a, b)
    for finger in _FINGERS:
        assert _close(c[f"l_{finger}_metacarpal"]["start"], c["l_hand"]["start"]), finger
        assert _close(c[f"l_{finger}_metacarpal"]["end"], c[f"l_{finger}"]["start"]), finger


def test_biped_chain_shapes():
    c = _chains()
    assert not c["root"]["end_joint"] and _close(c["root"]["start"], (0, 0, 0))
    for finger in _FINGERS:
        assert c[f"l_{finger}_metacarpal"]["count"] == 0 and c[f"l_{finger}_metacarpal"]["end_joint"]
        assert c[f"l_{finger}"]["count"] == 2 and c[f"l_{finger}"]["end_joint"]
    assert c["l_thumb"]["count"] == 2
    for name, chain in c.items():
        assert chain["mirror"] == name.startswith("l_"), name


def test_biped_chains_go_the_way_their_presets_do():
    c = _chains()
    for name, preset in logic.PRESETS.items():
        if name not in c:
            continue
        chain = c[name]
        way = om.MVector(chain["end"]) - om.MVector(chain["start"])
        preset_way = om.MVector(preset["end"]) - om.MVector(preset["start"])
        assert (way.normal() - preset_way.normal()).length() < 1e-6, name
        for key in ("count", "aim", "up", "up_side", "end_joint", "mirror"):
            assert chain[key] == preset[key], (name, key)


# -- check_build ------------------------------------------------------------------


def test_check_build_passes_and_changes_nothing(new_scene):
    before = set(cmds.ls())

    logic.check_build("arm", 1, mirror=True)

    assert set(cmds.ls()) == before


def test_check_build_refuses_what_build_guides_refuses(new_scene):
    cmds.createNode("transform", name="arm_r_02_jnt")
    with pytest.raises(ValueError, match="arm_r_02_jnt"):
        logic.check_build("arm_l", 1, mirror=True)
    with pytest.raises(ValueError):
        logic.check_build("arm", -1)
    with pytest.raises(ValueError):
        logic.check_build("arm", 1, start=(1, 1, 1), end=(1, 1, 1))


def test_check_build_lets_a_chain_build_again(new_scene):
    logic.build_guides("arm", 1, mirror=True)

    logic.check_build("arm", 3, mirror=True)


# -- build_template -----------------------------------------------------------------


def test_build_template_builds_every_chain_where_it_goes(new_scene):
    groups = templates.build_template("biped")

    assert [cmds.getAttr(f"{g}.kaijuGuides") for g in groups] == _BIPED
    for group, chain in zip(groups, templates.TEMPLATES["biped"]):
        found = logic.guides(group)["chain"]
        assert len(found) == chain["count"] + 2
        assert _close(_pos(found[0]), chain["start"]) and _close(_pos(found[-1]), chain["end"]), chain["name"]
        assert bool(logic.mirrored_joints(group)) == chain["mirror"]


def test_biped_fingers_and_metacarpals(new_scene):
    templates.build_template("biped")

    group = logic.find_group(["l_index_metacarpal_guides_grp"])
    assert [short_name(j) for j in logic.joints(group)] == [
        "l_index_metacarpal_01_jnt", "l_index_metacarpal_02_jnt_end"
    ]
    finger = logic.find_group(["l_index_guides_grp"])
    joints = logic.joints(finger)
    assert len(joints) == 4 and short_name(joints[-1]) == "l_index_04_jnt_end"
    assert _close(_pos(joints[0]), _pos(logic.joints(group)[-1]))
    assert short_name(logic.mirrored_joints(finger)[0]) == "r_index_01_jnt"


def test_biped_axes_follow_the_presets(new_scene):
    templates.build_template("biped")

    for joint in logic.joints("spine_guides_grp"):
        assert (_axis(joint, "y") - om.MVector(0, 1, 0)).length() < 1e-3
        assert (_axis(joint, "z") - om.MVector(0, 0, -1)).length() < 1e-3
    for joint in logic.joints("l_arm_guides_grp"):
        assert (_axis(joint, "x") - om.MVector(1, 0, 0)).length() < 1e-3
        assert (_axis(joint, "y") - om.MVector(0, 0, -1)).length() < 1e-3


def test_build_template_is_one_undo_step(new_scene):
    templates.build_template("biped")
    cmds.undo()

    assert not cmds.ls("*_guides_grp")
    assert not cmds.ls(type="joint")


def test_build_template_refuses_a_taken_name_and_builds_nothing(new_scene):
    cmds.createNode("transform", name="l_ring_02_jnt")
    before = set(cmds.ls())

    with pytest.raises(ValueError, match="l_ring_02_jnt"):
        templates.build_template("biped")

    assert set(cmds.ls()) == before


def test_build_template_again_keeps_the_joints(new_scene):
    groups = templates.build_template("biped")
    before = [cmds.ls(logic.joints(g), uuid=True) for g in groups]

    groups = templates.build_template("biped")

    assert [cmds.ls(logic.joints(g), uuid=True) for g in groups] == before


def test_build_template_refuses_an_unknown_template(new_scene):
    with pytest.raises(ValueError, match="dragon"):
        templates.build_template("dragon")


# -- align: UE5 Mannequin / MetaHuman ------------------------------------------------

# A stand-in UE5 skeleton (MetaHuman bodies use the same names): about 170 cm,
# facing +Z, left at +X, arms down and forward a little, elbow bent back,
# knee bent forward, under a namespace.
_UE5 = {
    "root": (None, (0, 0, 0)),
    "pelvis": ("root", (0, 95, 0)),
    "spine_01": ("pelvis", (0, 105, -1)),
    "spine_02": ("spine_01", (0, 115, -2)),
    "spine_03": ("spine_02", (0, 125, -2)),
    "spine_04": ("spine_03", (0, 135, -1)),
    "spine_05": ("spine_04", (0, 142, 0)),
    "neck_01": ("spine_05", (0, 150, -1)),
    "neck_02": ("neck_01", (0, 156, 0)),
    "head": ("neck_02", (0, 162, 1)),
    "clavicle_l": ("spine_05", (2, 145, 1)),
    "upperarm_l": ("clavicle_l", (16, 145, -2)),
    "lowerarm_l": ("upperarm_l", (40, 130, -8)),
    "hand_l": ("lowerarm_l", (64, 115, -2)),
    "thumb_01_l": ("hand_l", (66, 113, 1)),
    "thumb_02_l": ("thumb_01_l", (68, 110, 4)),
    "thumb_03_l": ("thumb_02_l", (69, 108, 6)),
    "thigh_l": ("pelvis", (9, 92, 0)),
    "calf_l": ("thigh_l", (10, 50, 4)),
    "foot_l": ("calf_l", (10, 8, -1)),
    "ball_l": ("foot_l", (10, 1, 12)),
}
for _i, (_finger, _z) in enumerate((("index", 1), ("middle", -1), ("ring", -3), ("pinky", -5))):
    _UE5[f"{_finger}_metacarpal_l"] = ("hand_l", (66, 114, _z))
    _UE5[f"{_finger}_01_l"] = (f"{_finger}_metacarpal_l", (72 - _i * 0.5, 110, _z))
    _UE5[f"{_finger}_02_l"] = (f"{_finger}_01_l", (76 - _i * 0.5, 107, _z))
    _UE5[f"{_finger}_03_l"] = (f"{_finger}_02_l", (78.5 - _i * 0.5, 105, _z))


def _skeleton(table=None, namespace="SK", skip=()):
    """Build a skeleton from ``table`` (name -> (parent, position)) and return
    its joints by name."""
    table = table or _UE5
    if namespace and not cmds.namespace(exists=namespace):
        cmds.namespace(add=namespace)
    made = {}
    for name, (parent, position) in table.items():
        if name in skip:
            continue
        cmds.select(clear=True)
        joint = cmds.joint(name=f"{namespace}:{name}" if namespace else name, position=position)
        if parent and parent in made:
            joint = cmds.parent(joint, made[parent])[0]
            cmds.xform(joint, worldSpace=True, translation=position)
        made[name] = cmds.ls(joint, long=True)[0]
    cmds.select(clear=True)
    return made


def _guide_pos(chain, which):
    found = logic.guides(f"{chain}_guides_grp")
    return _pos(found["up"] if which == "up" else found["chain"][which])


def _ue5_pos(name):
    return om.MVector(_UE5[name][1])


def test_skeletons_list_ue5():
    assert "ue5" in templates.SKELETONS
    assert templates.SKELETONS["ue5"]["label"] == "UE5 Mannequin / MetaHuman"


def test_detect_finds_ue5_from_any_of_its_joints(new_scene):
    joints = _skeleton()

    assert templates.detect([joints["calf_l"]]) == "ue5"


def test_detect_refuses_an_unknown_skeleton_or_no_selection(new_scene):
    cmds.joint(name="not_a_known_joint")
    with pytest.raises(ValueError):
        templates.detect(["not_a_known_joint"])
    with pytest.raises(ValueError, match="Select"):
        templates.detect([])


def test_align_puts_each_chain_on_its_anchor_joints(new_scene):
    templates.build_template("biped")
    joints = _skeleton()

    report = templates.align("biped", [joints["head"]], "ue5")

    assert not report["skipped"], report["skipped"]
    for chain, start, end in (
        ("spine", "pelvis", "neck_01"), ("neck", "neck_01", "head"), ("l_shoulder", "clavicle_l", "upperarm_l"),
        ("l_arm", "upperarm_l", "hand_l"), ("l_hand", "hand_l", "middle_01_l"),
        ("l_index_metacarpal", "hand_l", "index_01_l"), ("l_leg", "thigh_l", "foot_l"),
    ):
        assert _close(_guide_pos(chain, 0), _ue5_pos(start)), chain
        assert _close(_guide_pos(chain, -1), _ue5_pos(end)), chain
    for chain, start in (("root", "root"), ("head", "head"), ("l_index", "index_01_l"),
                         ("l_thumb", "thumb_01_l"), ("l_foot", "foot_l")):
        assert _close(_guide_pos(chain, 0), _ue5_pos(start)), chain


def test_align_puts_middle_guides_on_key_joints_when_the_counts_match(new_scene):
    templates.build_template("biped")
    joints = _skeleton()

    templates.align("biped", [joints["root"]], "ue5")

    for chain, index, joint in (
        ("l_arm", 1, "lowerarm_l"), ("l_leg", 1, "calf_l"), ("l_foot", 1, "ball_l"), ("neck", 1, "neck_02"),
        ("l_middle", 1, "middle_02_l"), ("l_middle", 2, "middle_03_l"), ("l_thumb", 1, "thumb_02_l"),
    ):
        assert _close(_guide_pos(chain, index), _ue5_pos(joint)), (chain, index)


def test_align_spreads_middle_guides_evenly_otherwise(new_scene):
    templates.build_template("biped")
    joints = _skeleton()

    templates.align("biped", [joints["root"]], "ue5")

    start, end = _ue5_pos("pelvis"), _ue5_pos("neck_01")
    for i in range(1, 4):
        assert _close(_guide_pos("spine", i), start + (end - start) * (i / 4.0)), i


def test_align_extends_past_the_last_joint_where_there_is_no_end(new_scene):
    templates.build_template("biped")
    joints = _skeleton()

    templates.align("biped", [joints["root"]], "ue5")

    tip = _guide_pos("l_index", -1)
    last, before = _ue5_pos("index_03_l"), _ue5_pos("index_02_l")
    assert (tip - last) * (last - before) > 0  # beyond the last knuckle, the same way
    toe, ball = _guide_pos("l_foot", -1), _ue5_pos("ball_l")
    assert toe.z > ball.z + 1 and abs(toe.y - ball.y) < 1e-3  # forward, flat
    assert _guide_pos("head", -1).y > _ue5_pos("head").y + 1  # still above the head


def test_align_puts_limb_up_guides_where_they_bend(new_scene):
    templates.build_template("biped")
    joints = _skeleton()

    templates.align("biped", [joints["root"]], "ue5")

    assert _guide_pos("l_arm", "up").z < _ue5_pos("lowerarm_l").z - 1  # behind the elbow
    assert _guide_pos("l_leg", "up").z > _ue5_pos("calf_l").z + 1  # in front of the knee
    assert _guide_pos("spine", "up").z < -1  # the spine keeps its up guide behind


def test_align_moves_the_joints_and_the_mirror(new_scene):
    templates.build_template("biped")
    joints = _skeleton()

    templates.align("biped", [joints["root"]], "ue5")

    elbow = _ue5_pos("lowerarm_l")
    assert _close(_pos(logic.joints("l_arm_guides_grp")[1]), elbow)
    assert _close(_pos(logic.mirrored_joints("l_arm_guides_grp")[1]), om.MVector(-elbow.x, elbow.y, elbow.z))


def test_align_auto_detects_the_skeleton(new_scene):
    templates.build_template("biped")
    joints = _skeleton()

    report = templates.align("biped", [joints["spine_03"]])

    assert report["skeleton"] == "ue5"
    assert _close(_guide_pos("l_arm", 0), _ue5_pos("upperarm_l"))


def test_align_skips_chains_it_cannot_place(new_scene):
    templates.build_template("biped")
    logic.delete_guides("l_thumb_guides_grp")
    joints = _skeleton(skip=("ball_l",))

    report = templates.align("biped", [joints["root"]], "ue5")

    skipped = dict(report["skipped"])
    assert "l_thumb" in skipped and "built" in skipped["l_thumb"]
    assert "l_foot" in skipped and skipped["l_foot"].count("ball_l") == 1
    assert "l_arm" in report["aligned"]


def test_align_refuses_when_nothing_is_built(new_scene):
    joints = _skeleton()

    with pytest.raises(ValueError, match="Build"):
        templates.align("biped", [joints["root"]], "ue5")


def test_align_is_one_undo_step(new_scene):
    templates.build_template("biped")
    before = _guide_pos("l_arm", 0)
    joints = _skeleton()

    templates.align("biped", [joints["root"]], "ue5")
    cmds.undo()

    assert _close(_guide_pos("l_arm", 0), before)


def test_align_prints_no_errors(new_scene):
    templates.build_template("biped")
    joints = _skeleton()
    printed = []
    kinds = (om.MCommandMessage.kWarning, om.MCommandMessage.kError)
    callback = om.MCommandMessage.addCommandOutputCallback(
        lambda text, kind, _: printed.append(text.strip()) if kind in kinds else None
    )
    try:
        templates.align("biped", [joints["root"]], "ue5")
    finally:
        om.MMessage.removeCallback(callback)

    assert printed == []


# -- align: Mixamo and HumanIK ------------------------------------------------------

# A stand-in Mixamo skeleton: HumanIK-style names, a HeadTop_End, finger tips
# (…4) and a toe end, no root joint.
_MIXAMO = {
    "Hips": (None, (0, 95, 0)),
    "Spine": ("Hips", (0, 105, -1)),
    "Spine1": ("Spine", (0, 120, -2)),
    "Spine2": ("Spine1", (0, 135, -1)),
    "Neck": ("Spine2", (0, 150, -1)),
    "Head": ("Neck", (0, 160, 1)),
    "HeadTop_End": ("Head", (0, 178, 2)),
    "LeftShoulder": ("Spine2", (2, 145, 1)),
    "LeftArm": ("LeftShoulder", (16, 145, -2)),
    "LeftForeArm": ("LeftArm", (40, 130, -8)),
    "LeftHand": ("LeftForeArm", (64, 115, -2)),
    "LeftHandThumb1": ("LeftHand", (66, 113, 1)),
    "LeftHandThumb2": ("LeftHandThumb1", (68, 110, 4)),
    "LeftHandThumb3": ("LeftHandThumb2", (69, 108, 6)),
    "LeftHandThumb4": ("LeftHandThumb3", (70, 106, 8)),
    "LeftUpLeg": ("Hips", (9, 92, 0)),
    "LeftLeg": ("LeftUpLeg", (10, 50, 4)),
    "LeftFoot": ("LeftLeg", (10, 8, -1)),
    "LeftToeBase": ("LeftFoot", (10, 1, 12)),
    "LeftToe_End": ("LeftToeBase", (10, 1, 19)),
}
for _i, (_finger, _z) in enumerate((("Index", 1), ("Middle", -1), ("Ring", -3), ("Pinky", -5))):
    for _n, _x in enumerate((72, 76, 78.5, 80.5), start=1):
        _parent = "LeftHand" if _n == 1 else f"LeftHand{_finger}{_n - 1}"
        _MIXAMO[f"LeftHand{_finger}{_n}"] = (_parent, (_x - _i * 0.5, 110 - (_n - 1) * 2.5, _z))


def _mixamo_pos(name):
    return om.MVector(_MIXAMO[name][1])


def test_skeletons_list_mixamo_and_humanik():
    labels = {key: skeleton["label"] for key, skeleton in templates.SKELETONS.items()}
    assert labels["mixamo"] == "Mixamo" and labels["humanik"] == "HumanIK"


def test_detect_finds_mixamo_in_a_namespace_or_with_a_name_prefix(new_scene):
    joints = _skeleton(_MIXAMO, namespace="mixamorig")
    assert templates.detect([joints["LeftLeg"]]) == "mixamo"

    cmds.file(new=True, force=True)
    renamed = {f"mixamorig_{name}": ((f"mixamorig_{p}" if p else None), at) for name, (p, at) in _MIXAMO.items()}
    joints = _skeleton(renamed, namespace=None)
    assert templates.detect([joints["mixamorig_Hips"]]) == "mixamo"


def test_align_to_mixamo(new_scene):
    templates.build_template("biped")
    joints = _skeleton(_MIXAMO, namespace="mixamorig")

    report = templates.align("biped", [joints["Hips"]])

    assert report["skeleton"] == "mixamo"
    assert [name for name, _ in report["skipped"]] == ["root"]  # Mixamo has no root joint
    for chain, start, end in (
        ("spine", "Hips", "Neck"), ("neck", "Neck", "Head"), ("head", "Head", "HeadTop_End"),
        ("l_shoulder", "LeftShoulder", "LeftArm"), ("l_arm", "LeftArm", "LeftHand"),
        ("l_hand", "LeftHand", "LeftHandMiddle1"), ("l_ring_metacarpal", "LeftHand", "LeftHandRing1"),
        ("l_index", "LeftHandIndex1", "LeftHandIndex4"), ("l_thumb", "LeftHandThumb1", "LeftHandThumb4"),
        ("l_leg", "LeftUpLeg", "LeftFoot"), ("l_foot", "LeftFoot", "LeftToe_End"),
    ):
        assert _close(_guide_pos(chain, 0), _mixamo_pos(start)), chain
        assert _close(_guide_pos(chain, -1), _mixamo_pos(end)), chain
    assert _close(_guide_pos("l_arm", 1), _mixamo_pos("LeftForeArm"))
    assert _close(_guide_pos("l_index", 2), _mixamo_pos("LeftHandIndex3"))
    assert _close(_guide_pos("l_foot", 1), _mixamo_pos("LeftToeBase"))


def test_align_to_mixamo_without_tip_joints_extends_past_the_last_knuckle(new_scene):
    templates.build_template("biped")
    joints = _skeleton(_MIXAMO, namespace="mixamorig", skip=("LeftHandIndex4", "LeftToe_End", "HeadTop_End"))

    report = templates.align("biped", [joints["Hips"]], "mixamo")

    assert [name for name, _ in report["skipped"]] == ["root"]
    last, before = _mixamo_pos("LeftHandIndex3"), _mixamo_pos("LeftHandIndex2")
    assert (_guide_pos("l_index", -1) - last) * (last - before) > 0
    assert _guide_pos("l_foot", -1).z > _mixamo_pos("LeftToeBase").z + 1
    assert _guide_pos("head", -1).y > _mixamo_pos("Head").y + 1


def _humanik(table, names):
    """Characterize the skeleton ``names`` (slot -> joint) as a HumanIK
    character and return it."""
    from maya import mel

    cmds.loadPlugin("mayaHIK", quiet=True)
    character = cmds.createNode("HIKCharacterNode", name="Character1")
    for slot, joint in names.items():
        node_id = mel.eval(f'hikGetNodeIdFromName("{slot}")')
        mel.eval(f'setCharacterObject("{joint}", "{character}", {node_id}, 0)')
    return character


def test_align_to_humanik_finds_joints_by_their_slots_not_their_names(new_scene):
    templates.build_template("biped")
    # The Mixamo layout, with every joint renamed to something HumanIK can't guess.
    odd = {name: f"bone_{i:02d}" for i, name in enumerate(_MIXAMO)}
    renamed = {odd[name]: ((odd[p] if p else None), at) for name, (p, at) in _MIXAMO.items()}
    joints = _skeleton(renamed, namespace=None)
    cmds.select(clear=True)
    reference = cmds.joint(name="bone_ref", position=(0, 0, 0))
    cmds.parent(joints[odd["Hips"]], reference)
    joints = {name: cmds.ls(odd[name], long=True)[0] for name in _MIXAMO}
    _humanik(renamed, {"Reference": reference, **{name: joints[name] for name in _MIXAMO if name != "HeadTop_End"
                                                  and name != "LeftToe_End"}})

    report = templates.align("biped", [joints["Spine1"]])

    assert report["skeleton"] == "humanik"
    assert not report["skipped"], report["skipped"]
    assert _close(_guide_pos("root", 0), (0, 0, 0))
    assert _close(_guide_pos("l_arm", 0), _mixamo_pos("LeftArm"))
    assert _close(_guide_pos("l_arm", 1), _mixamo_pos("LeftForeArm"))
    assert _close(_guide_pos("l_leg", -1), _mixamo_pos("LeftFoot"))
    assert _close(_guide_pos("l_pinky", -1), _mixamo_pos("LeftHandPinky4"))


def test_humanik_neck_middle_goes_on_neck1_when_it_is_defined(new_scene):
    templates.build_template("biped")
    table = {}
    for name, entry in _MIXAMO.items():
        if name == "Head":
            table["Neck1"] = ("Neck", (0, 155, 0))
            entry = ("Neck1", entry[1])
        table[name] = entry
    joints = _skeleton(table, namespace=None)
    _humanik(table, {name: joints[name] for name in ("Hips", "Spine", "Neck", "Neck1", "Head")})

    templates.align("biped", [joints["Hips"]], "humanik")

    assert _close(_guide_pos("neck", 1), (0, 155, 0))


def test_ue5_neck_spreads_evenly_without_neck_02(new_scene):
    templates.build_template("biped")
    table = {name: entry for name, entry in _UE5.items() if name != "neck_02"}
    table["head"] = ("neck_01", _UE5["head"][1])
    joints = _skeleton(table)

    report = templates.align("biped", [joints["root"]], "ue5")

    assert "neck" in report["aligned"]
    assert _close(_guide_pos("neck", 1), (_ue5_pos("neck_01") + _ue5_pos("head")) * 0.5)
