"""datatypes.animation.CHECKS: QC checks on given nodes, run by the
Animation Tool's QC tab and before Scripter publishes an Animation item.
They report problems and change nothing."""

from maya import cmds

from kaiju_suite import datatypes
from kaiju_suite.core import checks
from kaiju_suite.datatypes import animation


def _node(name="box", parent=None):
    kwargs = {"name": name, "skipSelect": True}
    if parent:
        kwargs["parent"] = parent
    return cmds.createNode("transform", **kwargs)


def _keyed(name="box", parent=None):
    node = _node(name, parent)
    cmds.setKeyframe(f"{node}.translateX", time=1, value=0)
    cmds.setKeyframe(f"{node}.translateX", time=10, value=5)
    return node


def _long(*nodes):
    return cmds.ls(nodes, long=True)


def _run(key, nodes, **options):
    return checks.get(key, animation.CHECKS).run(nodes=nodes, **options)


def test_the_animation_checks_and_their_defaults():
    assert [c.key for c in animation.CHECKS] == ["not_animated", "unsaved", "duplicate_names"]
    assert [c.label for c in animation.CHECKS] == ["Not animated", "Unsaved animation", "Duplicate names"]
    assert checks.defaults(animation.CHECKS) == {
        "not_animated": {"enabled": True},
        "unsaved": {"enabled": True},
        "duplicate_names": {"enabled": True},
    }


def test_keyed_nodes_have_no_problems(new_scene):
    a, b = _keyed("a"), _keyed("b")

    found = datatypes.run_qc(animation, _long(a, b), checks.defaults(animation.CHECKS))

    assert [(c.key, p) for c, p in found] == [(c.key, []) for c in animation.CHECKS]


def test_not_animated_names_nodes_without_keys(new_scene):
    _keyed("box")
    still = _node("still")

    [problem] = _run("not_animated", _long("box", still))

    assert problem == "still: no keys"
    assert checks.selection_of(problem) == ["still"]


def test_driven_keys_are_not_animation(new_scene):
    driver = _node("driver")
    box = _node("box")
    cmds.setDrivenKeyframe(f"{box}.translateZ", currentDriver=f"{driver}.translateX", driverValue=0, value=0)
    cmds.setDrivenKeyframe(f"{box}.translateZ", currentDriver=f"{driver}.translateX", driverValue=1, value=5)

    assert _run("not_animated", _long(box)) == ["box: no keys"]


def test_unsaved_names_driven_keys(new_scene):
    driver = _node("driver")
    box = _keyed("box")
    cmds.setDrivenKeyframe(f"{box}.translateZ", currentDriver=f"{driver}.translateX", driverValue=0, value=0)
    cmds.setDrivenKeyframe(f"{box}.translateZ", currentDriver=f"{driver}.translateX", driverValue=1, value=5)

    [problem] = _run("unsaved", _long(box))

    assert problem == "box.translateZ: driven keys"
    assert checks.selection_of(problem) == ["box"]


def test_unsaved_names_keys_through_a_pair_blend(new_scene):
    target = _node("target")
    box = _keyed("box")
    cmds.setKeyframe(f"{box}.translateY", time=1, value=2)
    cmds.parentConstraint(target, box)  # keyed + constrained: Maya adds a pairBlend
    blends = cmds.ls(type="pairBlend")
    assert blends

    found = _run("unsaved", _long(box))

    assert f"box.translateX: keys through {blends[0]}" in found
    assert all(checks.selection_of(p) == ["box"] for p in found)


def test_curves_wired_straight_in_are_saved(new_scene):
    box = _keyed("box")
    cmds.setKeyframe(f"{box}.visibility", time=1, value=1)

    assert _run("unsaved", _long(box)) == []


def test_duplicate_names_finds_nodes_sharing_a_name(new_scene):
    _node("a")
    _node("b")
    _keyed("ctl", parent="a")
    _keyed("ctl", parent="b")

    found = _run("duplicate_names", _long("a|ctl"))

    assert found == ["a|ctl: 2 nodes are called ctl"]
    assert checks.selection_of(found[0]) == ["a|ctl", "b|ctl"]


def test_checks_skip_nothing_selected(new_scene):
    for check in animation.CHECKS:
        assert check.run(nodes=[]) == []


def test_animation_checks_change_nothing(new_scene):
    box = _keyed("box")
    still = _node("still")
    cmds.select(box)
    before = (cmds.ls(long=True), cmds.keyframe(f"{box}.translateX", query=True, valueChange=True), cmds.ls(selection=True))

    datatypes.run_qc(animation, _long(box, still), checks.defaults(animation.CHECKS))

    after = (cmds.ls(long=True), cmds.keyframe(f"{box}.translateX", query=True, valueChange=True), cmds.ls(selection=True))
    assert after == before
