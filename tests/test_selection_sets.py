import pytest
from maya import cmds

from kaiju_suite.tools.selection_sets import logic


def _ctrl(name, parent=None):
    """A transform with a nurbsCurve shape; returns its long name."""
    curve = cmds.circle(name=name, constructionHistory=False)[0]
    if parent:
        curve = cmds.parent(curve, parent)[0]
    return cmds.ls(curve, long=True)[0]


def _long(nodes):
    return cmds.ls(nodes, long=True)


# -- saving and listing -----------------------------------------------------


def test_save_set_stores_members_in_the_scene(new_scene):
    a, b = _ctrl("L_arm_ctrl"), _ctrl("L_hand_ctrl")

    logic.save_set("L_arm", [a, b])

    assert logic.list_sets() == ["L_arm"]
    assert sorted(logic.members("L_arm")) == sorted([a, b])
    # Stored as an objectSet under the parent set, so it saves with the file.
    assert cmds.objExists(logic.PARENT)
    assert cmds.nodeType(logic.PARENT) == "objectSet"
    children = cmds.sets(logic.PARENT, query=True)
    assert len(children) == 1 and cmds.nodeType(children[0]) == "objectSet"


def test_list_sets_is_sorted_by_name(new_scene):
    a = _ctrl("a_ctrl")
    for name in ("zed", "Arm", "body"):
        logic.save_set(name, [a])

    assert logic.list_sets() == ["Arm", "body", "zed"]


def test_list_sets_is_empty_in_a_new_scene(new_scene):
    assert logic.list_sets() == []


def test_save_set_rejects_bad_names_and_duplicates(new_scene):
    a = _ctrl("a_ctrl")
    logic.save_set("arm", [a])

    for bad in ("", "has space", "1st", "a-b", "arm"):
        with pytest.raises(ValueError):
            logic.save_set(bad, [a])


def test_save_set_needs_nodes(new_scene):
    with pytest.raises(ValueError):
        logic.save_set("empty", [])


def test_members_drop_deleted_nodes(new_scene):
    a, b = _ctrl("a_ctrl"), _ctrl("b_ctrl")
    logic.save_set("both", [a, b])

    cmds.delete(b)

    assert logic.members("both") == [a]


def test_members_follow_renamed_and_reparented_nodes(new_scene):
    a = _ctrl("a_ctrl")
    logic.save_set("one", [a])
    group = cmds.createNode("transform", name="grp")

    cmds.parent(cmds.rename(a, "renamed_ctrl"), group)

    assert logic.members("one") == ["|grp|renamed_ctrl"]


def test_save_set_is_one_undo_step(new_scene):
    a = _ctrl("a_ctrl")
    cmds.flushUndo()

    logic.save_set("arm", [a])
    cmds.undo()

    assert logic.list_sets() == []


# -- recall -----------------------------------------------------------------


def test_recall_replaces_or_adds_to_the_selection(new_scene):
    a, b, c = _ctrl("a_ctrl"), _ctrl("b_ctrl"), _ctrl("c_ctrl")
    logic.save_set("ab", [a, b])

    cmds.select(c)
    logic.recall("ab")
    assert sorted(cmds.ls(selection=True, long=True)) == sorted([a, b])

    cmds.select(c)
    logic.recall("ab", add=True)
    assert sorted(cmds.ls(selection=True, long=True)) == sorted([a, b, c])


def test_recall_unknown_set_raises(new_scene):
    with pytest.raises(ValueError):
        logic.recall("nope")


# -- update, rename, delete -------------------------------------------------


def test_update_set_replaces_its_members(new_scene):
    a, b = _ctrl("a_ctrl"), _ctrl("b_ctrl")
    logic.save_set("one", [a])

    logic.update_set("one", [b])

    assert logic.members("one") == [b]


def test_update_set_is_one_undo_step(new_scene):
    a, b = _ctrl("a_ctrl"), _ctrl("b_ctrl")
    logic.save_set("one", [a])
    cmds.flushUndo()

    logic.update_set("one", [b])
    cmds.undo()

    assert logic.members("one") == [a]


def test_rename_set(new_scene):
    a = _ctrl("a_ctrl")
    logic.save_set("old", [a])
    logic.save_set("other", [a])

    logic.rename_set("old", "new")

    assert logic.list_sets() == ["new", "other"]
    assert logic.members("new") == [a]
    with pytest.raises(ValueError):
        logic.rename_set("new", "other")
    with pytest.raises(ValueError):
        logic.rename_set("new", "bad name")


def test_rename_set_is_one_undo_step(new_scene):
    a = _ctrl("a_ctrl")
    logic.save_set("old", [a])
    cmds.flushUndo()

    logic.rename_set("old", "new")
    cmds.undo()

    assert logic.list_sets() == ["old"]


def test_delete_set_keeps_its_members(new_scene):
    a = _ctrl("a_ctrl")
    logic.save_set("one", [a])
    logic.save_set("two", [a])

    logic.delete_set("one")

    assert logic.list_sets() == ["two"]
    assert cmds.objExists(a)


def test_delete_set_is_one_undo_step(new_scene):
    a = _ctrl("a_ctrl")
    logic.save_set("one", [a])
    cmds.flushUndo()

    logic.delete_set("one")
    cmds.undo()

    assert logic.list_sets() == ["one"]
    assert logic.members("one") == [a]


# -- mirror -----------------------------------------------------------------


def test_mirror_set_creates_the_opposite_side_set(new_scene):
    la, lh = _ctrl("L_arm_ctrl"), _ctrl("L_hand_ctrl")
    ra, rh = _ctrl("R_arm_ctrl"), _ctrl("R_hand_ctrl")
    spine = _ctrl("spine_ctrl")
    logic.save_set("L_arm", [la, lh, spine])

    result = logic.mirror_set("L_arm")

    assert result.name == "R_arm"
    assert result.skipped == []
    assert sorted(logic.members("R_arm")) == sorted([ra, rh, spine])


def test_mirror_set_skips_missing_opposites(new_scene):
    la, lh = _ctrl("L_arm_ctrl"), _ctrl("L_hand_ctrl")
    ra = _ctrl("R_arm_ctrl")
    logic.save_set("L_arm", [la, lh])

    result = logic.mirror_set("L_arm")

    assert logic.members("R_arm") == [ra]
    assert result.skipped == ["L_hand_ctrl"]


def test_mirror_set_works_with_namespaces(new_scene):
    cmds.namespace(add="char")
    la = _ctrl("char:L_arm_ctrl")
    ra = _ctrl("char:R_arm_ctrl")
    logic.save_set("leftArm", [la])

    result = logic.mirror_set("leftArm")

    assert result.name == "rightArm"
    assert logic.members("rightArm") == [ra]


def test_mirror_set_updates_an_existing_opposite_set(new_scene):
    la, ra, other = _ctrl("L_arm_ctrl"), _ctrl("R_arm_ctrl"), _ctrl("other_ctrl")
    logic.save_set("L_arm", [la])
    logic.save_set("R_arm", [other])

    logic.mirror_set("L_arm")

    assert logic.members("R_arm") == [ra]


def test_mirror_set_needs_a_side_in_its_name(new_scene):
    la = _ctrl("L_arm_ctrl")
    logic.save_set("arms", [la])

    with pytest.raises(ValueError):
        logic.mirror_set("arms")


def test_mirror_set_with_no_opposites_raises_and_changes_nothing(new_scene):
    la = _ctrl("L_arm_ctrl")
    logic.save_set("L_arm", [la])

    with pytest.raises(ValueError):
        logic.mirror_set("L_arm")
    assert logic.list_sets() == ["L_arm"]


def test_mirror_set_is_one_undo_step(new_scene):
    la, _ = _ctrl("L_arm_ctrl"), _ctrl("R_arm_ctrl")
    logic.save_set("L_arm", [la])
    cmds.flushUndo()

    logic.mirror_set("L_arm")
    cmds.undo()

    assert logic.list_sets() == ["L_arm"]


# -- rig controls -----------------------------------------------------------


def test_rig_controls_finds_curve_transforms_under_the_top_node(new_scene):
    rig = cmds.createNode("transform", name="rig")
    root = _ctrl("root_ctrl", rig)
    grp = cmds.createNode("transform", name="arm_grp", parent=root)
    arm = _ctrl("arm_ctrl", grp)
    cmds.polyCube(name="geo")
    cmds.parent("geo", rig)
    cmds.createNode("joint", name="jnt", parent=rig)
    outside = _ctrl("outside_ctrl")

    found = logic.rig_controls([rig])

    assert sorted(found) == sorted([root, arm])
    assert outside not in found


def test_rig_controls_includes_the_top_node_if_it_is_a_control(new_scene):
    root = _ctrl("root_ctrl")
    child = _ctrl("child_ctrl", root)

    assert sorted(logic.rig_controls([root])) == sorted([root, child])


def test_rig_controls_skips_intermediate_curve_shapes(new_scene):
    rig = cmds.createNode("transform", name="rig")
    holder = cmds.createNode("transform", name="holder", parent=rig)
    shape = cmds.createNode("nurbsCurve", name="holderShape", parent=holder)
    cmds.setAttr(f"{shape}.intermediateObject", True)

    assert logic.rig_controls([rig]) == []


# -- key and reset ----------------------------------------------------------


def test_key_sets_keys_on_keyable_attributes(new_scene):
    a = _ctrl("a_ctrl")
    cmds.setAttr(f"{a}.translateX", 3)
    cmds.setAttr(f"{a}.rotateZ", lock=True)

    count = logic.key([a])

    assert count == 1
    assert cmds.keyframe(f"{a}.translateX", query=True, keyframeCount=True) == 1
    assert cmds.keyframe(f"{a}.scaleY", query=True, keyframeCount=True) == 1
    assert not cmds.keyframe(f"{a}.rotateZ", query=True, keyframeCount=True)


def test_key_is_one_undo_step(new_scene):
    a, b = _ctrl("a_ctrl"), _ctrl("b_ctrl")
    cmds.flushUndo()

    logic.key([a, b])
    cmds.undo()

    assert not cmds.keyframe(a, query=True, keyframeCount=True)
    assert not cmds.keyframe(b, query=True, keyframeCount=True)


def test_reset_sets_keyable_attributes_to_defaults(new_scene):
    a = _ctrl("a_ctrl")
    cmds.addAttr(a, longName="blend", defaultValue=0.5, keyable=True)
    cmds.setAttr(f"{a}.translate", 1, 2, 3)
    cmds.setAttr(f"{a}.scaleX", 4)
    cmds.setAttr(f"{a}.blend", 1)

    result = logic.reset([a])

    assert result.changed == [a]
    assert result.skipped == []
    assert cmds.getAttr(f"{a}.translate")[0] == (0, 0, 0)
    assert cmds.getAttr(f"{a}.scaleX") == 1
    assert cmds.getAttr(f"{a}.blend") == 0.5


def test_reset_skips_locked_and_connected_attributes(new_scene):
    a, driver = _ctrl("a_ctrl"), _ctrl("driver_ctrl")
    cmds.setAttr(f"{a}.translateX", 5)
    cmds.setAttr(f"{a}.translateX", lock=True)
    cmds.setAttr(f"{driver}.translateY", 2)
    cmds.connectAttr(f"{driver}.translateY", f"{a}.translateY")
    cmds.setAttr(f"{a}.translateZ", 7)

    result = logic.reset([a])

    assert cmds.getAttr(f"{a}.translateX") == 5
    assert cmds.getAttr(f"{a}.translateY") == 2
    assert cmds.getAttr(f"{a}.translateZ") == 0
    assert "a_ctrl.translateY (connected)" in result.skipped


def test_reset_resets_keyed_attributes(new_scene):
    a = _ctrl("a_ctrl")
    cmds.setKeyframe(f"{a}.translateX", value=4, time=1)
    cmds.currentTime(1)

    logic.reset([a])

    assert cmds.getAttr(f"{a}.translateX") == 0


def test_reset_is_one_undo_step(new_scene):
    a, b = _ctrl("a_ctrl"), _ctrl("b_ctrl")
    cmds.setAttr(f"{a}.translateX", 3)
    cmds.setAttr(f"{b}.rotateY", 30)
    cmds.flushUndo()

    logic.reset([a, b])
    cmds.undo()

    assert cmds.getAttr(f"{a}.translateX") == 3
    assert cmds.getAttr(f"{b}.rotateY") == pytest.approx(30)


# -- tool -------------------------------------------------------------------


def test_tool_is_registered_under_animation():
    from kaiju_suite import registry

    tool = registry.find("Selection Sets")
    assert tool["category"] == "Animation"
    assert callable(tool["launch"])
