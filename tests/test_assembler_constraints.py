import os

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import data, logic, products, runlog, versions
from kaiju_suite.tools.assembler.products import constraints

ALL = ["aim_drv_ac", "leg_pv", "orient_drv_oc", "parent_drv_pc", "point_drv_pc", "scale_drv_sc"]
DRIVEN = ["parent_drv", "point_drv", "orient_drv", "scale_drv", "aim_drv", "leg_ik"]


def _locator(name, translate=(0, 0, 0), rotate=(0, 0, 0), scale=(1, 1, 1)):
    node = cmds.spaceLocator(name=name)[0]
    cmds.xform(node, translation=translate, rotation=rotate, scale=scale, worldSpace=True)
    return node


def _transform(name, translate=(0, 0, 0), rotate=(0, 0, 0)):
    node = cmds.createNode("transform", name=name, skipSelect=True)
    cmds.xform(node, translation=translate, rotation=rotate, worldSpace=True)
    return node


def _nodes():
    """Targets, constrained transforms and an IK leg, with no constraints."""
    _locator("world_tgt", (2, 3, 4), (10, 20, 30))
    _locator("hand_tgt", (-1, 5, 2), (0, 45, 0), (2, 2, 2))
    _locator("up_tgt", (0, 10, 0))
    _locator("pole_tgt", (1, 1, 5))
    _transform("parent_drv", (3, 0, 0), (0, 0, 15))
    _transform("point_drv", (0, 1, 0))
    _transform("orient_drv", (0, 0, 1), (30, 0, 0))
    _transform("scale_drv")
    _transform("aim_drv", (-2, 0, 0))
    cmds.select(clear=True)
    cmds.joint(name="leg_01", position=(0, 0, 0))
    cmds.joint(name="leg_02", position=(0, -2, 1))
    cmds.joint(name="leg_03", position=(0, -4, 0))
    cmds.ikHandle(name="leg_ik", startJoint="leg_01", endEffector="leg_03")
    cmds.select(clear=True)


def _constrain():
    """One of each constraint type, with non-default settings."""
    pc = cmds.parentConstraint(
        "world_tgt", "hand_tgt", "parent_drv", maintainOffset=True, skipRotate=["z"], name="parent_drv_pc"
    )[0]
    cmds.setAttr(f"{pc}.hand_tgtW1", 0.5)
    cmds.setAttr(f"{pc}.interpType", 2)
    cmds.pointConstraint("hand_tgt", "point_drv", offset=(1, 2, 3), skip=["y"], name="point_drv_pc")
    oc = cmds.orientConstraint("world_tgt", "hand_tgt", "orient_drv", maintainOffset=True, name="orient_drv_oc")[0]
    cmds.setAttr(f"{oc}.world_tgtW0", 0.25)
    cmds.setAttr(f"{oc}.interpType", 0)
    cmds.scaleConstraint("hand_tgt", "scale_drv", offset=(1, 0.5, 2), name="scale_drv_sc")
    cmds.aimConstraint(
        "world_tgt", "aim_drv", aimVector=(0, 1, 0), upVector=(1, 0, 0),
        worldUpType="objectrotation", worldUpObject="up_tgt", worldUpVector=(0, 0, 1),
        offset=(0, 0, 15), name="aim_drv_ac",
    )
    cmds.poleVectorConstraint("pole_tgt", "leg_ik", name="leg_pv")
    cmds.select(clear=True)


def _constraints():
    return sorted(cmds.ls(type="constraint"))


def _vec(value):
    """A rounded attribute value: a number, or a list for a compound."""
    if isinstance(value, list):
        return [round(v, 4) + 0.0 for v in value[0]]
    return round(value, 4) + 0.0


def _state(node):
    """What a constraint does, for comparing two scenes."""
    kind = cmds.nodeType(node)
    command = getattr(cmds, kind)
    aliases = command(node, query=True, weightAliasList=True)
    state = {
        "type": kind,
        "targets": command(node, query=True, targetList=True),
        "weights": [_vec(cmds.getAttr(f"{node}.{a}")) for a in aliases],
        "outputs": sorted(cmds.listConnections(node, source=False, destination=True, plugs=True) or []),
    }
    for attr in ("offset", "interpType", "aimVector", "upVector", "worldUpType", "worldUpVector"):
        if cmds.attributeQuery(attr, node=node, exists=True):
            state[attr] = _vec(cmds.getAttr(f"{node}.{attr}"))
    if kind == "aimConstraint":
        state["worldUpObject"] = cmds.listConnections(f"{node}.worldUpMatrix", source=True, destination=False)
    if kind == "parentConstraint":
        for i in range(len(aliases)):
            for attr in ("targetOffsetTranslate", "targetOffsetRotate"):
                state[f"{attr}{i}"] = _vec(cmds.getAttr(f"{node}.target[{i}].{attr}"))
    # Outputs to other constraints' inputs and the like aren't the point.
    state["outputs"] = [p for p in state["outputs"] if not p.startswith(node)]
    return state


def _states():
    return {node: _state(node) for node in _constraints()}


def _matrices():
    nodes = DRIVEN[:-1] + ["leg_01", "leg_02", "leg_03"]
    return {n: [round(v, 3) + 0.0 for v in cmds.xform(n, query=True, matrix=True, worldSpace=True)] for n in nodes}


def _publish(tmp_path, *selection, name="cnst"):
    path = constraints.PRODUCT.create(str(tmp_path), name)
    cmds.select(selection)
    message = versions.publish_action(path).fn()
    return path, message


def _records(path):
    return {r["name"]: r for r in data.read(path, "constraints")["constraints"]}


# -- product ----------------------------------------------------------------


def test_constraints_is_discovered_and_owns_cnst(tmp_path):
    assert constraints.PRODUCT in products.discover()
    assert constraints.PRODUCT.name == "Constraints"
    assert constraints.PRODUCT.kind == "constraints"
    assert constraints.PRODUCT.extensions == (".cnst",)
    assert constraints.PRODUCT.runnable and constraints.PRODUCT.versioned
    path = constraints.PRODUCT.creators[0].fn(str(tmp_path), "cnst", None)
    assert path == str(tmp_path / "cnst.cnst") and os.path.getsize(path) == 0
    assert products.product_for(path) is constraints.PRODUCT


# -- publish ----------------------------------------------------------------


def test_publish_saves_every_constraint_on_the_selected_nodes(new_scene, tmp_path):
    _nodes()
    _constrain()
    path, message = _publish(tmp_path, *DRIVEN)
    assert message == "Published Constraints cnst.cnst v001"
    records = _records(path)
    assert sorted(records) == ALL
    assert {r["name"]: (r["type"], r["driven"]) for r in records.values()} == {
        "parent_drv_pc": ("parentConstraint", "parent_drv"),
        "point_drv_pc": ("pointConstraint", "point_drv"),
        "orient_drv_oc": ("orientConstraint", "orient_drv"),
        "scale_drv_sc": ("scaleConstraint", "scale_drv"),
        "aim_drv_ac": ("aimConstraint", "aim_drv"),
        "leg_pv": ("poleVectorConstraint", "leg_ik"),
    }


def test_publish_saves_targets_weights_offsets_and_settings(new_scene, tmp_path):
    _nodes()
    _constrain()
    path, _ = _publish(tmp_path, "parent_drv", "point_drv", "aim_drv")
    records = _records(path)

    parent = records["parent_drv_pc"]
    assert [t["name"] for t in parent["targets"]] == ["world_tgt", "hand_tgt"]
    assert [t["weight"] for t in parent["targets"]] == [1.0, 0.5]
    assert parent["interpType"] == 2
    assert parent["skip"] == {"translate": [], "rotate": ["z"]}
    offset = cmds.getAttr("parent_drv_pc.target[1].targetOffsetTranslate")[0]
    assert parent["targets"][1]["targetOffsetTranslate"] == pytest.approx(list(offset), abs=1e-5)

    point = records["point_drv_pc"]
    assert point["offset"] == [1, 2, 3]
    assert point["skip"] == {"translate": ["y"]}

    aim = records["aim_drv_ac"]
    assert aim["aimVector"] == [0, 1, 0]
    assert aim["upVector"] == [1, 0, 0]
    assert aim["worldUpType"] == "objectrotation"
    assert aim["worldUpVector"] == [0, 0, 1]
    assert aim["worldUpObject"] == "up_tgt"


def test_publish_a_selected_constraint_node(new_scene, tmp_path):
    _nodes()
    _constrain()
    path, _ = _publish(tmp_path, "point_drv_pc")
    assert sorted(_records(path)) == ["point_drv_pc"]


def test_publish_leaves_out_constraints_the_node_is_a_target_of(new_scene, tmp_path):
    _nodes()
    _constrain()
    cmds.pointConstraint("hand_tgt", "world_tgt", name="world_tgt_pc")
    path, _ = _publish(tmp_path, "world_tgt")
    assert sorted(_records(path)) == ["world_tgt_pc"]


def test_publish_with_two_constraints_of_one_name_raises(new_scene, tmp_path):
    _nodes()
    for group in ("a_grp", "b_grp"):
        driven = cmds.createNode("transform", name="drv", parent=cmds.createNode("transform", name=group))
        cmds.pointConstraint("hand_tgt", driven, name="drv_pc")
    path = constraints.PRODUCT.create(str(tmp_path), "cnst")
    cmds.select("a_grp|drv", "b_grp|drv")
    with pytest.raises(RuntimeError) as info:
        versions.publish_action(path).fn()
    assert "drv_pc" in str(info.value)
    assert os.path.getsize(path) == 0


# -- run --------------------------------------------------------------------


def test_round_trip_gives_the_same_constraints(new_scene, tmp_path):
    _nodes()
    _constrain()
    states, matrices = _states(), _matrices()
    path, _ = _publish(tmp_path, *DRIVEN)

    cmds.file(new=True, force=True)
    _nodes()
    logic.run_steps([path])

    assert _constraints() == ALL
    assert _states() == states
    assert _matrices() == matrices


def test_run_message_names_the_constraints(new_scene, tmp_path):
    _nodes()
    _constrain()
    path, _ = _publish(tmp_path, "point_drv", "aim_drv")
    cmds.file(new=True, force=True)
    _nodes()
    message = constraints.PRODUCT.run(path)
    assert message == "Created 2 constraints: point_drv_pc, aim_drv_ac"


def test_rerunning_replaces_the_same_named_constraint(new_scene, tmp_path):
    _nodes()
    _constrain()
    states = _states()
    path, _ = _publish(tmp_path, *DRIVEN)
    cmds.setAttr("parent_drv_pc.hand_tgtW1", 1.0)
    cmds.setAttr("point_drv_pc.offset", 0, 0, 0)
    cmds.aimConstraint("aim_drv_ac", edit=True, worldUpType="scene")

    constraints.PRODUCT.run(path)
    constraints.PRODUCT.run(path)
    assert _constraints() == ALL
    assert _states() == states


def test_other_constraints_are_left_alone(new_scene, tmp_path):
    _nodes()
    _constrain()
    path, _ = _publish(tmp_path, "point_drv")
    cmds.pointConstraint("hand_tgt", "scale_drv", name="keep_pc")
    constraints.PRODUCT.run(path)
    assert "keep_pc" in _constraints()
    assert cmds.pointConstraint("keep_pc", query=True, targetList=True) == ["hand_tgt"]


def test_other_constraint_of_the_same_type_raises_and_changes_nothing(new_scene, tmp_path):
    # Maya would add the targets to it instead of making a new constraint.
    _nodes()
    _constrain()
    path, _ = _publish(tmp_path, "point_drv")
    cmds.file(new=True, force=True)
    _nodes()
    cmds.pointConstraint("world_tgt", "point_drv", name="other_pc")
    with pytest.raises(RuntimeError) as info:
        constraints.PRODUCT.run(path)
    assert "point_drv" in str(info.value) and "other_pc" in str(info.value)
    assert _constraints() == ["other_pc"]
    assert cmds.pointConstraint("other_pc", query=True, targetList=True) == ["world_tgt"]


def test_name_taken_by_another_node_raises_and_changes_nothing(new_scene, tmp_path):
    _nodes()
    _constrain()
    path, _ = _publish(tmp_path, "point_drv", "aim_drv")
    cmds.file(new=True, force=True)
    _nodes()
    cmds.createNode("transform", name="aim_drv_ac")
    with pytest.raises(RuntimeError) as info:
        constraints.PRODUCT.run(path)
    assert "aim_drv_ac" in str(info.value)
    assert _constraints() == []


def test_same_name_on_another_node_raises_and_changes_nothing(new_scene, tmp_path):
    _nodes()
    _constrain()
    path, _ = _publish(tmp_path, "point_drv")
    cmds.file(new=True, force=True)
    _nodes()
    cmds.pointConstraint("hand_tgt", "scale_drv", name="point_drv_pc")
    with pytest.raises(RuntimeError) as info:
        constraints.PRODUCT.run(path)
    assert "point_drv_pc" in str(info.value)
    assert cmds.listRelatives("point_drv_pc", parent=True) == ["scale_drv"]


def test_missing_nodes_are_skipped_with_a_warning(new_scene, tmp_path):
    _nodes()
    _constrain()
    path, _ = _publish(tmp_path, *DRIVEN)

    cmds.file(new=True, force=True)
    _nodes()
    cmds.delete("aim_drv", "pole_tgt")
    with runlog.capture() as run:
        constraints.PRODUCT.run(path)
    assert run.warnings == ["Skipped constraints with missing nodes: aim_drv_ac (aim_drv), leg_pv (pole_tgt)"]
    assert _constraints() == ["orient_drv_oc", "parent_drv_pc", "point_drv_pc", "scale_drv_sc"]


def test_missing_world_up_object_is_skipped(new_scene, tmp_path):
    _nodes()
    _constrain()
    path, _ = _publish(tmp_path, "aim_drv")
    cmds.file(new=True, force=True)
    _nodes()
    cmds.delete("up_tgt")
    with runlog.capture() as run:
        constraints.PRODUCT.run(path)
    assert run.warnings == ["Skipped constraints with missing nodes: aim_drv_ac (up_tgt)"]
    assert _constraints() == []


def test_all_missing_is_a_warning_not_an_error(new_scene, tmp_path):
    _nodes()
    _constrain()
    path, _ = _publish(tmp_path, "point_drv")
    cmds.file(new=True, force=True)
    with runlog.capture() as run:
        message = constraints.PRODUCT.run(path)
    assert len(run.warnings) == 1
    assert message == "Created no constraints"
    assert _constraints() == []


def test_ambiguous_names_raise_before_changing_anything(new_scene, tmp_path):
    _nodes()
    _constrain()
    states = _states()
    path, _ = _publish(tmp_path, *DRIVEN)
    cmds.setAttr("point_drv_pc.offset", 0, 0, 0)
    cmds.createNode("transform", name="hand_tgt", parent=cmds.createNode("transform", name="grp"))
    with pytest.raises(RuntimeError) as info:
        constraints.PRODUCT.run(path)
    assert "hand_tgt" in str(info.value)
    assert _constraints() == ALL
    assert cmds.getAttr("point_drv_pc.offset") == [(0, 0, 0)]
    assert _state("aim_drv_ac") == states["aim_drv_ac"]


def test_empty_file_is_skipped(new_scene, tmp_path):
    path = constraints.PRODUCT.create(str(tmp_path), "cnst")
    _nodes()
    assert logic.run_steps([path]) == [path]
    assert _constraints() == []


def test_one_undo_reverts_a_run(new_scene, tmp_path):
    _nodes()
    _constrain()
    path, _ = _publish(tmp_path, *DRIVEN)
    cmds.setAttr("point_drv_pc.offset", 0, 0, 0)
    before = _states()
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    constraints.PRODUCT.run(path)
    assert cmds.getAttr("point_drv_pc.offset")[0] == (1, 2, 3)
    cmds.undo()
    assert _constraints() == ALL
    assert _states() == before


def test_one_undo_reverts_a_fresh_run(new_scene, tmp_path):
    _nodes()
    _constrain()
    path, _ = _publish(tmp_path, *DRIVEN)
    cmds.file(new=True, force=True)
    _nodes()
    matrices = _matrices()
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    constraints.PRODUCT.run(path)
    assert _constraints() == ALL
    cmds.undo()
    assert _constraints() == []
    assert _matrices() == matrices


# -- publish checks and versions --------------------------------------------


def test_publish_problems(new_scene, tmp_path):
    path = constraints.PRODUCT.create(str(tmp_path), "cnst")
    cmds.select(clear=True)
    (problem,) = versions.publish_problems(path)
    assert "Nothing selected" in problem

    _nodes()
    cmds.select("point_drv", "aim_drv")
    (problem,) = versions.publish_problems(path)
    assert "point_drv" in problem and "aim_drv" in problem

    cmds.pointConstraint("hand_tgt", "point_drv", name="point_drv_pc")
    cmds.select("point_drv", "aim_drv")
    (problem,) = versions.publish_problems(path)
    assert "aim_drv" in problem and "point_drv" not in problem

    cmds.select("point_drv")
    assert versions.publish_problems(path) == []
    cmds.select("point_drv_pc")
    assert versions.publish_problems(path) == []


def test_publish_without_constraints_raises_and_writes_nothing(new_scene, tmp_path):
    path = constraints.PRODUCT.create(str(tmp_path), "cnst")
    _nodes()
    cmds.select("point_drv")
    with pytest.raises(RuntimeError):
        versions.publish_action(path).fn()
    assert os.path.getsize(path) == 0


def test_republishing_adds_a_version_only_on_change(new_scene, tmp_path):
    _nodes()
    _constrain()
    path, message = _publish(tmp_path, *DRIVEN)
    assert message.endswith("v001")

    cmds.select(DRIVEN)
    assert versions.publish_action(path).fn().endswith("v001")
    assert [v.number for v in versions.list_versions(path)] == [1]

    cmds.setAttr("point_drv_pc.offset", 0, 0, 0)
    assert versions.publish_action(path).fn().endswith("v002")


def test_panel_describes_the_constraints(new_scene, tmp_path):
    _nodes()
    _constrain()
    path, _ = _publish(tmp_path, "parent_drv", "point_drv", "leg_ik")
    assert constraints.PRODUCT.panel(path).info == [
        "3 constraints: 1 parent, 1 point, 1 pole vector",
        "Constrained: parent_drv, point_drv, leg_ik",
    ]
