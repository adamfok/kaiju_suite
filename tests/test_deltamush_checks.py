"""datatypes.deltamush.CHECKS: QC checks on the deltaMush nodes of given
meshes, run by the DeltaMush Tool's QC tab and before Builder publishes a
DeltaMush item. They report problems and change nothing."""

from maya import cmds

from kaiju_suite import datatypes
from kaiju_suite.core import checks
from kaiju_suite.datatypes import deltamush


def _mesh(name="body"):
    return cmds.polyCube(name=name, sx=2, sy=2, sz=2, ch=False)[0]


def _skinned(name="body"):
    mesh = _mesh(name)
    cmds.select(clear=True)
    joint = cmds.joint(name=f"{name}_jnt")
    cmds.select(clear=True)
    cmds.skinCluster(joint, mesh, toSelectedBones=True, name=f"{name}_skin")
    return mesh


def _long(*nodes):
    return cmds.ls(nodes, long=True)


def _run(key, nodes, **options):
    return checks.get(key, deltamush.CHECKS).run(nodes=nodes, **options)


def test_the_deltamush_checks_and_their_defaults():
    assert [c.key for c in deltamush.CHECKS] == ["missing", "below_skin", "disabled", "empty_weights", "duplicate_names"]
    assert [c.label for c in deltamush.CHECKS] == [
        "No deltaMush",
        "Below skin",
        "Disabled",
        "Empty weights",
        "Duplicate names",
    ]
    assert checks.defaults(deltamush.CHECKS) == {c.key: {"enabled": True} for c in deltamush.CHECKS}
    assert all(c.publish and c.fix is None for c in deltamush.CHECKS)


def test_a_deltamush_on_top_of_skin_has_no_problems(new_scene):
    mesh = _skinned()
    cmds.deltaMush(mesh, name="body_dm")

    found = datatypes.run_qc(deltamush, _long(mesh), checks.defaults(deltamush.CHECKS))

    assert [(c.key, p) for c, p in found] == [(c.key, []) for c in deltamush.CHECKS]


def test_no_deltamush(new_scene):
    body, head = _mesh("body"), _mesh("head")
    cmds.deltaMush(body)

    problems = _run("missing", _long(body, head))

    assert problems == ["head: no deltaMush"]
    assert checks.selection_of(problems[0]) == ["head"]


def test_below_skin(new_scene):
    mesh = _mesh()
    node = cmds.deltaMush(mesh, name="body_dm")[0]
    cmds.select(clear=True)
    joint = cmds.joint(name="body_jnt")
    cmds.skinCluster(joint, mesh, toSelectedBones=True, name="body_skin")  # added after: on top of the deltaMush

    problems = _run("below_skin", _long(mesh))

    assert problems == ["body_dm on body: evaluates before body_skin"]
    assert checks.selection_of(problems[0]) == [node]


def test_on_top_of_skin_is_fine(new_scene):
    mesh = _skinned()
    cmds.deltaMush(mesh)

    assert _run("below_skin", _long(mesh)) == []


def test_disabled_by_envelope_or_node_state(new_scene):
    body, head, arm = _mesh("body"), _mesh("head"), _mesh("arm")
    cmds.setAttr(cmds.deltaMush(body, name="body_dm")[0] + ".envelope", 0)
    cmds.setAttr(cmds.deltaMush(head, name="head_dm")[0] + ".nodeState", 1)
    cmds.deltaMush(arm, name="arm_dm")

    problems = _run("disabled", _long(body, head, arm))

    assert problems == ["body_dm on body: envelope is 0", "head_dm on head: node state is HasNoEffect"]
    assert checks.selection_of(problems[0]) == ["body_dm"]


def test_empty_weights(new_scene):
    body, head = _mesh("body"), _mesh("head")
    empty = cmds.deltaMush(body, name="body_dm")[0]
    count = cmds.polyEvaluate(body, vertex=True)
    cmds.setAttr(f"{empty}.weightList[0].weights[0:{count - 1}]", *[0.0] * count, size=count)
    painted = cmds.deltaMush(head, name="head_dm")[0]
    cmds.setAttr(f"{painted}.weightList[0].weights[0:{count - 1}]", *[0.0] * count, size=count)
    cmds.setAttr(f"{painted}.weightList[0].weights[4]", 0.5)

    problems = _run("empty_weights", _long(body, head))

    assert problems == ["body_dm on body: every weight is 0"]
    assert checks.selection_of(problems[0]) == ["body_dm"]


def test_duplicate_names(new_scene):
    body = _long(_mesh("body"))[0]
    group = cmds.createNode("transform", name="grp")
    other = cmds.parent(_mesh("other"), group)[0]
    cmds.rename(f"grp|{other}", "body")
    cmds.deltaMush(body)

    problems = _run("duplicate_names", [body])

    assert problems == ["|body: 2 nodes are called body"]
    assert sorted(checks.selection_of(problems[0])) == ["grp|body", "|body"]


def test_checks_change_nothing(new_scene):
    mesh = _mesh()
    node = cmds.deltaMush(mesh, name="body_dm")[0]
    cmds.setAttr(f"{node}.envelope", 0)
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    datatypes.run_qc(deltamush, _long(mesh), checks.defaults(deltamush.CHECKS))

    assert cmds.getAttr(f"{node}.envelope") == 0
    assert not cmds.undoInfo(query=True, undoName=True)
