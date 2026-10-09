import os

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import data, logic, products, versions
from kaiju_suite.tools.assembler.products import joints

ATTRS = (
    "translate",
    "rotate",
    "jointOrient",
    "rotateOrder",
    "scale",
    "segmentScaleCompensate",
    "radius",
    "preferredAngle",
    "side",
    "type",
    "otherType",
)


def _joint(name, parent=None, **values):
    node = cmds.createNode("joint", name=name, parent=parent, skipSelect=True)
    for attr, value in values.items():
        if isinstance(value, str):
            cmds.setAttr(f"{node}.{attr}", value, type="string")
        elif isinstance(value, (tuple, list)):
            cmds.setAttr(f"{node}.{attr}", *value)
        else:
            cmds.setAttr(f"{node}.{attr}", value)
    return cmds.ls(node, long=True)[0]


def _values(node):
    found = {}
    for attr in ATTRS:
        value = cmds.getAttr(f"{node}.{attr}")
        if isinstance(value, list):
            value = [round(v, 5) for v in value[0]]
        elif isinstance(value, float):
            value = round(value, 5)
        found[attr] = value
    return found


def _chain():
    """root > mid > end, with every saved attribute off its default."""
    root = _joint(
        "root",
        translate=(1, 2, 3),
        rotate=(10, 20, 30),
        jointOrient=(5, 6, 7),
        rotateOrder=3,
        scale=(1, 2, 1),
        segmentScaleCompensate=False,
        radius=2.5,
        preferredAngle=(0, 45, 0),
        side=1,
        type=18,
        otherType="hip_custom",
    )
    mid = _joint("mid", root, translate=(0, 4, 0), side=2, type=2)
    end = _joint("end", mid, translate=(0, 3, 0), radius=0.5)
    return root, mid, end


def _publish(tmp_path, *selection, name="skel"):
    path = joints.PRODUCT.create(str(tmp_path), name)
    cmds.select(selection)
    message = versions.publish_action(path).fn()
    return path, message


# -- product ----------------------------------------------------------------


def test_joints_is_discovered_and_owns_jnt(tmp_path):
    assert joints.PRODUCT in products.discover()
    assert joints.PRODUCT.name == "Joints"
    assert joints.PRODUCT.extensions == (".jnt",)
    assert joints.PRODUCT.order == 40
    assert joints.PRODUCT.runnable and joints.PRODUCT.versioned
    path = joints.PRODUCT.creators[0].fn(str(tmp_path), "skel", None)
    assert path == str(tmp_path / "skel.jnt") and os.path.getsize(path) == 0
    assert products.product_for(path) is joints.PRODUCT


# -- publish and run --------------------------------------------------------


def test_round_trip_restores_hierarchy_and_values(new_scene, tmp_path):
    chain = _chain()
    before = [_values(j) for j in chain]
    path, message = _publish(tmp_path, chain[0])
    assert message == "Published Joints skel.jnt v001"

    cmds.file(new=True, force=True)
    logic.run_steps([path])

    after = ["|root", "|root|mid", "|root|mid|end"]
    assert all(cmds.nodeType(j) == "joint" for j in after)
    assert [_values(j) for j in after] == before


def test_publish_takes_descendant_joints_only(new_scene, tmp_path):
    root, mid, end = _chain()
    cmds.createNode("transform", name="not_a_joint", parent=mid)
    path, _ = _publish(tmp_path, root)
    names = [j["name"] for j in data.read(path, "joints")["joints"]]
    assert names == ["root", "mid", "end"]


def test_publish_selecting_a_child_too_saves_it_once(new_scene, tmp_path):
    root, mid, end = _chain()
    path, _ = _publish(tmp_path, end, root)
    names = [j["name"] for j in data.read(path, "joints")["joints"]]
    assert names == ["root", "mid", "end"]


def test_running_twice_makes_numbered_copies(new_scene, tmp_path):
    chain = _chain()
    before = [_values(j) for j in chain]
    path, _ = _publish(tmp_path, chain[0])

    message = joints.PRODUCT.run(path)
    assert "3" in message

    # Originals untouched...
    assert [_values(j) for j in chain] == before
    assert cmds.listRelatives("|root|mid", children=True) == ["end"]
    # ...and each copy's children are under its own renamed parent.
    assert cmds.objExists("|root1|mid1|end1")
    assert [_values(j) for j in ("|root1", "|root1|mid1", "|root1|mid1|end1")] == before


def test_same_names_in_different_chains_keep_their_parents(new_scene, tmp_path):
    grp_a = _joint("a")
    _joint("end", grp_a, translate=(1, 0, 0))
    grp_b = _joint("b")
    _joint("end", grp_b, translate=(2, 0, 0))
    path, _ = _publish(tmp_path, grp_a, grp_b)

    cmds.file(new=True, force=True)
    joints.PRODUCT.run(path)
    assert cmds.getAttr("|a|end.translateX") == 1
    # The second "end" was taken by then, so it's numbered.
    assert cmds.getAttr("|b|end1.translateX") == 2


def test_parent_outside_the_file_is_found_by_name(new_scene, tmp_path):
    rig = cmds.createNode("transform", name="rig")
    arm = _joint("arm", rig)
    path, _ = _publish(tmp_path, arm)
    saved = data.read(path, "joints")["joints"][0]
    assert saved["parent"] == "rig" and saved["parent_index"] is None

    cmds.file(new=True, force=True)
    cmds.createNode("transform", name="rig")
    joints.PRODUCT.run(path)
    assert cmds.objExists("|rig|arm")


def test_parent_missing_from_the_scene_means_world(new_scene, tmp_path):
    rig = cmds.createNode("transform", name="rig")
    arm = _joint("arm", rig)
    path, _ = _publish(tmp_path, arm)

    cmds.file(new=True, force=True)
    joints.PRODUCT.run(path)
    assert cmds.objExists("|arm")


def test_ambiguous_outside_parent_creates_nothing(new_scene, tmp_path):
    rig = cmds.createNode("transform", name="rig")
    arm = _joint("arm", rig)
    path, _ = _publish(tmp_path, arm)

    cmds.file(new=True, force=True)
    for group in ("a", "b"):
        cmds.createNode("transform", name="rig", parent=cmds.createNode("transform", name=group))
    with pytest.raises(RuntimeError) as info:
        joints.PRODUCT.run(path)
    assert "rig" in str(info.value)
    assert not cmds.ls(type="joint")


def test_empty_file_is_skipped(new_scene, tmp_path):
    path = joints.PRODUCT.create(str(tmp_path), "skel")
    assert logic.run_steps([path]) == [path]
    assert not cmds.ls(type="joint")


def test_one_undo_reverts_a_run(new_scene, tmp_path):
    chain = _chain()
    path, _ = _publish(tmp_path, chain[0])
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    joints.PRODUCT.run(path)
    assert len(cmds.ls(type="joint")) == 3
    cmds.undo()
    assert not cmds.ls(type="joint")


# -- publish checks and versions --------------------------------------------


def test_publish_problems(new_scene, tmp_path):
    path = joints.PRODUCT.create(str(tmp_path), "skel")
    cmds.select(clear=True)
    (problem,) = versions.publish_problems(path)
    assert "Nothing selected" in problem

    cmds.select(cmds.createNode("transform"))
    (problem,) = versions.publish_problems(path)
    assert "joint" in problem.lower()

    cmds.select(_joint("root"))
    assert versions.publish_problems(path) == []


def test_publish_without_joints_raises_and_writes_nothing(new_scene, tmp_path):
    path = joints.PRODUCT.create(str(tmp_path), "skel")
    cmds.select(cmds.createNode("transform"))
    with pytest.raises(RuntimeError):
        versions.publish_action(path).fn()
    assert os.path.getsize(path) == 0


def test_republishing_adds_a_version_only_on_change(new_scene, tmp_path):
    root, mid, end = _chain()
    path, message = _publish(tmp_path, root)
    assert message.endswith("v001")

    cmds.select(root)
    assert versions.publish_action(path).fn().endswith("v001")
    assert [v.number for v in versions.list_versions(path)] == [1]

    cmds.setAttr(f"{end}.translateY", 9)
    assert versions.publish_action(path).fn().endswith("v002")


def test_panel_describes_the_joints(new_scene, tmp_path):
    root, mid, end = _chain()
    other = _joint("other")
    path, _ = _publish(tmp_path, root, other)
    assert joints.PRODUCT.panel(path).info == ["4 joints", "Roots: root, other"]
