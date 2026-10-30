import pytest
from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.core.selection import short_name
from kaiju_suite.tools.guide_tool import logic, templates

_FINGERS = ("index", "middle", "ring", "pinky")
_BIPED = [
    "root", "pelvis", "spine", "torso", "neck", "head", "l_shoulder", "l_arm", "l_hand",
    *(f"l_{f}_metacarpal" for f in _FINGERS), "l_thumb", *(f"l_{f}" for f in _FINGERS),
    "l_leg", "l_foot",
]
_QUADRUPED = ["root", "pelvis", "spine", "neck", "head", "tail", "l_scapula", "l_front_leg", "l_quad_leg"]


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
    assert list(templates.TEMPLATES) == ["biped", "quadruped"]
    assert [chain["name"] for chain in templates.TEMPLATES["biped"]] == _BIPED


def test_biped_chains_connect():
    c = _chains()
    for a, b in (("spine", "torso"), ("torso", "neck"), ("neck", "head"), ("l_shoulder", "l_arm"), ("l_arm", "l_hand"),
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


@pytest.mark.parametrize("template", ["biped", "quadruped"])
def test_pelvis_is_one_joint_where_the_spine_starts(template):
    c = _chains(template)
    assert c["pelvis"]["count"] == 0 and not c["pelvis"]["end_joint"] and not c["pelvis"]["mirror"]
    assert _close(c["pelvis"]["start"], c["spine"]["start"])
    pelvis_way = om.MVector(c["pelvis"]["end"]) - om.MVector(c["pelvis"]["start"])
    spine_way = om.MVector(c["spine"]["end"]) - om.MVector(c["spine"]["start"])
    assert (pelvis_way.normal() - spine_way.normal()).length() < 1e-6


def test_biped_spine_and_torso_split_the_back():
    c = _chains()
    assert (c["spine"]["count"], c["torso"]["count"]) == (2, 0)
    assert c["spine"]["end_joint"] and c["torso"]["end_joint"]
    for name, a, b in (("spine", (0, 100, 0), (0, 130, 0)), ("torso", (0, 130, 0), (0, 145, 0))):
        assert _close(c[name]["start"], a) and _close(c[name]["end"], b), name
    for key in ("aim", "up", "up_side"):
        assert c["torso"][key] == c["spine"][key], key


def test_quadruped_has_every_chain_in_order():
    assert [chain["name"] for chain in templates.TEMPLATES["quadruped"]] == _QUADRUPED


def test_quadruped_chains_connect():
    c = _chains("quadruped")
    for a, b in (("spine", "neck"), ("neck", "head"), ("l_scapula", "l_front_leg")):
        assert _close(c[a]["end"], c[b]["start"]), (a, b)
    assert _close(c["tail"]["start"], c["spine"]["start"])
    for leg in ("l_front_leg", "l_quad_leg"):
        assert c[leg]["end"][1] == 0, leg  # standing on the ground
    assert c["l_front_leg"]["start"][2] > 0 > c["l_quad_leg"]["start"][2]
    for name, chain in c.items():
        assert chain["mirror"] == name.startswith("l_"), name


def test_quadruped_chains_go_the_way_their_presets_do():
    c = _chains("quadruped")
    for name, preset in (("spine", "forward_spine"), ("tail", "tail"), ("l_scapula", "l_scapula"),
                         ("l_front_leg", "l_front_leg"), ("l_quad_leg", "l_quad_leg"), ("root", "root")):
        chain, preset = c[name], logic.PRESETS[preset]
        way = om.MVector(chain["end"]) - om.MVector(chain["start"])
        preset_way = om.MVector(preset["end"]) - om.MVector(preset["start"])
        assert (way.normal() - preset_way.normal()).length() < 1e-6, name
        for key in ("count", "aim", "up", "up_side", "end_joint", "mirror"):
            if name == "spine" and key in ("aim", "up"):
                continue  # aims Y with -Z up, as the biped spine does
            assert chain[key] == preset[key], (name, key)


def test_build_quadruped(new_scene):
    groups = templates.build_template("quadruped")

    assert [cmds.getAttr(f"{g}.kaijuGuides") for g in groups] == _QUADRUPED
    assert short_name(logic.joints("spine_guides_grp")[0]) == "spine_01_jnt"
    assert short_name(logic.mirrored_joints("l_front_leg_guides_grp")[0]) == "r_front_leg_01_jnt"
    cmds.undo()
    assert not cmds.ls(type="joint")


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

    world = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}
    for group in ("pelvis_guides_grp", "spine_guides_grp", "torso_guides_grp", "neck_guides_grp"):
        for joint in logic.joints(group):
            _assert_axes(joint, world)
    for joint in logic.joints("l_arm_guides_grp"):
        _assert_axes(joint, {"x": (1, 0, 0), "z": (0, 0, 1)})  # the elbow bends a little back


def test_quadruped_pelvis_is_world_aligned_and_spine_and_neck_aim_y_with_minus_z_up(new_scene):
    templates.build_template("quadruped")

    (pelvis,) = logic.joints("pelvis_guides_grp")
    _assert_axes(pelvis, {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)})
    for joint in logic.joints("spine_guides_grp"):
        _assert_axes(joint, {"x": (1, 0, 0), "y": (0, 0, 1), "z": (0, -1, 0)})
    for joint in logic.joints("neck_guides_grp"):  # leaning forward: Z forward and down
        assert abs(_axis(joint, "x").x - 1) < 1e-3 and _axis(joint, "z").y < 0 < _axis(joint, "z").z, joint


def _assert_axes(joint, want):
    for axis, vector in want.items():
        assert (_axis(joint, axis) - om.MVector(vector)).length() < 1e-3, (joint, axis, _axis(joint, axis))


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


# -- delete_template ----------------------------------------------------------------


def test_delete_template_deletes_every_chains_guides_and_keeps_the_joints(new_scene):
    templates.build_template("quadruped")
    joints = {c["name"]: logic.joints(f"{c['name']}_guides_grp") for c in templates.TEMPLATES["quadruped"]}
    where = {j: _pos(j) for chain in joints.values() for j in chain}
    mirrored = logic.mirrored_joints("l_front_leg_guides_grp")

    uuids = {j: cmds.ls(j, uuid=True)[0] for j in where}
    mirrored = cmds.ls(mirrored, uuid=True)

    extracted = templates.delete_template("quadruped")

    assert not cmds.ls("*_guides_grp")
    assert extracted == [cmds.ls(uuids[j], long=True)[0] for chain in joints.values() for j in chain]
    for joint, at in where.items():
        joint = cmds.ls(uuids[joint], long=True)[0]  # parented now, so its path changed
        assert _close(_pos(joint), at), joint
        assert cmds.getAttr(f"{joint}.overrideEnabled") == 0  # no longer drawn as reference
    assert all(cmds.ls(j) for j in mirrored)


def test_delete_template_skips_chains_that_are_not_built(new_scene):
    templates.build_template("biped")
    logic.delete_guides("l_thumb_guides_grp")
    cmds.createNode("transform", name="other_guides_grp")  # not a guide group, not in the template

    templates.delete_template("biped")

    assert cmds.ls("*_guides_grp") == ["other_guides_grp"]


def test_delete_template_leaves_another_templates_chains(new_scene):
    templates.build_template("quadruped")
    logic.build_guides("l_arm", 1)  # a biped chain, not in the quadruped

    templates.delete_template("quadruped")

    assert cmds.ls("*_guides_grp") == ["l_arm_guides_grp"]


def test_delete_template_refuses_when_none_of_it_is_built(new_scene):
    with pytest.raises(ValueError, match="biped"):
        templates.delete_template("biped")
    with pytest.raises(ValueError, match="dragon"):
        templates.delete_template("dragon")


def test_delete_template_is_one_undo_step(new_scene):
    templates.build_template("biped")
    cmds.select(clear=True)

    templates.delete_template("biped")
    cmds.undo()

    assert len(cmds.ls("*_guides_grp")) == len(templates.TEMPLATES["biped"])
    assert logic.guides("l_arm_guides_grp")["chain"]


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
        ("spine", "pelvis", "spine_03"), ("torso", "spine_03", "neck_01"), ("neck", "neck_01", "head"), ("l_shoulder", "clavicle_l", "upperarm_l"),
        ("l_arm", "upperarm_l", "hand_l"), ("l_hand", "hand_l", "middle_01_l"),
        ("l_index_metacarpal", "hand_l", "index_01_l"), ("l_leg", "thigh_l", "foot_l"),
    ):
        assert _close(_guide_pos(chain, 0), _ue5_pos(start)), chain
        assert _close(_guide_pos(chain, -1), _ue5_pos(end)), chain
    for chain, start in (("root", "root"), ("pelvis", "pelvis"), ("head", "head"), ("l_index", "index_01_l"),
                         ("l_thumb", "thumb_01_l"), ("l_foot", "foot_l")):
        assert _close(_guide_pos(chain, 0), _ue5_pos(start)), chain


def test_align_puts_middle_guides_on_key_joints_when_the_counts_match(new_scene):
    templates.build_template("biped")
    joints = _skeleton()

    templates.align("biped", [joints["root"]], "ue5")

    for chain, index, joint in (
        ("spine", 1, "spine_01"), ("spine", 2, "spine_02"),
        ("l_arm", 1, "lowerarm_l"), ("l_leg", 1, "calf_l"), ("l_foot", 1, "ball_l"), ("neck", 1, "neck_02"),
        ("l_middle", 1, "middle_02_l"), ("l_middle", 2, "middle_03_l"), ("l_thumb", 1, "thumb_02_l"),
    ):
        assert _close(_guide_pos(chain, index), _ue5_pos(joint)), (chain, index)


def test_align_spreads_middle_guides_evenly_otherwise(new_scene):
    templates.build_template("biped")
    table = {name: entry for name, entry in _UE5.items() if name != "spine_02"}
    table["spine_03"] = ("spine_01", _UE5["spine_03"][1])
    joints = _skeleton(table)

    templates.align("biped", [joints["root"]], "ue5")

    start, end = _ue5_pos("pelvis"), _ue5_pos("spine_03")
    for i in range(1, 3):
        assert _close(_guide_pos("spine", i), start + (end - start) * (i / 3.0)), i


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
    assert _guide_pos("spine", "up").z < -1  # the spine and torso keep their up guides behind
    assert _guide_pos("torso", "up").z < -1


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
        ("spine", "Hips", "Spine2"), ("torso", "Spine2", "Neck"), ("neck", "Neck", "Head"),
        ("head", "Head", "HeadTop_End"),
        ("l_shoulder", "LeftShoulder", "LeftArm"), ("l_arm", "LeftArm", "LeftHand"),
        ("l_hand", "LeftHand", "LeftHandMiddle1"), ("l_ring_metacarpal", "LeftHand", "LeftHandRing1"),
        ("l_index", "LeftHandIndex1", "LeftHandIndex4"), ("l_thumb", "LeftHandThumb1", "LeftHandThumb4"),
        ("l_leg", "LeftUpLeg", "LeftFoot"), ("l_foot", "LeftFoot", "LeftToe_End"),
    ):
        assert _close(_guide_pos(chain, 0), _mixamo_pos(start)), chain
        assert _close(_guide_pos(chain, -1), _mixamo_pos(end)), chain
    assert _close(_guide_pos("spine", 1), _mixamo_pos("Spine"))
    assert _close(_guide_pos("spine", 2), _mixamo_pos("Spine1"))
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


# -- align: mGear -------------------------------------------------------------------

# The left and middle joints of the skeleton mGear 5.4.4 builds from its own
# biped template (biped.sgt), scaled up 10 times: twist joints along the arm
# and leg (the elbow and knee are the 4th), no root joint, fingers L0-L3 index
# to pinky.
_MGEAR = {
    "spine_C0_0_jnt": (None, (0.0, 108.5, 1.8)),
    "spine_C0_1_jnt": ("spine_C0_0_jnt", (0.0, 114.2, 1.8)),
    "spine_C0_2_jnt": ("spine_C0_1_jnt", (0.0, 119.9, 1.8)),
    "spine_C0_3_jnt": ("spine_C0_2_jnt", (0.0, 125.5, 1.8)),
    "spine_C0_4_jnt": ("spine_C0_3_jnt", (0.0, 131.2, 1.8)),
    "shoulder_L0_shoulder_jnt": ("spine_C0_4_jnt", (1.1, 147.7, 2.0)),
    "arm_L0_0_jnt": ("shoulder_L0_shoulder_jnt", (15.7, 144.7, -6.8)),
    "arm_L0_1_jnt": ("arm_L0_0_jnt", (21.9, 138.3, -7.2)),
    "arm_L0_2_jnt": ("arm_L0_1_jnt", (28.2, 131.9, -7.7)),
    "arm_L0_3_jnt": ("arm_L0_2_jnt", (34.2, 125.9, -8.1)),
    "arm_L0_4_jnt": ("arm_L0_3_jnt", (34.5, 125.5, -8.1)),
    "arm_L0_5_jnt": ("arm_L0_4_jnt", (34.9, 125.1, -8.1)),
    "arm_L0_6_jnt": ("arm_L0_5_jnt", (41.1, 118.9, -7.5)),
    "arm_L0_7_jnt": ("arm_L0_6_jnt", (47.7, 112.3, -6.9)),
    "arm_L0_8_jnt": ("arm_L0_7_jnt", (53.8, 106.1, -6.3)),
    "arm_L0_end_jnt": ("arm_L0_8_jnt", (54.2, 105.7, -6.2)),
    "meta_L0_0_jnt": ("arm_L0_end_jnt", (55.3, 103.8, -2.6)),
    "finger_L0_0_jnt": ("meta_L0_0_jnt", (60.3, 97.5, -1.1)),
    "finger_L0_1_jnt": ("finger_L0_0_jnt", (62.3, 94.5, 0.1)),
    "finger_L0_2_jnt": ("finger_L0_1_jnt", (63.8, 92.0, 1.2)),
    "meta_L0_1_jnt": ("meta_L0_0_jnt", (55.3, 103.5, -4.5)),
    "finger_L1_0_jnt": ("meta_L0_1_jnt", (61.1, 97.1, -3.6)),
    "finger_L1_1_jnt": ("finger_L1_0_jnt", (63.3, 94.1, -2.9)),
    "finger_L1_2_jnt": ("finger_L1_1_jnt", (65.4, 91.2, -2.2)),
    "meta_L0_2_jnt": ("meta_L0_1_jnt", (55.3, 103.2, -6.5)),
    "finger_L2_0_jnt": ("meta_L0_2_jnt", (60.8, 96.9, -6.2)),
    "finger_L2_1_jnt": ("finger_L2_0_jnt", (63.2, 94.2, -6.3)),
    "finger_L2_2_jnt": ("finger_L2_1_jnt", (65.2, 92.1, -6.3)),
    "meta_L0_3_jnt": ("meta_L0_2_jnt", (55.3, 102.9, -8.4)),
    "finger_L3_0_jnt": ("meta_L0_3_jnt", (60.1, 97.3, -8.4)),
    "finger_L3_1_jnt": ("finger_L3_0_jnt", (62.2, 95.0, -9.2)),
    "finger_L3_2_jnt": ("finger_L3_1_jnt", (63.6, 93.4, -9.8)),
    "leg_L0_0_jnt": ("spine_C0_0_jnt", (9.7, 97.2, 1.8)),
    "leg_L0_1_jnt": ("leg_L0_0_jnt", (9.7, 83.4, 0.6)),
    "leg_L0_2_jnt": ("leg_L0_1_jnt", (9.6, 69.5, -0.6)),
    "leg_L0_3_jnt": ("leg_L0_2_jnt", (9.5, 56.4, -1.8)),
    "leg_L0_4_jnt": ("leg_L0_3_jnt", (9.5, 55.5, -1.9)),
    "leg_L0_5_jnt": ("leg_L0_4_jnt", (9.5, 54.7, -2.0)),
    "leg_L0_6_jnt": ("leg_L0_5_jnt", (9.4, 41.1, -4.2)),
    "leg_L0_7_jnt": ("leg_L0_6_jnt", (9.4, 26.7, -6.6)),
    "leg_L0_8_jnt": ("leg_L0_7_jnt", (9.3, 13.1, -8.8)),
    "leg_L0_end_jnt": ("leg_L0_8_jnt", (9.3, 12.3, -9.0)),
    "foot_L0_0_jnt": ("leg_L0_end_jnt", (10.6, 4.9, 4.2)),
    "foot_L0_1_jnt": ("foot_L0_0_jnt", (11.1, 3.3, 9.4)),
    "neck_C0_0_jnt": ("spine_C0_4_jnt", (0.0, 152.8, -3.3)),
    "neck_C0_1_jnt": ("neck_C0_0_jnt", (0.0, 159.8, -1.5)),
    "neck_C0_2_jnt": ("neck_C0_1_jnt", (0.0, 166.8, 0.5)),
    "neck_C0_head_jnt": ("neck_C0_2_jnt", (0.0, 167.4, 0.5)),
    "thumb_L0_0_jnt": ("meta_L0_0_jnt", (55.1, 102.9, -3.1)),
    "thumb_L0_1_jnt": ("thumb_L0_0_jnt", (55.5, 99.9, -0.2)),
    "thumb_L0_2_jnt": ("thumb_L0_1_jnt", (56.0, 97.1, 2.2)),
}


def _mgear_pos(name):
    return om.MVector(_MGEAR[name][1])


def test_skeletons_list_mgear():
    assert templates.SKELETONS["mgear"]["label"] == "mGear biped"


def test_detect_finds_mgear(new_scene):
    joints = _skeleton(_MGEAR, namespace=None)
    assert templates.detect([joints["arm_L0_3_jnt"]]) == "mgear"


def test_align_to_mgear(new_scene):
    templates.build_template("biped")
    joints = _skeleton(_MGEAR, namespace="rig")

    report = templates.align("biped", [joints["spine_C0_0_jnt"]])

    assert report["skeleton"] == "mgear"
    assert [name for name, _ in report["skipped"]] == ["root"]  # mGear's biped has no root joint
    for chain, start, end in (
        ("spine", "spine_C0_0_jnt", "spine_C0_3_jnt"),
        ("torso", "spine_C0_3_jnt", "neck_C0_0_jnt"),
        ("neck", "neck_C0_0_jnt", "neck_C0_head_jnt"),
        ("l_shoulder", "shoulder_L0_shoulder_jnt", "arm_L0_0_jnt"),
        ("l_arm", "arm_L0_0_jnt", "arm_L0_end_jnt"),
        ("l_hand", "arm_L0_end_jnt", "finger_L1_0_jnt"),
        ("l_index_metacarpal", "arm_L0_end_jnt", "finger_L0_0_jnt"),
        ("l_pinky_metacarpal", "arm_L0_end_jnt", "finger_L3_0_jnt"),
        ("l_leg", "leg_L0_0_jnt", "leg_L0_end_jnt"),
        ("l_foot", "leg_L0_end_jnt", "foot_L0_1_jnt"),
    ):
        assert _close(_guide_pos(chain, 0), _mgear_pos(start)), chain
        assert _close(_guide_pos(chain, -1), _mgear_pos(end)), chain
    assert _close(_guide_pos("head", 0), _mgear_pos("neck_C0_head_jnt"))
    assert _close(_guide_pos("neck", 1), _mgear_pos("neck_C0_1_jnt"))
    assert _close(_guide_pos("l_arm", 1), _mgear_pos("arm_L0_4_jnt"))  # the elbow, not a twist joint
    assert _close(_guide_pos("l_leg", 1), _mgear_pos("leg_L0_4_jnt"))
    assert _close(_guide_pos("l_foot", 1), _mgear_pos("foot_L0_0_jnt"))
    for chain, finger in (("l_thumb", "thumb_L0"), ("l_index", "finger_L0"), ("l_ring", "finger_L2")):
        assert _close(_guide_pos(chain, 0), _mgear_pos(f"{finger}_0_jnt")), chain
        assert _close(_guide_pos(chain, 2), _mgear_pos(f"{finger}_2_jnt")), chain
        last, before = _mgear_pos(f"{finger}_2_jnt"), _mgear_pos(f"{finger}_1_jnt")
        assert (_guide_pos(chain, -1) - last) * (last - before) > 0, chain  # past the last knuckle


def test_align_to_mgear_bends_the_arm_up_guide_toward_the_elbow(new_scene):
    templates.build_template("biped")
    joints = _skeleton(_MGEAR, namespace=None)

    templates.align("biped", [joints["spine_C0_0_jnt"]], "mgear")

    start, end = _mgear_pos("arm_L0_0_jnt"), _mgear_pos("arm_L0_end_jnt")
    span = end - start
    elbow = _mgear_pos("arm_L0_4_jnt") - start
    bend = elbow - span * ((elbow * span) / (span * span))
    assert (_guide_pos("l_arm", "up") - start) * bend > 0


# -- align: quadrupeds ---------------------------------------------------------------

# The middle and left joints of the skeleton mGear 5.4.4 builds from its own
# quadruped template (quadruped.sgt), scaled up 40 times: twist joints along
# both legs (elbow and stifle on the 3rd, wrist and hock on the 6th), no root
# or tail joints.
_MGEAR_QUADRUPED = {
    "spine_C0_0_jnt": (None, (0.0, 96.8, -49.2)),
    "legBack_L0_0_jnt": ("spine_C0_0_jnt", (50.8, 92.8, -51.2)),
    "legBack_L0_1_jnt": ("legBack_L0_0_jnt", (50.8, 82.0, -48.0)),
    "legBack_L0_2_jnt": ("legBack_L0_1_jnt", (50.8, 71.2, -44.8)),
    "legBack_L0_3_jnt": ("legBack_L0_2_jnt", (50.8, 60.0, -41.6)),
    "legBack_L0_4_jnt": ("legBack_L0_3_jnt", (50.8, 46.0, -47.2)),
    "legBack_L0_5_jnt": ("legBack_L0_4_jnt", (50.8, 32.0, -52.4)),
    "legBack_L0_6_jnt": ("legBack_L0_5_jnt", (50.8, 17.6, -58.0)),
    "legBack_L0_7_jnt": ("legBack_L0_6_jnt", (50.8, 12.8, -56.4)),
    "legBack_L0_8_jnt": ("legBack_L0_7_jnt", (50.8, 7.6, -55.2)),
    "legBack_L0_9_jnt": ("legBack_L0_8_jnt", (50.8, 2.4, -53.6)),
    "legBack_L0_end_jnt": ("legBack_L0_9_jnt", (50.8, 2.4, -53.6)),
    "footBack_L0_0_jnt": ("legBack_L0_end_jnt", (50.8, 2.4, -51.2)),
    "spine_C0_1_jnt": ("spine_C0_0_jnt", (0.0, 96.8, -18.0)),
    "spine_C0_2_jnt": ("spine_C0_1_jnt", (0.0, 96.8, 13.2)),
    "spine_C0_3_jnt": ("spine_C0_2_jnt", (0.0, 96.8, 44.8)),
    "spine_C0_4_jnt": ("spine_C0_3_jnt", (0.0, 96.8, 76.0)),
    "shoulder_L0_0_jnt": ("spine_C0_4_jnt", (4.0, 101.2, 79.6)),
    "legFront_L0_0_jnt": ("shoulder_L0_0_jnt", (37.2, 92.8, 88.0)),
    "legFront_L0_1_jnt": ("legFront_L0_0_jnt", (37.2, 81.6, 85.6)),
    "legFront_L0_2_jnt": ("legFront_L0_1_jnt", (37.2, 70.4, 82.8)),
    "legFront_L0_3_jnt": ("legFront_L0_2_jnt", (37.2, 58.8, 80.4)),
    "legFront_L0_4_jnt": ("legFront_L0_3_jnt", (37.2, 46.4, 80.8)),
    "legFront_L0_5_jnt": ("legFront_L0_4_jnt", (37.2, 33.6, 81.2)),
    "legFront_L0_6_jnt": ("legFront_L0_5_jnt", (37.2, 21.2, 81.6)),
    "legFront_L0_7_jnt": ("legFront_L0_6_jnt", (37.2, 15.2, 81.6)),
    "legFront_L0_8_jnt": ("legFront_L0_7_jnt", (37.2, 9.2, 81.6)),
    "legFront_L0_9_jnt": ("legFront_L0_8_jnt", (37.2, 3.2, 81.6)),
    "legFront_L0_end_jnt": ("legFront_L0_9_jnt", (37.2, 3.2, 81.6)),
    "footFront_L0_0_jnt": ("legFront_L0_end_jnt", (37.2, 3.2, 85.6)),
    "neck_C0_0_jnt": ("spine_C0_4_jnt", (0.0, 98.8, 82.8)),
    "neck_C0_1_jnt": ("neck_C0_0_jnt", (0.0, 104.4, 97.2)),
    "neck_C0_2_jnt": ("neck_C0_1_jnt", (0.0, 110.4, 111.2)),
    "neck_C0_3_jnt": ("neck_C0_2_jnt", (0.0, 116.4, 125.6)),
    "neck_C0_4_jnt": ("neck_C0_3_jnt", (0.0, 122.8, 139.6)),
    "neck_C0_head_jnt": ("neck_C0_4_jnt", (0.0, 122.8, 139.6)),
}


def _quad_pos(name):
    return om.MVector(_MGEAR_QUADRUPED[name][1])


def _side_of(chain, start, end, joint):
    """How far ``chain``'s up guide is to the side ``joint`` bends to, off the
    line ``start`` -> ``end`` (positive: the same side)."""
    a, b, j = _quad_pos(start), _quad_pos(end), _quad_pos(joint) - _quad_pos(start)
    span = b - a
    bend = j - span * ((j * span) / (span * span))
    return (_guide_pos(chain, "up") - a) * bend


def test_skeletons_say_which_template_they_fit():
    fits = {key: skeleton["template"] for key, skeleton in templates.SKELETONS.items()}
    assert fits == {
        "ue5": "biped", "humanik": "biped", "mixamo": "biped", "mgear": "biped",
        "mgear_quadruped": "quadruped", "humanik_quadruped": "quadruped",
    }
    assert templates.SKELETONS["mgear_quadruped"]["label"] == "mGear quadruped"
    assert templates.SKELETONS["humanik_quadruped"]["label"] == "HumanIK quadruped"


def test_detect_only_picks_skeletons_for_the_template(new_scene):
    joints = _skeleton(_MGEAR_QUADRUPED, namespace=None)
    assert templates.detect([joints["spine_C0_2_jnt"]], "quadruped") == "mgear_quadruped"

    cmds.file(new=True, force=True)
    joints = _skeleton(_MGEAR, namespace=None)
    assert templates.detect([joints["spine_C0_2_jnt"]], "biped") == "mgear"

    cmds.file(new=True, force=True)
    joints = _skeleton()
    assert templates.detect([joints["root"]]) == "ue5"
    with pytest.raises(ValueError):
        templates.detect([joints["root"]], "quadruped")  # no quadruped skeleton has its names


def test_align_refuses_a_skeleton_for_another_template(new_scene):
    templates.build_template("quadruped")
    joints = _skeleton()
    with pytest.raises(ValueError, match="biped"):
        templates.align("quadruped", [joints["root"]], "ue5")


def test_align_quadruped_to_mgear(new_scene):
    templates.build_template("quadruped")
    joints = _skeleton(_MGEAR_QUADRUPED, namespace="rig")

    report = templates.align("quadruped", [joints["spine_C0_0_jnt"]])

    assert report["skeleton"] == "mgear_quadruped"
    assert sorted(name for name, _ in report["skipped"]) == ["root", "tail"]  # mGear's quadruped has neither
    for chain, start, end in (
        ("spine", "spine_C0_0_jnt", "neck_C0_0_jnt"),
        ("neck", "neck_C0_0_jnt", "neck_C0_head_jnt"),
        ("l_scapula", "shoulder_L0_0_jnt", "legFront_L0_0_jnt"),
        ("l_front_leg", "legFront_L0_0_jnt", "footFront_L0_0_jnt"),
        ("l_quad_leg", "legBack_L0_0_jnt", "footBack_L0_0_jnt"),
    ):
        assert _close(_guide_pos(chain, 0), _quad_pos(start)), chain
        assert _close(_guide_pos(chain, -1), _quad_pos(end)), chain
    assert _close(_guide_pos("head", 0), _quad_pos("neck_C0_head_jnt"))
    assert _close(_guide_pos("neck", 1), _quad_pos("neck_C0_2_jnt"))
    for chain, leg in (("l_front_leg", "legFront_L0"), ("l_quad_leg", "legBack_L0")):
        for i, joint in ((1, "3"), (2, "6"), (3, "end")):
            assert _close(_guide_pos(chain, i), _quad_pos(f"{leg}_{joint}_jnt")), (chain, i)


def test_align_quadruped_legs_put_the_up_guide_where_the_elbow_and_stifle_bend(new_scene):
    templates.build_template("quadruped")
    joints = _skeleton(_MGEAR_QUADRUPED, namespace=None)

    templates.align("quadruped", [joints["spine_C0_0_jnt"]], "mgear_quadruped")

    assert _side_of("l_front_leg", "legFront_L0_0_jnt", "footFront_L0_0_jnt", "legFront_L0_3_jnt") > 0
    assert _guide_pos("l_front_leg", "up").z < _quad_pos("legFront_L0_0_jnt").z  # elbow bends back
    # The hock bends back, but the stifle - the first joint - sets the side: forward.
    assert _side_of("l_quad_leg", "legBack_L0_0_jnt", "footBack_L0_0_jnt", "legBack_L0_3_jnt") > 0
    assert _guide_pos("l_quad_leg", "up").z > _quad_pos("legBack_L0_0_jnt").z


_HIK_QUADRUPED = {
    "Hips": "spine_C0_0_jnt", "Spine": "spine_C0_1_jnt", "Spine1": "spine_C0_2_jnt", "Spine2": "spine_C0_3_jnt",
    "Spine3": "spine_C0_4_jnt", "Neck": "neck_C0_0_jnt", "Neck1": "neck_C0_1_jnt", "Neck2": "neck_C0_2_jnt",
    "Neck3": "neck_C0_3_jnt", "Head": "neck_C0_head_jnt",
    "LeftShoulder": "shoulder_L0_0_jnt", "LeftArm": "legFront_L0_0_jnt", "LeftForeArm": "legFront_L0_3_jnt",
    "LeftHand": "legFront_L0_6_jnt", "LeftFingerBase": "legFront_L0_end_jnt",
    "LeftUpLeg": "legBack_L0_0_jnt", "LeftLeg": "legBack_L0_3_jnt", "LeftFoot": "legBack_L0_6_jnt",
    "LeftToeBase": "legBack_L0_end_jnt",
}


def test_align_quadruped_to_humanik_front_legs_in_the_arm_slots(new_scene):
    templates.build_template("quadruped")
    odd = {name: f"bone_{i:02d}" for i, name in enumerate(_MGEAR_QUADRUPED)}
    renamed = {odd[n]: ((odd[p] if p else None), at) for n, (p, at) in _MGEAR_QUADRUPED.items()}
    joints = _skeleton(renamed, namespace=None)
    _humanik(renamed, {slot: joints[odd[name]] for slot, name in _HIK_QUADRUPED.items()})

    report = templates.align("quadruped", [joints[odd["spine_C0_2_jnt"]]])

    assert report["skeleton"] == "humanik_quadruped"
    assert sorted(name for name, _ in report["skipped"]) == ["root", "tail"]
    assert _close(_guide_pos("spine", -1), _quad_pos("neck_C0_0_jnt"))
    assert _close(_guide_pos("l_scapula", 0), _quad_pos("shoulder_L0_0_jnt"))
    for chain, leg in (("l_front_leg", "legFront_L0"), ("l_quad_leg", "legBack_L0")):
        assert _close(_guide_pos(chain, 0), _quad_pos(f"{leg}_0_jnt")), chain
        assert _close(_guide_pos(chain, 3), _quad_pos(f"{leg}_end_jnt")), chain
        # No toe tip slot: the end goes a little ahead of the paw, along the ground.
        tip, paw = _guide_pos(chain, -1), _quad_pos(f"{leg}_end_jnt")
        assert abs(tip.y - paw.y) < 1e-3 and tip.z > paw.z + 1, chain


# -- default parents ----------------------------------------------------------------


def _parent(joint):
    return short_name((cmds.listRelatives(joint, parent=True) or [""])[0])


@pytest.mark.parametrize("template", ["biped", "quadruped"])
def test_every_chain_but_root_has_an_earlier_parent_chain(template):
    names = [chain["name"] for chain in templates.TEMPLATES[template]]
    parents = templates.PARENTS[template]
    assert sorted(parents) == sorted(names[1:])
    for child, parent in parents.items():
        assert names.index(parent) < names.index(child), child


def test_build_template_saves_the_parent_chains_end_joint_as_default_parent(new_scene):
    templates.build_template("biped")
    for joint, parent in (
        ("pelvis_01_jnt", "root_01_jnt"), ("spine_01_jnt", "pelvis_01_jnt"), ("torso_01_jnt", "spine_04_jnt_end"),
        ("neck_01_jnt", "torso_02_jnt_end"),
        ("l_shoulder_01_jnt", "torso_02_jnt_end"), ("r_shoulder_01_jnt", "torso_02_jnt_end"),
        ("l_arm_01_jnt", "l_shoulder_02_jnt_end"), ("r_arm_01_jnt", "r_shoulder_02_jnt_end"),
        ("l_index_01_jnt", "l_index_metacarpal_02_jnt_end"), ("l_thumb_01_jnt", "l_hand_01_jnt"),
        ("l_leg_01_jnt", "pelvis_01_jnt"), ("r_foot_01_jnt", "r_leg_03_jnt_end"),
    ):
        assert cmds.getAttr(f"{joint}.kaijuDefaultParentName") == parent, joint
    assert not cmds.attributeQuery("kaijuDefaultParentName", node="root_01_jnt", exists=True)
    assert not cmds.listRelatives("l_arm_01_jnt", parent=True)  # nothing moves until Delete


def test_delete_template_parents_the_biped_into_one_skeleton(new_scene):
    templates.build_template("biped")
    templates.delete_template("biped")

    for joint, parent in (
        ("pelvis_01_jnt", "root_01_jnt"), ("spine_01_jnt", "pelvis_01_jnt"), ("head_01_jnt", "neck_03_jnt_end"),
        ("r_shoulder_01_jnt", "torso_02_jnt_end"), ("r_hand_01_jnt", "r_arm_03_jnt_end"),
        ("l_middle_metacarpal_01_jnt", "l_hand_01_jnt"), ("r_pinky_01_jnt", "r_pinky_metacarpal_02_jnt_end"),
        ("l_leg_01_jnt", "pelvis_01_jnt"), ("l_foot_01_jnt", "l_leg_03_jnt_end"),
    ):
        assert _parent(joint) == parent, joint
    roots = [j for j in cmds.ls(type="joint", long=True) if j.count("|") == 1]
    assert roots == ["|root_01_jnt"]


def test_delete_template_parents_the_quadruped(new_scene):
    templates.build_template("quadruped")
    templates.delete_template("quadruped")
    for joint, parent in (
        ("tail_01_jnt", "pelvis_01_jnt"), ("l_quad_leg_01_jnt", "pelvis_01_jnt"),
        ("r_scapula_01_jnt", "spine_05_jnt_end"), ("r_front_leg_01_jnt", "r_scapula_02_jnt_end"),
    ):
        assert _parent(joint) == parent, joint


def test_delete_template_leaves_a_chain_whose_parent_is_gone_at_the_world(new_scene):
    templates.build_template("biped")
    hand = logic.joints("l_hand_guides_grp")
    logic.delete_guides("l_hand_guides_grp")
    cmds.delete(hand)

    templates.delete_template("biped")

    assert _parent("l_index_metacarpal_01_jnt") == ""
    assert _parent("l_arm_01_jnt") == "l_shoulder_02_jnt_end"


def test_delete_template_with_only_root_built(new_scene):
    logic.build_guides(**templates.TEMPLATES["biped"][0])
    assert templates.delete_template("biped") == ["|root_01_jnt"]


# -- building again after Delete -----------------------------------------------------


def _uuids(template):
    groups = templates._built(template)
    return [cmds.ls(logic.joints(g) + logic.mirrored_joints(g), uuid=True) for g in groups]


@pytest.mark.parametrize("template", ["biped", "quadruped"])
def test_build_template_after_delete_unparents_and_picks_up_the_same_joints(new_scene, template):
    templates.build_template(template)
    before = _uuids(template)
    templates.delete_template(template)

    groups = templates.build_template(template)

    assert [cmds.getAttr(f"{g}.kaijuGuides") for g in groups] == [c["name"] for c in templates.TEMPLATES[template]]
    assert _uuids(template) == before
    for group in groups:
        for top in (logic.joints(group)[0], *logic.mirrored_joints(group)[:1]):
            assert not cmds.listRelatives(top, parent=True), top


def test_build_template_after_delete_keeps_where_joints_were_moved(new_scene):
    templates.build_template("biped")
    templates.delete_template("biped")
    cmds.xform("l_arm_02_jnt", worldSpace=True, translation=(40, 140, -6))

    templates.build_template("biped")

    assert _close(_guide_pos("l_arm", 1), (40, 140, -6))  # the joint then stays on the chain's plane


def test_build_and_delete_again_makes_the_same_skeleton(new_scene):
    templates.build_template("biped")
    templates.delete_template("biped")
    templates.build_template("biped")
    templates.delete_template("biped")

    assert _parent("l_index_01_jnt") == "l_index_metacarpal_02_jnt_end"
    assert _parent("r_foot_01_jnt") == "r_leg_03_jnt_end"
    roots = [j for j in cmds.ls(type="joint", long=True) if j.count("|") == 1]
    assert roots == ["|root_01_jnt"]


def test_build_template_after_delete_is_one_undo_step(new_scene):
    templates.build_template("biped")
    templates.delete_template("biped")
    cmds.select(clear=True)

    templates.build_template("biped")
    cmds.undo()

    assert not cmds.ls("*_guides_grp")
    assert _parent("l_arm_01_jnt") == "l_shoulder_02_jnt_end"


def test_build_template_picks_up_a_chain_the_chain_tab_deleted(new_scene):
    templates.build_template("biped")
    arm = cmds.ls(logic.joints("l_arm_guides_grp"), uuid=True)
    logic.delete_guides("l_arm_guides_grp")

    templates.build_template("biped")

    assert cmds.ls(logic.joints("l_arm_guides_grp"), uuid=True) == arm
