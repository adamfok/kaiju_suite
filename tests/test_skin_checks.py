"""datatypes.skin.CHECKS: QC checks on the skinClusters of given meshes,
run by the SkinCluster Tool's QC tab. They report problems and change nothing."""

import pytest
from maya import cmds

from kaiju_suite import datatypes
from kaiju_suite.core import checks
from kaiju_suite.datatypes import skin


def _joint(name, x):
    cmds.select(clear=True)
    return cmds.joint(name=name, position=(x, 0, 0))


def _skinned(name="body", joints=("a", "b", "c")):
    """A 1x1 plane (4 vertices) bound to ``joints``, every vertex fully on the first."""
    made = [_joint(j, i) for i, j in enumerate(joints)]
    plane = cmds.polyPlane(name=name, width=2, height=2, sx=1, sy=1, constructionHistory=False)[0]
    cluster = cmds.skinCluster(*made, plane, toSelectedBones=True)[0]
    cmds.skinPercent(cluster, f"{plane}.vtx[0:3]", transformValue=[(made[0], 1.0)])
    return plane, cluster


def _long(*nodes):
    return cmds.ls(nodes, long=True)


def _run(key, nodes, **options):
    return checks.get(key, skin.CHECKS).run(nodes=nodes, **options)


def test_the_skin_checks_and_their_defaults():
    assert [c.key for c in skin.CHECKS] == ["skinned", "normalized", "influence_count", "small_weights", "unused"]
    assert checks.defaults(skin.CHECKS) == {
        "skinned": {"enabled": True},
        "normalized": {"enabled": True, "tolerance": 0.001},
        "influence_count": {"enabled": True, "max_influences": 4},
        "small_weights": {"enabled": True, "threshold": 0.001},
        "unused": {"enabled": True},
    }


def test_a_clean_skin_has_no_problems(new_scene):
    plane, _ = _skinned(joints=("a",))

    assert [(c.key, p) for c, p in checks.run(None, skin.CHECKS, nodes=_long(plane))] == [
        ("skinned", []),
        ("normalized", []),
        ("influence_count", []),
        ("small_weights", []),
        ("unused", []),
    ]


def test_not_skinned_names_meshes_without_a_skincluster(new_scene):
    plane, _ = _skinned()
    bare = cmds.polyCube(name="bare", constructionHistory=False)[0]

    [problem] = _run("skinned", _long(plane, bare))

    assert problem == "bare: no skinCluster"
    assert checks.selection_of(problem) == ["bare"]


def test_other_checks_skip_meshes_without_a_skincluster(new_scene):
    cmds.polyCube(name="bare", constructionHistory=False)

    for key in ("normalized", "influence_count", "small_weights", "unused"):
        assert _run(key, _long("bare")) == []


def test_normalized_finds_vertices_whose_weights_dont_add_up_to_one(new_scene):
    plane, cluster = _skinned()
    cmds.setAttr(f"{cluster}.normalizeWeights", 0)
    cmds.setAttr(f"{cluster}.weightList[1].weights[0]", 0.5)
    cmds.setAttr(f"{cluster}.weightList[2].weights[0]", 0.9995)

    [problem] = _run("normalized", _long(plane))

    assert problem == "body: 1 vertex doesn't add up to 1 (furthest off by 0.5)"
    assert checks.selection_of(problem) == ["body.vtx[1]"]
    assert _run("normalized", _long(plane), tolerance=0.0001)[0].select == ["body.vtx[1:2]"]


def test_influence_count_finds_vertices_with_too_many_influences(new_scene):
    plane, cluster = _skinned()
    cmds.skinPercent(cluster, f"{plane}.vtx[0:1]", transformValue=[("a", 0.5), ("b", 0.3), ("c", 0.2)])

    [problem] = _run("influence_count", _long(plane), max_influences=2)

    assert problem == "body: 2 vertices have more than 2 influences (up to 3)"
    assert checks.selection_of(problem) == ["body.vtx[0:1]"]
    assert _run("influence_count", _long(plane), max_influences=3) == []


def test_small_weights_finds_vertices_with_tiny_weights(new_scene):
    plane, cluster = _skinned()
    cmds.skinPercent(cluster, f"{plane}.vtx[3]", transformValue=[("a", 0.9995), ("b", 0.0005)])

    [problem] = _run("small_weights", _long(plane))

    assert problem == "body: 1 vertex has weights below 0.001"
    assert checks.selection_of(problem) == ["body.vtx[3]"]


def test_unused_finds_influences_with_no_weight(new_scene):
    plane, _ = _skinned()

    [problem] = _run("unused", _long(plane))

    assert problem == "body: 2 unused influences: b, c"
    assert checks.selection_of(problem) == ["b", "c"]


def test_skin_checks_take_shapes_and_components_as_their_mesh(new_scene):
    plane, _ = _skinned()
    shape = cmds.listRelatives(plane, shapes=True, noIntermediate=True)[0]

    assert len(_run("unused", _long(shape))) == 1
    assert len(_run("unused", [f"{plane}.vtx[0]"])) == 1


def test_skin_checks_change_nothing(new_scene):
    plane, cluster = _skinned()
    cmds.select(plane)
    before = (cmds.ls(long=True), cmds.getAttr(f"{cluster}.weightList[0].weights")[0], cmds.ls(selection=True))

    checks.run(None, skin.CHECKS, nodes=_long(plane))

    assert (cmds.ls(long=True), cmds.getAttr(f"{cluster}.weightList[0].weights")[0], cmds.ls(selection=True)) == before


@pytest.mark.parametrize("indices, expected", [
    ([], []),
    ([4], ["m.vtx[4]"]),
    ([0, 1, 2, 5, 7, 8], ["m.vtx[0:2]", "m.vtx[5]", "m.vtx[7:8]"]),
])
def test_vertex_ranges_fold_runs_of_indices(indices, expected):
    assert skin.vertex_ranges("m", indices) == expected


# -- QC through datatypes (shared by the tool and Scripter's Publish) ---------


@pytest.fixture
def clean_qc_settings():
    def clear():
        for name in cmds.optionVar(list=True) or []:
            if name.startswith("kaiju_suite_datatype_skin_"):
                cmds.optionVar(remove=name)

    clear()
    yield
    clear()


def test_qc_settings_start_at_the_defaults(clean_qc_settings):
    assert datatypes.qc_settings(skin) == checks.defaults(skin.CHECKS)


def test_saved_qc_settings_are_read_back(clean_qc_settings):
    datatypes.save_qc_setting(skin, "influence_count", "max_influences", 6)

    assert datatypes.qc_settings(skin)["influence_count"]["max_influences"] == 6


def test_every_check_runs_even_if_one_was_saved_as_off(new_scene, clean_qc_settings):
    plane, _ = _skinned()
    datatypes.save_qc_setting(skin, "unused", "enabled", False)

    assert datatypes.qc_settings(skin)["unused"]["enabled"] is True
    found = [check.key for check, _ in datatypes.run_qc(skin, _long(plane))]
    assert found == ["skinned", "normalized", "influence_count", "small_weights", "unused"]


def test_run_qc_uses_the_saved_options(new_scene, clean_qc_settings):
    plane, cluster = _skinned()
    cmds.skinPercent(cluster, f"{plane}.vtx[0]", transformValue=[("a", 0.5), ("b", 0.5)])
    datatypes.save_qc_setting(skin, "influence_count", "max_influences", 1)

    found = dict((check.key, problems) for check, problems in datatypes.run_qc(skin, _long(plane)))

    assert len(found["influence_count"]) == 1


def test_a_datatype_without_checks_has_no_qc(new_scene):
    from kaiju_suite.datatypes import joints

    assert datatypes.run_qc(joints, []) == []


def test_failed_keeps_only_checks_that_found_something(new_scene, clean_qc_settings):
    plane, _ = _skinned()

    failed = datatypes.qc_failed(datatypes.run_qc(skin, _long(plane)))

    assert [(check.key, problems) for check, problems in failed] == [("unused", ["body: 2 unused influences: b, c"])]
