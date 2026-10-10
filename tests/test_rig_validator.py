import pytest
from maya import cmds

from kaiju_suite.tools.rig_validator import logic


def _control(name="arm_ctrl", parent=None):
    control = cmds.circle(name=name, constructionHistory=False)[0]
    if parent:
        control = cmds.parent(control, parent)[0]
    return cmds.ls(control, long=True)[0]


def _found(key):
    """What check ``key`` finds in the scene."""
    results = logic.run([key])
    assert [r.check.key for r in results] in ([], [key])
    return results[0].items if results else []


def _skinned(name="body"):
    """A cube skinned to two joints; returns (transform, skinCluster)."""
    cube = cmds.ls(cmds.polyCube(name=name, constructionHistory=False)[0], long=True)[0]
    cmds.select(clear=True)
    a = cmds.joint(name="a_jnt", position=(0, -1, 0))
    cmds.joint(name="b_jnt", position=(0, 1, 0))
    skin = cmds.skinCluster(a, cube, toSelectedBones=False)[0]
    cmds.select(clear=True)
    return cube, skin


def _unnormalize(skin, vertex=0):
    cmds.setAttr(f"{skin}.normalizeWeights", 0)
    for index in cmds.getAttr(f"{skin}.matrix", multiIndices=True):
        cmds.setAttr(f"{skin}.weightList[{vertex}].weights[{index}]", 0.3)


# -- the list of checks -------------------------------------------------------


def test_every_check_has_a_label_and_description():
    keys = [check.key for check in logic.CHECKS]
    assert len(keys) == len(set(keys))
    for check in logic.CHECKS:
        assert check.label and check.description


def test_the_checks():
    assert [check.key for check in logic.CHECKS] == [
        "control_transforms",
        "control_keys",
        "joint_rotations",
        "skin_weights",
        "duplicate_names",
        "namespaces",
        "unknown_nodes",
        "unused_nodes",
    ]


def test_an_empty_scene_passes_every_check(new_scene):
    assert logic.run() == []


def test_a_clean_rig_passes_every_check(new_scene):
    grp = cmds.group(empty=True, name="rig_grp")
    _control("arm_ctrl", grp)
    cmds.select(clear=True)
    joint = cmds.joint(name="arm_jnt")
    cmds.setAttr(f"{joint}.jointOrient", 0, 45, 0)
    _skinned()

    assert logic.run() == []


def test_unknown_check_key_raises():
    with pytest.raises(KeyError):
        logic.run(["no_such_check"])


# -- controls -----------------------------------------------------------------


def test_controls_are_transforms_with_curve_shapes(new_scene):
    control = _control()
    cmds.group(empty=True, name="grp")
    cmds.polyCube(name="cube", constructionHistory=False)

    assert logic.controls() == [control]


def test_control_transforms_finds_controls_off_their_defaults(new_scene):
    clean = _control("clean_ctrl")
    moved = _control("moved_ctrl")
    turned = _control("turned_ctrl")
    scaled = _control("scaled_ctrl")
    cmds.setAttr(f"{moved}.translateY", 1)
    cmds.setAttr(f"{turned}.rotateZ", 10)
    cmds.setAttr(f"{scaled}.scaleX", 2)
    # Not a control: no curve shape.
    grp = cmds.group(empty=True, name="grp")
    cmds.setAttr(f"{grp}.translateX", 5)

    assert sorted(_found("control_transforms")) == sorted([moved, turned, scaled])


def test_fixing_control_transforms_zeroes_them(new_scene):
    control = _control()
    cmds.xform(control, translation=(1, 2, 3), rotation=(10, 20, 30), scale=(2, 2, 2))

    logic.fix("control_transforms", [control])

    assert cmds.getAttr(f"{control}.translate")[0] == pytest.approx((0, 0, 0))
    assert cmds.getAttr(f"{control}.rotate")[0] == pytest.approx((0, 0, 0))
    assert cmds.getAttr(f"{control}.scale")[0] == pytest.approx((1, 1, 1))


def test_fixing_control_transforms_skips_locked_channels(new_scene):
    control = _control()
    cmds.setAttr(f"{control}.translate", 1, 2, 3)
    cmds.setAttr(f"{control}.translateY", lock=True)

    logic.fix("control_transforms", [control])

    assert cmds.getAttr(f"{control}.translate")[0] == pytest.approx((0, 2, 0))


def test_control_keys_finds_keyed_controls(new_scene):
    keyed = _control("keyed_ctrl")
    _control("still_ctrl")
    cmds.setKeyframe(f"{keyed}.rotateX", time=1, value=0)
    cmds.setKeyframe(f"{keyed}.rotateX", time=10, value=45)
    # Keys on something that isn't a control don't count.
    grp = cmds.group(empty=True, name="grp")
    cmds.setKeyframe(f"{grp}.translateX", time=1, value=1)

    assert _found("control_keys") == [keyed]


def test_control_keys_ignores_driven_keys(new_scene):
    driver = _control("driver_ctrl")
    driven = _control("driven_ctrl")
    cmds.setDrivenKeyframe(f"{driven}.translateX", currentDriver=f"{driver}.rotateX")

    assert _found("control_keys") == []


def test_fixing_control_keys_deletes_the_keys_and_keeps_the_value(new_scene):
    control = _control()
    cmds.setKeyframe(f"{control}.rotateX", time=1, value=30)
    cmds.currentTime(1)

    logic.fix("control_keys", [control])

    assert cmds.keyframe(control, query=True, keyframeCount=True) == 0
    assert cmds.getAttr(f"{control}.rotateX") == pytest.approx(30)


# -- joints -------------------------------------------------------------------


def test_joint_rotations_finds_joints_with_rotate_values(new_scene):
    cmds.select(clear=True)
    clean = cmds.ls(cmds.joint(name="clean_jnt"), long=True)[0]
    cmds.setAttr(f"{clean}.jointOrient", 0, 30, 0)
    cmds.select(clear=True)
    rotated = cmds.ls(cmds.joint(name="rotated_jnt"), long=True)[0]
    cmds.setAttr(f"{rotated}.rotateY", 30)

    assert _found("joint_rotations") == [rotated]


def test_joint_rotations_ignores_joints_driven_by_the_rig(new_scene):
    cmds.select(clear=True)
    joint = cmds.joint(name="driven_jnt")
    control = _control()
    cmds.setAttr(f"{control}.rotateY", 30)
    cmds.orientConstraint(control, joint)

    assert _found("joint_rotations") == []


def test_fixing_joint_rotations_moves_them_into_joint_orient(new_scene):
    cmds.select(clear=True)
    joint = cmds.ls(cmds.joint(name="arm_jnt"), long=True)[0]
    child = cmds.ls(cmds.joint(name="hand_jnt", position=(2, 1, 0)), long=True)[0]
    cmds.setAttr(f"{joint}.rotateOrder", 3)  # xzy
    cmds.setAttr(f"{joint}.jointOrient", 10, 0, 0)
    cmds.setAttr(f"{joint}.rotate", 20, 30, 40)
    before = cmds.xform(child, query=True, worldSpace=True, matrix=True)

    logic.fix("joint_rotations", [joint])

    assert cmds.getAttr(f"{joint}.rotate")[0] == pytest.approx((0, 0, 0))
    assert cmds.xform(child, query=True, worldSpace=True, matrix=True) == pytest.approx(before, abs=1e-6)


def test_fixing_joint_rotations_works_on_skinned_joints(new_scene):
    cube, skin = _skinned()
    joint = cmds.ls("a_jnt", long=True)[0]
    cmds.setAttr(f"{joint}.rotateX", 0)
    cmds.skinCluster(skin, edit=True, moveJointsMode=True)
    cmds.setAttr(f"{joint}.rotateX", 20)
    cmds.skinCluster(skin, edit=True, moveJointsMode=False)
    before = cmds.xform(f"{cube}.vtx[5]", query=True, worldSpace=True, translation=True)

    logic.fix("joint_rotations", [joint])

    assert cmds.getAttr(f"{joint}.rotate")[0] == pytest.approx((0, 0, 0))
    after = cmds.xform(f"{cube}.vtx[5]", query=True, worldSpace=True, translation=True)
    assert after == pytest.approx(before, abs=1e-5)


# -- skin weights -------------------------------------------------------------


def test_skin_weights_finds_vertices_that_dont_add_up_to_one(new_scene):
    cube, skin = _skinned()
    assert _found("skin_weights") == []

    _unnormalize(skin, vertex=2)

    assert _found("skin_weights") == [f"{cube}.vtx[2]"]


def test_fixing_skin_weights_normalizes_them(new_scene):
    cube, skin = _skinned()
    _unnormalize(skin, vertex=2)

    logic.fix("skin_weights", [f"{cube}.vtx[2]"])

    assert sum(cmds.skinPercent(skin, f"{cube}.vtx[2]", query=True, value=True)) == pytest.approx(1)


# -- names and namespaces -----------------------------------------------------


def test_duplicate_names_finds_every_node_sharing_a_short_name(new_scene):
    a = cmds.group(empty=True, name="a")
    b = cmds.group(empty=True, name="b")
    first = cmds.group(empty=True, name="hand_grp", parent=a)
    second = cmds.group(empty=True, name="hand_grp", parent=b)
    cmds.group(empty=True, name="unique_grp")

    assert sorted(_found("duplicate_names")) == sorted(cmds.ls([first, second], long=True))


def test_namespaces_finds_namespaces_not_from_references(new_scene):
    cmds.namespace(add="old")
    cmds.namespace(add="inner", parent="old")
    cmds.group(empty=True, name="old:grp")

    assert _found("namespaces") == [":old", ":old:inner"]


def test_select_targets_of_a_namespace_are_its_nodes(new_scene):
    cmds.namespace(add="old")
    grp = cmds.ls(cmds.group(empty=True, name="old:grp"), long=True)[0]

    assert logic.select_targets("namespaces", [":old"]) == [grp]


def test_select_targets_of_nodes_are_the_nodes_that_still_exist(new_scene):
    grp = cmds.ls(cmds.group(empty=True, name="grp"), long=True)[0]

    assert logic.select_targets("control_transforms", [grp, "|gone"]) == [grp]


def test_fixing_namespaces_merges_them_into_the_root(new_scene):
    cmds.namespace(add="old")
    cmds.namespace(add="inner", parent="old")
    cmds.group(empty=True, name="old:grp")
    cmds.group(empty=True, name="old:inner:loc")

    logic.fix("namespaces", [":old", ":old:inner"])

    assert not cmds.namespace(exists=":old")
    assert cmds.objExists("|grp") and cmds.objExists("|loc")


# -- unknown and unused nodes -------------------------------------------------


def test_unknown_nodes_finds_unknown_nodes(new_scene):
    node = cmds.createNode("unknown", name="mystery")

    assert _found("unknown_nodes") == [node]


def test_fixing_unknown_nodes_deletes_them_even_when_locked(new_scene):
    node = cmds.createNode("unknown", name="mystery")
    cmds.lockNode(node, lock=True)

    logic.fix("unknown_nodes", [node])

    assert not cmds.objExists(node)


def test_unused_nodes_finds_unused_materials_and_shading_groups_and_loose_curves(new_scene):
    used = cmds.shadingNode("lambert", asShader=True, name="used_mat")
    used_sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="used_SG")
    cmds.connectAttr(f"{used}.outColor", f"{used_sg}.surfaceShader")
    cube = cmds.polyCube(name="cube", constructionHistory=False)[0]
    cmds.sets(cube, edit=True, forceElement=used_sg)

    loose = cmds.shadingNode("lambert", asShader=True, name="loose_mat")
    empty_sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="empty_SG")
    cmds.connectAttr(f"{loose}.outColor", f"{empty_sg}.surfaceShader")
    curve = cmds.createNode("animCurveTL", name="loose_curve")

    assert sorted(_found("unused_nodes")) == sorted([loose, empty_sg, curve])


def test_fixing_unused_nodes_deletes_them(new_scene):
    curve = cmds.createNode("animCurveTL", name="loose_curve")

    logic.fix("unused_nodes", [curve])

    assert not cmds.objExists(curve)


# -- fixing in general --------------------------------------------------------


def test_only_some_checks_can_fix():
    assert {check.key for check in logic.CHECKS if check.fix} == {
        "control_transforms",
        "control_keys",
        "joint_rotations",
        "skin_weights",
        "namespaces",
        "unknown_nodes",
        "unused_nodes",
    }


def test_fixing_a_check_without_a_fix_raises(new_scene):
    with pytest.raises(ValueError):
        logic.fix("duplicate_names", [])


def _broken(key):
    """Make the scene fail check ``key``; returns what to fix."""
    if key == "control_transforms":
        control = _control()
        cmds.setAttr(f"{control}.translateX", 3)
        return [control]
    if key == "control_keys":
        control = _control()
        cmds.setKeyframe(f"{control}.translateX", time=1, value=1)
        return [control]
    if key == "joint_rotations":
        cmds.select(clear=True)
        joint = cmds.ls(cmds.joint(name="jnt"), long=True)[0]
        cmds.setAttr(f"{joint}.rotateY", 30)
        return [joint]
    if key == "skin_weights":
        cube, skin = _skinned()
        _unnormalize(skin)
        return [f"{cube}.vtx[0]"]
    if key == "namespaces":
        cmds.namespace(add="old")
        cmds.group(empty=True, name="old:grp")
        return [":old"]
    if key == "unknown_nodes":
        return [cmds.createNode("unknown", name="mystery")]
    if key == "unused_nodes":
        return [cmds.createNode("animCurveTL", name="loose_curve")]
    raise AssertionError(key)


@pytest.mark.parametrize("key", [c.key for c in logic.CHECKS if c.fix])
def test_fix_clears_the_problem_in_one_undo_step(new_scene, key):
    cmds.undoInfo(state=True)
    items = _broken(key)
    assert _found(key)

    logic.fix(key, items)

    assert _found(key) == []
    cmds.undo()
    assert _found(key)
