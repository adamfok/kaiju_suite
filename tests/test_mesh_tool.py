import pytest
from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.core import checks
from kaiju_suite.datatypes import mesh as mesh_data
from kaiju_suite.tools.mesh_tool import logic


def _cube(name="body", **kwargs):
    return cmds.ls(cmds.polyCube(name=name, constructionHistory=False, **kwargs)[0], long=True)[0]


def _mesh(points, faces, name="geo"):
    """A mesh built straight from ``points`` and ``faces`` (vertex lists),
    with no UVs, for shapes polyCube can't make."""
    transform = cmds.createNode("transform", name=name)
    parent = om.MSelectionList().add(transform).getDependNode(0)
    counts = [len(face) for face in faces]
    connects = [v for face in faces for v in face]
    om.MFnMesh().create([om.MPoint(*p) for p in points], counts, connects, parent=parent)
    cmds.sets(transform, edit=True, forceElement="initialShadingGroup")
    return cmds.ls(transform, long=True)[0]


def _found(mesh, key):
    """What check ``key`` points at on ``mesh``: its faces, edges, vertices
    or the mesh itself, as long names."""
    problems = checks.get(key, mesh_data.CHECKS).run(nodes=[mesh])
    assert len(problems) <= 1
    return checks.selection_of(problems[0]) if problems else []


# -- the checks -------------------------------------------------------------


def test_every_check_has_a_label_and_description():
    keys = [check.key for check in mesh_data.CHECKS]
    assert len(keys) == len(set(keys))
    for check in mesh_data.CHECKS:
        assert check.label and check.description


def test_the_mesh_checks():
    assert [c.key for c in mesh_data.CHECKS] == [
        "ngons", "non_manifold", "lamina", "zero_area", "zero_length", "uvs",
        "normals", "symmetry", "transforms", "history", "names", "shape_names",
    ]  # fmt: skip


def test_symmetry_and_uvs_are_left_out_of_publish():
    assert [c.key for c in mesh_data.CHECKS if not c.publish] == ["uvs", "symmetry"]


def _problems(selection):
    return {check.key: problems for check, problems in logic.run_qc(selection) if problems}


def test_a_clean_cube_passes_every_check(new_scene):
    assert _problems([_cube()]) == {}


def test_problems_are_one_per_mesh_naming_it(new_scene):
    a, b = _cube("a"), _cube("b")
    cmds.setAttr(f"{b}.translateX", 2)

    assert _problems([a, b]) == {"transforms": ["b: transform not frozen"]}


@pytest.mark.parametrize("key, make, text", [
    ("ngons", "ngon", "p: 1 face with more than 4 sides"),
    ("uvs", "no_uvs", "geo: 1 face without UVs"),
    ("history", "history", "body: construction history"),
    ("shape_names", "shape_name", "body: shape is oops, not bodyShape"),
])
def test_problem_messages(new_scene, key, make, text):
    if make == "ngon":
        mesh = cmds.ls(cmds.polyPlane(name="p", sx=2, sy=1, constructionHistory=False)[0], long=True)[0]
        cmds.polyDelEdge(f"{mesh}.e[3]", cleanVertices=False, constructionHistory=False)
    elif make == "no_uvs":
        mesh = _mesh([(0, 0, 0), (1, 0, 0), (0, 0, 1)], [[0, 1, 2]])
    elif make == "history":
        mesh = cmds.ls(cmds.polyCube(name="body")[0], long=True)[0]
    else:
        mesh = _cube()
        cmds.rename(cmds.listRelatives(mesh, shapes=True, fullPath=True)[0], "oops")

    assert checks.get(key, mesh_data.CHECKS).run(nodes=[mesh]) == [text]


def test_ngons(new_scene):
    plane = cmds.ls(cmds.polyPlane(name="p", sx=2, sy=1, constructionHistory=False)[0], long=True)[0]
    cmds.polyDelEdge(f"{plane}.e[3]", cleanVertices=False, constructionHistory=False)

    assert _found(plane, "ngons") == [f"{plane}.f[0]"]


def test_non_manifold(new_scene):
    # Three triangles share the edge 0-1.
    mesh = _mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1)], [[0, 1, 2], [1, 0, 3], [0, 1, 4]])

    assert f"{mesh}.e[0]" in _found(mesh, "non_manifold")


def test_lamina_faces(new_scene):
    mesh = _mesh([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [[0, 1, 2, 3], [3, 2, 1, 0]])

    assert _found(mesh, "lamina") == [f"{mesh}.f[1]"]


def test_zero_area_faces(new_scene):
    # The second face's corners are on a line.
    mesh = _mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0), (2, 0, 0)], [[0, 1, 2], [0, 3, 1]])

    assert _found(mesh, "zero_area") == [f"{mesh}.f[1]"]


def test_zero_length_edges(new_scene):
    mesh = _mesh([(0, 0, 0), (1, 0, 0), (1, 0, 0), (0, 1, 0)], [[0, 1, 2, 3]])

    assert _found(mesh, "zero_length") == [f"{mesh}.e[1]"]


def test_faces_without_uvs(new_scene):
    mesh = _mesh([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [[0, 1, 2]])

    assert _found(mesh, "uvs") == [f"{mesh}.f[0]"]


def test_locked_normals(new_scene):
    cube = _cube()
    cmds.polyNormalPerVertex(f"{cube}.vtx[3]", xyz=(0, 1, 0))

    assert _found(cube, "normals") == [f"{cube}.vtx[3]"]


def test_symmetry(new_scene):
    cube = _cube()
    assert _found(cube, "symmetry") == []

    cmds.move(0.2, 0, 0, f"{cube}.vtx[1]", relative=True)

    assert sorted(_found(cube, "symmetry")) == [f"{cube}.vtx[0]", f"{cube}.vtx[1]"]


def test_symmetry_counts_vertices_on_the_mirror_plane(new_scene):
    plane = cmds.ls(cmds.polyPlane(name="p", sx=2, sy=1, constructionHistory=False)[0], long=True)[0]

    assert _found(plane, "symmetry") == []


def test_unfrozen_transforms(new_scene):
    cube = _cube()
    cmds.setAttr(f"{cube}.rotateY", 10)

    assert _found(cube, "transforms") == [cube]


def test_construction_history(new_scene):
    cube = cmds.ls(cmds.polyCube(name="body")[0], long=True)[0]

    assert _found(cube, "history") == [cube]


def test_deformers_are_not_history(new_scene):
    cube = _cube()
    joint = cmds.createNode("joint")
    cmds.skinCluster(joint, cube)

    assert _found(cube, "history") == []


def test_duplicate_names(new_scene):
    a = _cube()
    group = cmds.createNode("transform", name="grp")
    b = cmds.parent(_cube(), group)[0]
    b = cmds.rename(b, "body")

    assert _found(a, "names") == [a]


def test_shape_names(new_scene):
    cube = _cube()
    cmds.rename(cmds.listRelatives(cube, shapes=True, fullPath=True)[0], "oops")

    assert _found(cube, "shape_names") == [cube]


# -- fixing -----------------------------------------------------------------


@pytest.mark.parametrize("key", [check.key for check in mesh_data.CHECKS if check.fix])
def test_only_some_checks_can_fix(key):
    assert key in {"transforms", "history", "normals", "shape_names"}


def _broken(key):
    if key == "transforms":
        cube = _cube()
        cmds.xform(cube, translation=(1, 2, 3), rotation=(0, 30, 0), scale=(2, 2, 2))
    elif key == "history":
        cube = cmds.ls(cmds.polyCube(name="body")[0], long=True)[0]
    elif key == "normals":
        cube = _cube()
        cmds.polyNormalPerVertex(f"{cube}.vtx[3]", xyz=(0, 1, 0))
    else:
        cube = _cube()
        cmds.rename(cmds.listRelatives(cube, shapes=True, fullPath=True)[0], "oops")
    return cube


@pytest.mark.parametrize("key", ["transforms", "history", "normals", "shape_names"])
def test_fix_clears_the_problem_in_one_undo_step(new_scene, key):
    cmds.undoInfo(state=True)
    cube = _broken(key)
    assert _found(cube, key)

    logic.fix(key, [cube])

    assert _found(cube, key) == []
    cmds.undo()
    assert _found(cube, key)


def test_fixing_transforms_keeps_the_mesh_in_place(new_scene):
    cube = _cube()
    cmds.xform(cube, translation=(1, 2, 3), rotation=(0, 30, 0))
    before = cmds.xform(f"{cube}.vtx[0]", query=True, worldSpace=True, translation=True)

    logic.fix("transforms", [cube])

    assert cmds.xform(f"{cube}.vtx[0]", query=True, worldSpace=True, translation=True) == pytest.approx(before)


def test_fixing_history_keeps_deformers(new_scene):
    cube = cmds.ls(cmds.polyCube(name="body")[0], long=True)[0]
    joint = cmds.createNode("joint")
    cluster = cmds.skinCluster(joint, cube)[0]

    logic.fix("history", [cube])

    assert cmds.objExists(cluster)
    assert not cmds.ls(cmds.listHistory(cube), type="polyCube")


def test_fix_refuses_a_check_that_cannot_fix(new_scene):
    with pytest.raises(ValueError):
        logic.fix("ngons", [_cube()])


# -- the QC tab -------------------------------------------------------------


def test_qc_takes_transforms_shapes_and_components(new_scene):
    a, b, c = _cube("a"), _cube("b"), _cube("c")
    for cube in (a, b, c):
        cmds.setAttr(f"{cube}.translateY", 1)
    shape = cmds.listRelatives(b, shapes=True, fullPath=True)[0]
    joint = cmds.createNode("joint")

    found = _problems([a, shape, f"{c}.vtx[0]", cmds.ls(joint, long=True)[0], a])

    assert found["transforms"] == ["a: transform not frozen", "b: transform not frozen", "c: transform not frozen"]


def test_qc_needs_meshes(new_scene):
    _cube()
    joint = cmds.ls(cmds.createNode("joint"), long=True)[0]

    with pytest.raises(ValueError, match="No meshes selected"):
        logic.run_qc([joint])
    with pytest.raises(ValueError, match="No meshes selected"):
        logic.run_qc([])


def test_qc_options_are_saved_for_publish_too(new_scene):
    from kaiju_suite import datatypes

    assert logic.qc_settings() == datatypes.qc_settings(mesh_data)


def test_fix_on_the_selection_returns_fresh_results(new_scene):
    cube = _broken("shape_names")

    found = logic.fix_and_check("shape_names", [cube])

    assert dict((c.key, p) for c, p in found)["shape_names"] == []


def test_select_problem_selects_the_components(new_scene):
    plane = cmds.ls(cmds.polyPlane(name="p", sx=2, sy=1, constructionHistory=False)[0], long=True)[0]
    cmds.polyDelEdge(f"{plane}.e[3]", cleanVertices=False, constructionHistory=False)
    [problem] = _problems([plane])["ngons"]

    logic.select_problem(problem)

    assert cmds.ls(selection=True) == ["p.f[0]"]
