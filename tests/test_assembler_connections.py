import os

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import data, logic, products, runlog, versions
from kaiju_suite.tools.assembler.products import connections

MATRIX = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 1.0, 2.0, 3.0, 1.0]


def _ends():
    """The scene nodes the network links: a control and a joint."""
    cmds.createNode("transform", name="arm_ctrl")
    cmds.select(clear=True)
    cmds.joint(name="arm_jnt")
    cmds.select(clear=True)
    return "arm_ctrl", "arm_jnt"


def _network():
    """arm_ctrl drives arm_jnt through a multiplyDivide, a plusMinusAverage
    and a multMatrix, plus a direct connection and one through a unit
    conversion (rotate into a plain float)."""
    ctrl, jnt = _ends()
    md = cmds.createNode("multiplyDivide", name="arm_md")
    cmds.setAttr(f"{md}.input2X", 2)
    cmds.setAttr(f"{md}.operation", 1)
    cmds.connectAttr(f"{ctrl}.translateX", f"{md}.input1X")
    cmds.connectAttr(f"{ctrl}.rotateY", f"{md}.input1Y")  # inserts a unitConversion
    cmds.connectAttr(f"{md}.outputX", f"{jnt}.translateY")
    cmds.connectAttr(f"{md}.outputY", f"{jnt}.scaleX")

    pma = cmds.createNode("plusMinusAverage", name="arm_pma")
    cmds.connectAttr(f"{ctrl}.translateY", f"{pma}.input1D[0]")
    cmds.setAttr(f"{pma}.input1D[1]", 5)
    cmds.connectAttr(f"{pma}.output1D", f"{jnt}.translateZ")

    mm = cmds.createNode("multMatrix", name="arm_mm")
    cmds.setAttr(f"{mm}.matrixIn[0]", *MATRIX, type="matrix")
    cmds.connectAttr(f"{ctrl}.worldMatrix[0]", f"{mm}.matrixIn[1]")
    cmds.connectAttr(f"{mm}.matrixSum", f"{jnt}.offsetParentMatrix")

    cmds.connectAttr(f"{ctrl}.rotateX", f"{jnt}.rotateX")
    return ctrl, jnt


def _publish(tmp_path, *selection, name="links"):
    path = connections.PRODUCT.create(str(tmp_path), name)
    cmds.select(selection, noExpand=True)
    message = versions.publish_action(path).fn()
    return path, message


def _incoming(node):
    """``(source plug, destination plug)`` pairs into ``node``, through unit conversions."""
    pairs = cmds.listConnections(node, source=True, destination=False, plugs=True, connections=True,
                                 skipConversionNodes=True) or []
    return sorted(zip(pairs[1::2], pairs[::2]))


def _check_network():
    cmds.setAttr("arm_ctrl.translateX", 3)
    cmds.setAttr("arm_ctrl.translateY", 1)
    cmds.setAttr("arm_ctrl.rotateX", 30)
    assert cmds.getAttr("arm_jnt.translateY") == pytest.approx(6)
    assert cmds.getAttr("arm_jnt.translateZ") == pytest.approx(6)
    assert cmds.getAttr("arm_jnt.rotateX") == pytest.approx(30)
    assert cmds.getAttr("arm_mm.matrixIn[0]") == pytest.approx(MATRIX)
    assert ("arm_ctrl.rotateY", "arm_md.input1Y") in _incoming("arm_md")
    assert cmds.ls(type="unitConversion")


# -- product ----------------------------------------------------------------


def test_connections_is_discovered_and_owns_conn(tmp_path):
    assert connections.PRODUCT in products.discover()
    assert connections.PRODUCT.name == "Connections"
    assert connections.PRODUCT.kind == "connections"
    assert connections.PRODUCT.extensions == (".conn",)
    assert connections.PRODUCT.runnable and connections.PRODUCT.versioned
    assert connections.PRODUCT.menu_slot is not None
    path = connections.PRODUCT.creators[0].fn(str(tmp_path), "links", None)
    assert path == str(tmp_path / "links.conn") and os.path.getsize(path) == 0
    assert products.product_for(path) is connections.PRODUCT


# -- publish ----------------------------------------------------------------


def test_publish_saves_the_network_between_the_selected_nodes(new_scene, tmp_path):
    ctrl, jnt = _network()
    path, message = _publish(tmp_path, ctrl, jnt)
    assert message == "Published Connections links.conn v001"

    payload = data.read(path, "connections")
    nodes = {n["name"]: n for n in payload["nodes"]}
    assert sorted(nodes) == ["arm_md", "arm_mm", "arm_pma"]  # no unitConversion
    assert nodes["arm_md"]["type"] == "multiplyDivide"
    # Only values that aren't the default, and none that are connected.
    assert nodes["arm_md"]["attrs"] == {"input2X": 2.0}
    assert nodes["arm_pma"]["attrs"] == {"input1D[1]": 5.0}
    assert nodes["arm_mm"]["attrs"]["matrixIn[0]"] == pytest.approx(MATRIX)
    assert sorted(map(tuple, payload["connections"])) == sorted([
        ("arm_ctrl.translateX", "arm_md.input1X"),
        ("arm_ctrl.rotateY", "arm_md.input1Y"),
        ("arm_md.outputX", "arm_jnt.translateY"),
        ("arm_md.outputY", "arm_jnt.scaleX"),
        ("arm_ctrl.translateY", "arm_pma.input1D[0]"),
        ("arm_pma.output1D", "arm_jnt.translateZ"),
        ("arm_ctrl.worldMatrix[0]", "arm_mm.matrixIn[1]"),
        ("arm_mm.matrixSum", "arm_jnt.offsetParentMatrix"),
        ("arm_ctrl.rotateX", "arm_jnt.rotateX"),
    ])


def test_publish_leaves_out_nodes_not_between_selected_nodes(new_scene, tmp_path):
    ctrl, jnt = _network()
    dangling = cmds.createNode("reverse", name="loose_rev")
    cmds.connectAttr(f"{ctrl}.translateZ", f"{dangling}.inputX")  # leads to nothing selected
    other = cmds.createNode("transform", name="other_grp")
    cmds.connectAttr(f"{ctrl}.translateZ", f"{other}.translateZ")
    path, _ = _publish(tmp_path, ctrl, jnt)
    payload = data.read(path, "connections")
    assert "loose_rev" not in [n["name"] for n in payload["nodes"]]
    assert not [c for c in payload["connections"] if "other_grp" in c[1] or "loose_rev" in c[1]]


def test_selected_utility_nodes_are_saved_too(new_scene, tmp_path):
    ctrl, _jnt = _ends()
    cond = cmds.createNode("condition", name="arm_cond")
    cmds.setAttr(f"{cond}.operation", 2)
    cmds.setAttr(f"{cond}.colorIfTrueR", 0.25)
    cmds.connectAttr(f"{ctrl}.translateX", f"{cond}.firstTerm")
    path, _ = _publish(tmp_path, ctrl, cond)
    payload = data.read(path, "connections")
    assert payload["nodes"] == [{"name": "arm_cond", "type": "condition",
                                 "attrs": {"colorIfTrueR": 0.25, "operation": 2}}]
    assert payload["connections"] == [["arm_ctrl.translateX", "arm_cond.firstTerm"]]


# -- run --------------------------------------------------------------------


def test_round_trip_rebuilds_the_network(new_scene, tmp_path):
    ctrl, jnt = _network()
    path, _ = _publish(tmp_path, ctrl, jnt)

    cmds.file(new=True, force=True)
    _ends()
    with runlog.capture() as run:
        assert logic.run_steps([path])
    assert not run.warnings
    assert cmds.nodeType("arm_md") == "multiplyDivide"
    assert cmds.getAttr("arm_md.input2X") == 2
    assert cmds.getAttr("arm_pma.input1D[1]") == 5
    _check_network()


def test_run_message_names_what_it_made(new_scene, tmp_path):
    ctrl, jnt = _network()
    path, _ = _publish(tmp_path, ctrl, jnt)
    cmds.file(new=True, force=True)
    _ends()
    assert connections.PRODUCT.run(path) == "Created 3 utility nodes and made 9 connections"


def test_rerunning_replaces_same_named_nodes(new_scene, tmp_path):
    ctrl, jnt = _network()
    path, _ = _publish(tmp_path, ctrl, jnt)
    cmds.setAttr("arm_md.input2X", 7)
    connections.PRODUCT.run(path)
    connections.PRODUCT.run(path)
    assert cmds.ls(type="multiplyDivide") == ["arm_md"]
    assert cmds.ls(type="plusMinusAverage") == ["arm_pma"]
    assert cmds.getAttr("arm_md.input2X") == 2
    _check_network()


def test_missing_scene_node_is_skipped_with_a_warning(new_scene, tmp_path):
    ctrl, jnt = _network()
    path, _ = _publish(tmp_path, ctrl, jnt)

    cmds.file(new=True, force=True)
    cmds.createNode("transform", name="arm_ctrl")
    with runlog.capture() as run:
        message = connections.PRODUCT.run(path)
    assert run.warnings == ["Skipped missing nodes: arm_jnt"]
    assert sorted(cmds.ls(type=["multiplyDivide", "plusMinusAverage", "multMatrix"])) == ["arm_md", "arm_mm", "arm_pma"]
    assert ("arm_ctrl.translateX", "arm_md.input1X") in _incoming("arm_md")
    assert message == "Created 3 utility nodes and made 4 connections"


def test_missing_attribute_is_skipped_with_a_warning(new_scene, tmp_path):
    ctrl, jnt = _ends()
    cmds.addAttr(ctrl, longName="curl", attributeType="double", keyable=True)
    cmds.connectAttr(f"{ctrl}.curl", f"{jnt}.rotateZ")
    cmds.connectAttr(f"{ctrl}.rotateX", f"{jnt}.rotateX")
    path, _ = _publish(tmp_path, ctrl, jnt)

    cmds.file(new=True, force=True)
    _ends()
    with runlog.capture() as run:
        connections.PRODUCT.run(path)
    assert run.warnings == ["Skipped connections to missing attributes: arm_ctrl.curl -> arm_jnt.rotateZ"]
    assert cmds.isConnected("arm_ctrl.rotateX", "arm_jnt.rotateX")


def test_ambiguous_name_raises_and_changes_nothing(new_scene, tmp_path):
    ctrl, jnt = _network()
    path, _ = _publish(tmp_path, ctrl, jnt)

    cmds.file(new=True, force=True)
    _ends()
    twin = cmds.createNode("transform", name="twin", parent=cmds.createNode("transform", name="other_grp"))
    cmds.rename(twin, "arm_ctrl")
    assert len(cmds.ls("arm_ctrl")) == 2
    with pytest.raises(RuntimeError) as info:
        connections.PRODUCT.run(path)
    assert "arm_ctrl" in str(info.value)
    assert not cmds.ls(type=["multiplyDivide", "plusMinusAverage", "multMatrix"])
    assert not cmds.listConnections("arm_jnt", source=True, destination=False)


def test_name_taken_by_another_type_raises_and_changes_nothing(new_scene, tmp_path):
    ctrl, jnt = _network()
    path, _ = _publish(tmp_path, ctrl, jnt)

    cmds.file(new=True, force=True)
    _ends()
    cmds.createNode("transform", name="arm_pma")
    with pytest.raises(RuntimeError) as info:
        connections.PRODUCT.run(path)
    assert "arm_pma" in str(info.value)
    assert not cmds.ls(type=["multiplyDivide", "plusMinusAverage", "multMatrix"])


def test_empty_file_is_skipped(new_scene, tmp_path):
    path = connections.PRODUCT.create(str(tmp_path), "links")
    assert logic.run_steps([path]) == [path]
    assert not cmds.ls(type="multiplyDivide")


def test_one_undo_reverts_a_run(new_scene, tmp_path):
    ctrl, jnt = _network()
    path, _ = _publish(tmp_path, ctrl, jnt)
    cmds.file(new=True, force=True)
    _ends()
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    connections.PRODUCT.run(path)
    assert cmds.objExists("arm_md")
    cmds.undo()
    assert not cmds.ls(type=["multiplyDivide", "plusMinusAverage", "multMatrix"])
    assert not cmds.listConnections("arm_jnt", source=True, destination=False)
    assert not cmds.listConnections("arm_ctrl", source=False, destination=True)


def test_one_undo_reverts_a_rerun(new_scene, tmp_path):
    ctrl, jnt = _network()
    path, _ = _publish(tmp_path, ctrl, jnt)
    cmds.setAttr("arm_md.input2X", 7)
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    connections.PRODUCT.run(path)
    assert cmds.getAttr("arm_md.input2X") == 2
    cmds.undo()
    assert cmds.ls(type="multiplyDivide") == ["arm_md"]
    assert cmds.getAttr("arm_md.input2X") == 7
    assert cmds.isConnected("arm_md.outputX", "arm_jnt.translateY")


# -- publish checks and versions --------------------------------------------


def test_publish_problems(new_scene, tmp_path):
    path = connections.PRODUCT.create(str(tmp_path), "links")
    cmds.select(clear=True)
    (problem,) = versions.publish_problems(path)
    assert "Nothing selected" in problem

    ctrl, jnt = _ends()
    cmds.select(ctrl, jnt)
    (problem,) = versions.publish_problems(path)
    assert "connection" in problem.lower()

    cmds.select(cmds.createNode("animCurveTL", name="some_curve"))
    (problem,) = versions.publish_problems(path)
    assert "some_curve" in problem

    cmds.connectAttr(f"{ctrl}.rotateX", f"{jnt}.rotateX")
    cmds.select(ctrl, jnt)
    assert versions.publish_problems(path) == []


def test_publish_with_nothing_to_save_raises_and_writes_nothing(new_scene, tmp_path):
    path = connections.PRODUCT.create(str(tmp_path), "links")
    cmds.select(_ends())
    with pytest.raises(RuntimeError):
        versions.publish_action(path).fn()
    assert os.path.getsize(path) == 0


def test_republishing_adds_a_version_only_on_change(new_scene, tmp_path):
    ctrl, jnt = _network()
    path, message = _publish(tmp_path, ctrl, jnt)
    assert message.endswith("v001")
    cmds.select(ctrl, jnt)
    assert versions.publish_action(path).fn().endswith("v001")
    cmds.setAttr("arm_md.input2Z", 4)
    assert versions.publish_action(path).fn().endswith("v002")


def test_panel_describes_the_file(new_scene, tmp_path):
    ctrl, jnt = _network()
    path, _ = _publish(tmp_path, ctrl, jnt)
    assert connections.PRODUCT.panel(path).info == [
        "3 utility nodes: arm_md, arm_mm, arm_pma",
        "9 connections",
        "Scene nodes: arm_ctrl, arm_jnt",
    ]
