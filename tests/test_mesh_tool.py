import pytest
from maya import cmds
from maya.api import OpenMaya as om

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
    """The items check ``key`` finds on ``mesh``."""
    results = logic.run([mesh], [key])
    assert [r.check.key for r in results] in ([], [key])
    return results[0].items if results else []


# -- the checks -------------------------------------------------------------


def test_every_check_has_a_label_and_description():
    keys = [check.key for check in logic.CHECKS]
    assert len(keys) == len(set(keys))
    for check in logic.CHECKS:
        assert check.label and check.description


def test_a_clean_cube_passes_every_check(new_scene):
    assert logic.run([_cube()]) == []


def test_run_reports_each_problem_per_mesh(new_scene):
    a, b = _cube("a"), _cube("b")
    cmds.setAttr(f"{b}.translateX", 2)

    results = logic.run([a, b])

    assert [(r.check.key, r.mesh) for r in results] == [("transforms", b)]


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


def test_open_borders(new_scene):
    plane = cmds.ls(cmds.polyPlane(name="p", sx=1, sy=1, constructionHistory=False)[0], long=True)[0]

    assert sorted(_found(plane, "borders")) == [f"{plane}.e[{i}]" for i in range(4)]


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


@pytest.mark.parametrize("key", [check.key for check in logic.CHECKS if check.fix])
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


# -- picking meshes ---------------------------------------------------------


def test_meshes_takes_transforms_shapes_and_components(new_scene):
    a, b, c = _cube("a"), _cube("b"), _cube("c")
    shape = cmds.listRelatives(b, shapes=True, fullPath=True)[0]
    joint = cmds.createNode("joint")

    assert logic.meshes([a, shape, f"{c}.vtx[0]", joint, a]) == [a, b, c]


def test_meshes_with_nothing_given_is_every_mesh_in_the_scene(new_scene):
    a, b = _cube("a"), _cube("b")

    assert logic.meshes([]) == [a, b]
