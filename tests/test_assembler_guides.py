import os

import pytest
from maya import cmds

from kaiju_suite.core import guides as core_guides
from kaiju_suite.tools.assembler import data, logic, products, versions
from kaiju_suite.tools.assembler.products import guides


def _pos(node):
    return [round(v, 5) for v in cmds.xform(node, query=True, worldSpace=True, translation=True)]


def _arm():
    group = core_guides.build_guides("arm", 1, start=(0, 0, 0), end=(8, 0, 0))
    cmds.xform(core_guides.guides(group)["chain"][1], worldSpace=True, translation=(4, 1, -1))
    return group


def _publish(tmp_path, *selection, name="body"):
    path = guides.PRODUCT.create(str(tmp_path), name)
    cmds.select(selection)
    message = versions.publish_action(path).fn()
    return path, message


def test_guide_is_discovered_and_owns_guide(tmp_path):
    assert guides.PRODUCT in products.discover()
    assert guides.PRODUCT.name == "Guide"
    assert guides.PRODUCT.extensions == (".guide",)
    assert guides.PRODUCT.runnable and guides.PRODUCT.versioned
    assert guides.PRODUCT.utility == "Guide Tool"
    path = guides.PRODUCT.creators[0].fn(str(tmp_path), "body", None)
    assert path == str(tmp_path / "body.guide") and os.path.getsize(path) == 0
    assert products.product_for(path) is guides.PRODUCT


def test_round_trip_rebuilds_the_guides(new_scene, tmp_path):
    group = _arm()
    before = [_pos(g) for g in core_guides.guides(group)["chain"]]
    path, message = _publish(tmp_path, core_guides.guides(group)["chain"][1])
    assert message == "Published Guide body.guide v001"
    assert data.read(path, "guides")["name"] == "arm"

    cmds.file(new=True, force=True)
    logic.run_steps([path])
    assert [_pos(g) for g in core_guides.guides("arm_guides_grp")["chain"]] == before
    assert len(core_guides.joints("arm_guides_grp")) == 3


def test_run_is_one_undo_step(new_scene, tmp_path):
    path, _ = _publish(tmp_path, _arm())
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True)
    guides.PRODUCT.run(path)
    assert cmds.objExists("arm_guides_grp")
    cmds.undo()
    assert not cmds.objExists("arm_guides_grp")
    assert cmds.ls(type="joint") == []


def test_running_with_the_guides_still_there_fails(new_scene, tmp_path):
    path, _ = _publish(tmp_path, _arm())
    with pytest.raises(RuntimeError, match="Guides already in the scene: arm"):
        guides.PRODUCT.run(path)
    assert cmds.ls("arm_guides_grp*") == ["arm_guides_grp"]


def test_publish_with_nothing_selected_is_refused(new_scene, tmp_path):
    path = guides.PRODUCT.create(str(tmp_path), "body")
    cmds.select(clear=True)
    assert guides.PRODUCT.publish_problems(path) == [
        "Nothing selected. Select guides, a guide group or a joint they drive."
    ]


def test_publish_refuses_guides_of_two_chains(new_scene, tmp_path):
    arm = _arm()
    leg = core_guides.build_guides("leg", 0, start=(0, 0, 0), end=(0, -8, 0))
    path = guides.PRODUCT.create(str(tmp_path), "body")
    cmds.select(arm, leg)
    assert guides.PRODUCT.publish_problems(path) == ["Select guides of one chain, not arm_guides_grp, leg_guides_grp."]


def test_double_click_hands_the_item_to_the_guide_tool(monkeypatch, tmp_path):
    tool = logic.utility_for(guides.PRODUCT)
    assert tool["name"] == "Guide Tool"
    assert "open" in tool
    opened = []
    monkeypatch.setitem(tool, "open", opened.append)
    path = guides.PRODUCT.create(str(tmp_path), "L_arm")
    logic.open_utility(guides.PRODUCT, path)
    assert opened == [path]


def test_republish_finds_the_guide_groups_by_name(new_scene, tmp_path):
    group = _arm()
    path, _ = _publish(tmp_path, group)
    cmds.xform(core_guides.guides(group)["up"], worldSpace=True, translation=(4, 0, 7))
    cmds.select(clear=True)
    guides.PRODUCT.republish(path)
    assert data.read(path, "guides")["up_guide"] == [4.0, 0.0, 7.0]
    assert len(versions.list_versions(path)) == 2


def test_info_describes_the_chain(new_scene, tmp_path):
    path, _ = _publish(tmp_path, _arm())
    assert guides.PRODUCT.describe(data.read(path, "guides")) == ["arm: 3 guides, aim x, up y"]


# -- Mirror ---------------------------------------------------------------------

from maya.api import OpenMaya as om  # noqa: E402


def _mirror_action(path):
    return next((a for a in guides.PRODUCT.actions(path) if a.label == "Mirror"), None)


def _left_arm(aim="x", up="y"):
    group = core_guides.build_guides("L_arm", 2, start=(2, 10, 0), end=(10, 9, -1), aim=aim, up=up)
    found = core_guides.guides(group)
    for node, xyz in zip(found["chain"][1:3] + [found["up"]], [(4.5, 10.5, -0.5), (7, 9, -1.5), (6, 10, -6)]):
        cmds.xform(node, worldSpace=True, translation=xyz)
    return group


def _rows(node):
    m = om.MMatrix(cmds.xform(node, query=True, worldSpace=True, matrix=True))
    return [om.MVector(m[r * 4], m[r * 4 + 1], m[r * 4 + 2]).normalize() for r in range(4)]


def _flip_x(v):
    return om.MVector(-v.x, v.y, v.z)


def _close(a, b, tol=1e-4):
    return (a - b).length() < tol


def test_mirror_writes_the_other_sides_item(new_scene, tmp_path):
    path, _ = _publish(tmp_path, _left_arm(), name="L_arm")
    message = _mirror_action(path).fn()

    mirrored = str(tmp_path / "R_arm.guide")
    assert "R_arm.guide" in message
    chain = data.read(mirrored, "guides")
    assert chain["name"] == "R_arm" and (chain["aim"], chain["up"]) == ("-x", "-y")
    assert chain["guides"][1] == [-4.5, 10.5, -0.5]
    assert chain["up_guide"] == [-6.0, 10.0, -6.0]
    assert versions.current_version(mirrored).number == 1


def test_mirror_places_the_new_item_right_after_the_source(new_scene, tmp_path):
    first = guides.PRODUCT.create(str(tmp_path), "a_first")
    path, _ = _publish(tmp_path, _left_arm(), name="L_arm")
    last = guides.PRODUCT.create(str(tmp_path), "z_last")
    logic.append_to_order(str(tmp_path), [os.path.basename(p) for p in (first, path, last)])
    _mirror_action(path).fn()
    assert logic.item_names(str(tmp_path)) == ["a_first.guide", "L_arm.guide", "R_arm.guide", "z_last.guide"]


def test_mirror_again_updates_the_other_item_as_a_new_version(new_scene, tmp_path):
    group = _left_arm()
    path, _ = _publish(tmp_path, group, name="L_arm")
    _mirror_action(path).fn()
    cmds.xform(core_guides.guides(group)["up"], worldSpace=True, translation=(6, 14, -6))
    versions.publish_action(path).fn()
    _mirror_action(path).fn()

    mirrored = str(tmp_path / "R_arm.guide")
    assert data.read(mirrored, "guides")["up_guide"] == [-6.0, 14.0, -6.0]
    assert [v.number for v in versions.list_versions(mirrored)] == [2, 1]


def test_mirror_of_an_unsided_item_adds_mirrored_and_goes_back(new_scene, tmp_path):
    core_guides.build_guides("tail", 1, start=(1, 5, -2), end=(3, 2, -8))
    path, _ = _publish(tmp_path, "tail_guides_grp", name="tail")
    _mirror_action(path).fn()
    assert data.read(str(tmp_path / "tail_mirrored.guide"), "guides")["name"] == "tail_mirrored"
    _mirror_action(str(tmp_path / "tail_mirrored.guide")).fn()
    assert sorted(n for n in os.listdir(tmp_path) if not n.startswith(".")) == ["tail.guide", "tail_mirrored.guide"]


def test_mirror_refuses_to_overwrite_another_kind_of_item(new_scene, tmp_path):
    path, _ = _publish(tmp_path, _left_arm(), name="L_arm")
    with open(tmp_path / "R_arm.guide", "w") as f:
        f.write('{"kaiju": "joints", "format": 1, "data": {}}')
    action = _mirror_action(path)
    assert any("R_arm.guide" in p for p in action.problems())
    with pytest.raises(ValueError, match="R_arm.guide"):
        action.fn()


def test_an_empty_item_has_no_mirror(tmp_path):
    assert _mirror_action(guides.PRODUCT.create(str(tmp_path), "L_arm")) is None


def test_mirror_keeps_republish(new_scene, tmp_path):
    path, _ = _publish(tmp_path, _left_arm(), name="L_arm")
    labels = [a.label for a in guides.PRODUCT.actions(path)]
    assert {"Republish", "Select Objects", "Mirror"} <= set(labels)


@pytest.mark.parametrize("aim, up", [("x", "y"), ("-x", "z"), ("y", "-z")])
def test_running_the_mirrored_item_behavior_mirrors_the_joints(new_scene, tmp_path, aim, up):
    # Maya's Behavior mirror: each axis of the copy is the source's axis
    # flipped across X and then reversed, so the same rotation values move
    # the two sides in mirror image.
    left = _left_arm(aim, up)
    path, _ = _publish(tmp_path, left, name="L_arm")
    _mirror_action(path).fn()
    guides.PRODUCT.run(str(tmp_path / "R_arm.guide"))
    for a, b in zip(core_guides.joints(left), core_guides.joints("R_arm_guides_grp")):
        ra, rb = _rows(a), _rows(b)
        for axis in range(3):
            assert _close(rb[axis], -_flip_x(ra[axis])), (cmds.ls(b)[0], "xyz"[axis])
        assert _close(rb[3], _flip_x(ra[3]))


def test_mirrored_joints_match_maya_behavior_mirror(new_scene, tmp_path):
    left = _left_arm()
    path, _ = _publish(tmp_path, left, name="L_arm")
    _mirror_action(path).fn()
    guides.PRODUCT.run(str(tmp_path / "R_arm.guide"))
    top = core_guides.delete_guides(left)[0]
    core_guides.delete_guides("R_arm_guides_grp")
    cmds.mirrorJoint(top, mirrorYZ=True, mirrorBehavior=True, searchReplace=("L_", "M_"))
    for i in range(1, 5):
        assert all(_close(a, b) for a, b in zip(_rows(f"R_arm_{i:02d}_jnt"), _rows(f"M_arm_{i:02d}_jnt"))), i
