"""datatypes.blendshape.CHECKS: QC checks on given meshes' blendShapes, run
by the BlendShape Tool's QC tab and before Scripter publishes a BlendShapes
item. They report problems and change nothing."""

from maya import cmds

from kaiju_suite import datatypes
from kaiju_suite.core import checks
from kaiju_suite.datatypes import blendshape


def _base(name="face"):
    return cmds.polyPlane(name=name, subdivisionsX=4, subdivisionsY=4, constructionHistory=False)[0]


def _target(base, name, moved=True):
    target = cmds.duplicate(base, name=name)[0]
    if moved:
        cmds.move(0, 1, 0, f"{target}.vtx[0]", relative=True, objectSpace=True)
    return target


def _rig(name="face", skin=False, **order):
    """``name`` with blendShape ``<name>BS`` holding target ``smile``; with
    ``skin``, skinned to one joint first, the blendShape placed by ``order``
    (``frontOfChain=True`` or ``after=True``)."""
    base = _base(name)
    if skin:
        cmds.select(clear=True)
        joint = cmds.joint(name=f"{name}_jnt")
        cmds.select(clear=True)
        cmds.skinCluster(joint, base, toSelectedBones=True, name=f"{name}_skin")
    smile = _target(base, "smile")
    node = cmds.blendShape(smile, base, name=f"{name}BS", **order)[0]
    cmds.delete(smile)
    return base, node


def _long(*nodes):
    return cmds.ls(nodes, long=True)


def _run(key, nodes):
    return checks.get(key, blendshape.CHECKS).run(nodes=nodes)


def test_the_blendshape_checks_and_their_defaults():
    assert [c.key for c in blendshape.CHECKS] == ["blendshape", "order", "empty_targets", "duplicate_names"]
    assert [c.label for c in blendshape.CHECKS] == ["No blendShape", "Above skin", "Empty targets", "Duplicate names"]
    assert checks.defaults(blendshape.CHECKS) == {
        "blendshape": {"enabled": True},
        "order": {"enabled": True},
        "empty_targets": {"enabled": True},
        "duplicate_names": {"enabled": True},
    }


def test_a_clean_blendshape_before_the_skin_has_no_problems(new_scene):
    base, _ = _rig(skin=True, frontOfChain=True)

    found = datatypes.run_qc(blendshape, _long(base), checks.defaults(blendshape.CHECKS))

    assert [(c.key, p) for c, p in found] == [(c.key, []) for c in blendshape.CHECKS]


def test_no_blendshape_names_meshes_without_one(new_scene):
    plain = _base("plain")
    rigged, _ = _rig()

    [problem] = _run("blendshape", _long(plain, rigged))

    assert problem == "plain: no blendShape"
    assert checks.selection_of(problem) == ["plain"]


def test_above_skin_names_a_blendshape_evaluated_after_the_skin(new_scene):
    base, _ = _rig(skin=True, after=True)

    [problem] = _run("order", _long(base))

    assert problem == "face: faceBS evaluates after face_skin; it should be at the front of the chain"
    assert checks.selection_of(problem) == ["face"]


def test_above_skin_skips_meshes_without_a_skin(new_scene):
    base, _ = _rig()

    assert _run("order", _long(base)) == []


def test_empty_targets_names_targets_with_no_deltas(new_scene):
    base = _base()
    smile, blank, blink = _target(base, "smile"), _target(base, "blank", moved=False), _target(base, "blink", moved=False)
    node = cmds.blendShape(smile, blank, blink, base, name="faceBS")[0]
    cmds.delete(smile, blank, blink)

    [problem] = _run("empty_targets", _long(base))

    assert problem == "face: faceBS has 2 empty targets: blank, blink"
    assert checks.selection_of(problem) == ["face"]
    assert cmds.ls(type="blendShape") == [node]


def test_empty_targets_reads_a_live_sculpt_mesh(new_scene):
    base = _base()
    smile = _target(base, "smile", moved=False)
    cmds.blendShape(smile, base, name="faceBS")
    assert _run("empty_targets", _long(base)) == ["face: faceBS has 1 empty target: smile"]

    cmds.move(0, 1, 0, f"{smile}.vtx[0]", relative=True, objectSpace=True)

    assert _run("empty_targets", _long(base)) == []


def test_duplicate_names_finds_meshes_sharing_a_name(new_scene):
    cmds.group(empty=True, name="grp")
    base, _ = _rig()
    cmds.parent(base, "grp")
    cmds.group(empty=True, name="other")
    cmds.parent(_base("face"), "other")

    [problem] = _run("duplicate_names", _long("grp|face"))

    assert problem == "grp|face: 2 nodes are called face"
    assert checks.selection_of(problem) == ["grp|face", "other|face"]


def test_checks_skip_what_isnt_a_mesh(new_scene):
    joint = cmds.createNode("joint", name="jnt")

    for check in blendshape.CHECKS:
        assert check.run(nodes=_long(joint)) == []


def test_blendshape_checks_change_nothing(new_scene):
    base, node = _rig(skin=True, after=True)
    cmds.select(base)
    before = (cmds.ls(long=True), cmds.getAttr(f"{node}.smile"), cmds.ls(selection=True))

    datatypes.run_qc(blendshape, _long(base), checks.defaults(blendshape.CHECKS))

    assert (cmds.ls(long=True), cmds.getAttr(f"{node}.smile"), cmds.ls(selection=True)) == before


def test_every_check_runs_before_publishing():
    assert all(check.publish for check in blendshape.CHECKS)
