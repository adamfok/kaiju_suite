"""datatypes.joints.CHECKS: QC checks on given joints and the joints below
them, run by the Joint Tool's QC tab and before Scripter publishes a Joints
item. They report problems and change nothing."""

import pytest
from maya import cmds

from kaiju_suite import datatypes
from kaiju_suite.core import checks
from kaiju_suite.datatypes import joints


def _chain(names, positions, parent=None):
    """Joints ``names`` at world ``positions``, each under the one before."""
    cmds.select(parent or None) if parent else cmds.select(clear=True)
    made = [cmds.joint(name=n, position=p) for n, p in zip(names, positions)]
    cmds.select(clear=True)
    return made


def _clean_leg(side="L", x=1.0):
    return _chain([f"{side}_hip", f"{side}_knee", f"{side}_ankle"], [(x, 10, 0), (x, 5, 1), (x, 1, 0)])


def _long(*nodes):
    return cmds.ls(nodes, long=True)


def _run(key, nodes, **options):
    return checks.get(key, joints.CHECKS).run(nodes=nodes, **options)


def test_the_joint_checks_and_their_defaults():
    assert [c.key for c in joints.CHECKS] == ["rotate", "scale", "end_orient", "overlapping", "duplicate_names", "mirror"]
    assert checks.defaults(joints.CHECKS) == {
        "rotate": {"enabled": True},
        "scale": {"enabled": True},
        "end_orient": {"enabled": True},
        "overlapping": {"enabled": True, "tolerance": 0.001},
        "duplicate_names": {"enabled": True},
        "mirror": {"enabled": True, "tolerance": 0.01},
    }


def test_clean_mirrored_legs_have_no_problems(new_scene):
    left, right = _clean_leg("L", 1.0), _clean_leg("R", -1.0)
    for leg in (left, right):
        cmds.joint(leg[0], edit=True, orientJoint="xyz", secondaryAxisOrient="yup", children=True, zeroScaleOrient=True)
        cmds.setAttr(f"{leg[2]}.jointOrient", 0, 0, 0, type="double3")  # as the Joint Tool's Orient leaves end joints

    found = datatypes.run_qc(joints, _long(left[0], right[0]), checks.defaults(joints.CHECKS))

    assert [(c.key, p) for c, p in found] == [(c.key, []) for c in joints.CHECKS]


def test_checks_look_at_the_joints_below_the_selected_ones(new_scene):
    hip, knee, _ = _clean_leg()
    cmds.setAttr(f"{knee}.rotateY", 30)

    assert _run("rotate", _long(hip)) == ["L_knee: rotate is (0, 30, 0)"]


def test_rotate_names_joints_with_rotate_values(new_scene):
    hip, knee, ankle = _clean_leg()
    cmds.setAttr(f"{hip}.rotate", 10, 0, -5.5, type="double3")

    [problem] = _run("rotate", _long(hip))

    assert problem == "L_hip: rotate is (10, 0, -5.5)"
    assert checks.selection_of(problem) == ["L_hip"]


def test_scale_names_joints_not_at_scale_one(new_scene):
    hip, _, ankle = _clean_leg()
    cmds.setAttr(f"{ankle}.scale", 1, 2, 1, type="double3")

    [problem] = _run("scale", _long(hip))

    assert problem == "L_ankle: scale is (1, 2, 1)"
    assert checks.selection_of(problem) == ["L_ankle"]


def test_end_orient_names_end_joints_with_a_joint_orient(new_scene):
    hip, knee, ankle = _clean_leg()
    cmds.setAttr(f"{knee}.jointOrient", 0, 0, 20, type="double3")
    cmds.setAttr(f"{ankle}.jointOrient", 0, 0, 20, type="double3")

    [problem] = _run("end_orient", _long(hip))

    assert problem == "L_ankle: end joint has joint orient (0, 0, 20)"
    assert checks.selection_of(problem) == ["L_ankle"]


def test_overlapping_names_joints_at_their_parents_position(new_scene):
    hip, knee = _chain(["hip", "knee"], [(0, 10, 0), (0, 10.0005, 0)])

    [problem] = _run("overlapping", _long(hip))

    assert problem == "knee: at the same position as hip"
    assert checks.selection_of(problem) == ["knee", "hip"]
    assert _run("overlapping", _long(hip), tolerance=0.0001) == []


def test_duplicate_names_finds_joints_sharing_a_name(new_scene):
    first = _chain(["arm_grp_a"], [(0, 0, 0)])[0]
    cmds.select(clear=True)
    cmds.group(empty=True, name="grp")
    _chain(["arm"], [(0, 0, 0)], parent="grp")
    cmds.select(clear=True)
    cmds.group(empty=True, name="other")
    _chain(["arm"], [(1, 0, 0)], parent="other")

    found = _run("duplicate_names", _long("grp|arm", first))

    assert found == ["grp|arm: 2 nodes are called arm"]
    assert checks.selection_of(found[0]) == ["grp|arm", "other|arm"]


def test_mirror_finds_a_missing_opposite_joint(new_scene):
    hip = _clean_leg("L", 1.0)[0]

    found = _run("mirror", _long(hip))

    assert found == ["L_hip: no R_hip", "L_knee: no R_knee", "L_ankle: no R_ankle"]
    assert checks.selection_of(found[0]) == ["L_hip"]


def test_mirror_finds_an_opposite_joint_not_at_the_mirrored_position(new_scene):
    left, right = _clean_leg("L", 1.0), _clean_leg("R", -1.0)
    cmds.move(0, 0.5, 0, right[2], relative=True, worldSpace=True)

    found = _run("mirror", _long(left[0], right[0]))

    assert found == ["L_ankle: R_ankle isn't at its mirrored position (off by 0.5)"]
    assert checks.selection_of(found[0]) == ["L_ankle", "R_ankle"]


def test_mirror_skips_joints_without_a_side(new_scene):
    root = _chain(["spine_01", "spine_02"], [(0, 10, 0), (0, 12, 0)])[0]

    assert _run("mirror", _long(root)) == []


def test_checks_skip_what_isnt_a_joint(new_scene):
    cube = cmds.polyCube(name="box", constructionHistory=False)[0]
    cmds.setAttr(f"{cube}.rotateY", 45)

    for check in joints.CHECKS:
        assert check.run(nodes=_long(cube)) == []


def test_joint_checks_change_nothing(new_scene):
    hip = _clean_leg()[0]
    cmds.setAttr(f"{hip}.rotateX", 10)
    cmds.select(hip)
    before = (cmds.ls(long=True), cmds.getAttr(f"{hip}.rotate"), cmds.ls(selection=True))

    datatypes.run_qc(joints, _long(hip), checks.defaults(joints.CHECKS))

    assert (cmds.ls(long=True), cmds.getAttr(f"{hip}.rotate"), cmds.ls(selection=True)) == before


@pytest.mark.parametrize("values, text", [((0, 0, 0), "(0, 0, 0)"), ((1.23456, -0.5, 90), "(1.235, -0.5, 90)")])
def test_vectors_read_short(values, text):
    assert joints.vector_text(values) == text
