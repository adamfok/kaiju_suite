"""Mesh save/load (kaiju_suite.datatypes.mesh)."""

from maya import cmds

from kaiju_suite.datatypes import mesh


def _cube(name="box"):
    return cmds.polyCube(name=name, constructionHistory=False)[0]


def test_kind_and_extension():
    assert mesh.KIND == "mesh"
    assert mesh.EXTENSION == ".mesh"


def test_gather_then_apply_rebuilds_the_mesh(new_scene):
    cube = _cube()
    cmds.setAttr(f"{cube}.translateY", 3)
    payload = mesh.gather(cmds.ls(cube, long=True))

    cmds.file(new=True, force=True)
    message = mesh.apply(payload)

    assert message == "Created 1 mesh"
    assert cmds.polyEvaluate("box", vertex=True) == 8
    assert cmds.getAttr("box.translateY") == 3
    assert cmds.listRelatives("box", shapes=True) == ["boxShape"]


def test_selection_problems(new_scene):
    assert mesh.selection_problems([]) == ["Nothing selected. Select the meshes to publish."]
    locator = cmds.spaceLocator(name="loc")[0]
    assert mesh.selection_problems(cmds.ls(locator, long=True)) == [
        "Not meshes: loc. Select only meshes to publish."
    ]
    assert mesh.selection_problems(cmds.ls(_cube(), long=True)) == []


def test_describe_and_nodes(new_scene):
    payload = mesh.gather(cmds.ls([_cube("a"), _cube("b")], long=True))
    assert mesh.describe(payload) == ["2 meshes", "a, b"]
    assert mesh.nodes(payload) == ["a", "b"]
