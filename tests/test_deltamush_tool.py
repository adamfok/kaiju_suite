import pytest
from maya import cmds

from kaiju_suite.tools.deltamush_tool import logic


def _plane(name="body", sx=2):
    plane = cmds.polyPlane(name=name, width=2, height=2, sx=sx, sy=1, constructionHistory=False)[0]
    return cmds.ls(plane, long=True)[0]


def _weights(node, mesh):
    return [round(w, 4) for w in logic.weights(node, mesh)]


def _xs(mesh):
    return [cmds.pointPosition(f"{mesh}.vtx[{v}]", local=True)[0] for v in range(cmds.polyEvaluate(mesh, vertex=True))]


# -- adding -----------------------------------------------------------------


def test_add_starts_with_no_weight(new_scene):
    mesh = _plane()

    nodes = logic.add([mesh])

    assert len(nodes) == 1 and cmds.nodeType(nodes[0]) == "deltaMush"
    assert logic.delta_mushes(mesh) == nodes
    assert _weights(nodes[0], mesh) == [0.0] * 6


def test_add_can_start_fully_weighted(new_scene):
    mesh = _plane()

    node = logic.add([mesh], weight=1.0)[0]

    assert _weights(node, mesh) == [1.0] * 6


def test_add_goes_after_skin(new_scene):
    mesh = _plane()
    joint = cmds.createNode("joint")
    skin = cmds.skinCluster(joint, mesh)[0]

    node = logic.add([mesh])[0]

    history = cmds.ls(cmds.listHistory(mesh), type=["skinCluster", "deltaMush"])
    assert history == [node, skin]


def test_add_is_one_undo_step(new_scene):
    cmds.undoInfo(state=True)
    mesh = _plane()

    logic.add([mesh])
    cmds.undo()

    assert logic.delta_mushes(mesh) == []


def test_paint_attribute_names_the_weights_for_artisan(new_scene):
    node = logic.add([_plane()])[0]

    assert logic.paint_attribute(node) == f"deltaMush.{node}.weights"


# -- editing weights --------------------------------------------------------


def test_set_weights_on_components(new_scene):
    mesh = _plane()
    node = logic.add([mesh])[0]

    logic.set_weights(node, [f"{mesh}.vtx[0]", f"{mesh}.vtx[4]"], 0.5)

    assert _weights(node, mesh) == [0.5, 0, 0, 0, 0.5, 0]


def test_flood(new_scene):
    mesh = _plane()
    node = logic.add([mesh])[0]

    logic.flood(node, mesh, 0.25)

    assert _weights(node, mesh) == [0.25] * 6


def test_invert(new_scene):
    mesh = _plane()
    node = logic.add([mesh])[0]
    logic.set_weights(node, [f"{mesh}.vtx[0]"], 0.25)

    logic.invert(node, mesh)

    assert _weights(node, mesh) == [0.75, 1, 1, 1, 1, 1]


@pytest.mark.parametrize("positive_to_negative", [True, False])
def test_mirror_weights(new_scene, positive_to_negative):
    mesh = _plane()
    node = logic.add([mesh])[0]
    xs = _xs(mesh)
    source = [v for v, x in enumerate(xs) if (x > 0.5 if positive_to_negative else x < -0.5)]
    logic.set_weights(node, [f"{mesh}.vtx[{v}]" for v in source], 0.8)

    logic.mirror_weights(node, mesh, positive_to_negative)

    for v, x in enumerate(xs):
        assert _weights(node, mesh)[v] == (0.8 if abs(x) > 0.5 else 0.0)


def test_affected_vertices(new_scene):
    mesh = _plane()
    node = logic.add([mesh])[0]
    logic.set_weights(node, [f"{mesh}.vtx[1]", f"{mesh}.vtx[5]"], 0.3)

    assert logic.affected(node, mesh) == [f"{mesh}.vtx[1]", f"{mesh}.vtx[5]"]


def test_weight_edits_are_one_undo_step_each(new_scene):
    cmds.undoInfo(state=True)
    mesh = _plane()
    node = logic.add([mesh])[0]
    logic.set_weights(node, [f"{mesh}.vtx[0]"], 0.25)
    before = _weights(node, mesh)

    for edit in (
        lambda: logic.set_weights(node, [f"{mesh}.vtx[2]"], 1),
        lambda: logic.flood(node, mesh, 1),
        lambda: logic.invert(node, mesh),
        lambda: logic.mirror_weights(node, mesh, False),
    ):
        edit()
        assert _weights(node, mesh) != before
        cmds.undo()
        assert _weights(node, mesh) == before


# -- finding ----------------------------------------------------------------


def test_meshes_and_their_delta_mushes(new_scene):
    a, b = _plane("a"), _plane("b")
    node = logic.add([a])[0]

    assert logic.meshes([f"{a}.vtx[0]", b]) == [a, b]
    assert logic.delta_mushes(b) == []
    assert logic.delta_mushes(a) == [node]


def test_components_of_keeps_only_that_meshs_components(new_scene):
    a, b = _plane("a"), _plane("b")
    shape = cmds.listRelatives(a, shapes=True, fullPath=True)[0]
    cmds.select(f"{a}.vtx[0:1]", f"{shape}.f[1]", f"{b}.vtx[2]", b)

    found = logic.components_of(a, cmds.ls(selection=True))

    assert cmds.ls(found, flatten=True) == cmds.ls([f"{a}.vtx[0]", f"{a}.vtx[1]", f"{a}.f[1]"], flatten=True)
