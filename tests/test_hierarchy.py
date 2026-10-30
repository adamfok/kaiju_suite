import pytest
from maya import cmds

from kaiju_suite.core import hierarchy


def _node(name, parent=None):
    kwargs = {"name": name, "parent": parent} if parent else {"name": name}
    return cmds.ls(cmds.createNode("transform", **kwargs), long=True)[0]


def test_set_default_parent_defaults_to_the_current_parent(new_scene):
    child = _node("child", _node("rig"))
    hierarchy.set_default_parent(child)
    assert cmds.getAttr(f"{child}.kaijuDefaultParentName") == "rig"


def test_set_default_parent_to_a_given_node(new_scene):
    rig = _node("rig")
    child = _node("child")
    hierarchy.set_default_parent(child, rig)
    assert cmds.getAttr(f"{child}.kaijuDefaultParentUuid") == cmds.ls(rig, uuid=True)[0]
    assert hierarchy.reparent([child]) == ["|rig|child"]


def test_set_default_parent_to_the_world(new_scene):
    child = _node("child", _node("rig"))
    hierarchy.set_default_parent(child, "")
    assert hierarchy.reparent([child]) == ["|child"]


def test_has_default_parent(new_scene):
    child = _node("child")
    assert not hierarchy.has_default_parent(child)
    hierarchy.set_default_parent(child)
    assert hierarchy.has_default_parent(child)


def test_reparent_skip_missing_leaves_nodes_whose_parent_is_gone(new_scene):
    gone = _node("gone")
    a = _node("a")
    b = _node("b")
    home = _node("home")
    hierarchy.set_default_parent(a, gone)
    hierarchy.set_default_parent(b, home)
    cmds.delete(gone)
    with pytest.raises(ValueError, match="no longer exists"):
        hierarchy.reparent([a, b])
    assert hierarchy.reparent([a, b], skip_missing=True) == ["|a", "|home|b"]


def test_reparent_skip_missing_with_nothing_to_move_does_not_raise(new_scene):
    gone = _node("gone")
    a = _node("a")
    hierarchy.set_default_parent(a, gone)
    cmds.delete(gone)
    assert hierarchy.reparent([a], skip_missing=True) == ["|a"]


def test_reparent_without_any_default_raises(new_scene):
    with pytest.raises(ValueError, match="No default parent"):
        hierarchy.reparent([_node("a")], skip_missing=True)
