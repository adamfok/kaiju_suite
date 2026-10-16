"""Animation save/load (kaiju_suite.datatypes.animation), without the Assembler.

The Assembler's Animation product (tests/test_assembler_animation.py) goes
through this module; the file format is unchanged.
"""

from maya import cmds

from kaiju_suite import datatypes
from kaiju_suite.datatypes import animation


def _box(name="box"):
    node = cmds.createNode("transform", name=name, skipSelect=True)
    cmds.setKeyframe(f"{node}.translateX", time=1, value=0)
    cmds.setKeyframe(f"{node}.translateX", time=10, value=5)
    cmds.setKeyframe(f"{node}.rotateY", time=4, value=90)
    return node


def _long(*nodes):
    return cmds.ls(nodes, long=True)


def test_kind_and_extension():
    assert animation.KIND == "animation"
    assert animation.EXTENSION == ".anim"


def test_gather_then_apply_puts_the_keys_back(new_scene):
    _box()
    payload = animation.gather(_long("box"))
    assert [(c["node"], c["attribute"]) for c in payload["curves"]] == [("box", "rotateY"), ("box", "translateX")]

    cmds.cutKey("box", clear=True)
    lines = []
    message = animation.apply(payload, info=lines.append)

    assert message == "Keyed 2 attributes (3 keys)"
    assert lines == ["box.rotateY: 1 key", "box.translateX: 2 keys"]
    assert cmds.keyframe("box.translateX", query=True, timeChange=True) == [1, 10]


def test_apply_skips_missing_nodes_with_a_maya_warning(new_scene, monkeypatch):
    _box()
    payload = animation.gather(_long("box"))
    cmds.file(new=True, force=True)
    warnings = []
    monkeypatch.setattr(datatypes, "warning", warnings.append)

    assert animation.apply(payload) == "Keyed 0 attributes (0 keys)"
    assert warnings == ["Skipped missing nodes: box"]


def test_selection_problems(new_scene):
    assert animation.selection_problems([]) == ["Nothing selected. Select the animated nodes to publish."]
    still = cmds.createNode("transform", name="still")
    [problem] = animation.selection_problems(_long(still))
    assert "keys" in problem
    assert animation.selection_problems(_long(_box())) == []


def test_describe_and_nodes(new_scene):
    payload = animation.gather(_long(_box()))
    assert animation.describe(payload) == ["2 animated attributes on 1 node, 3 keys", "Frames 1 to 10"]
    assert animation.nodes(payload) == ["box", "box"]


def test_compare_view_ignores_the_order_nodes_were_selected_in(new_scene):
    _box("a")
    _box("b")
    first = animation.gather(_long("a", "b"))
    second = animation.gather(_long("b", "a"))
    assert first != second
    assert animation.compare_view(first) == animation.compare_view(second)


def test_save_and_load_through_a_file(new_scene, tmp_path):
    _box()
    path = datatypes.save(animation, str(tmp_path / "walk.anim"), _long("box"))
    cmds.cutKey("box", clear=True)

    assert datatypes.load(animation, path) == "Keyed 2 attributes (3 keys)"
    assert cmds.keyframe("box.rotateY", query=True, valueChange=True) == [90]
