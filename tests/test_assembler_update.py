"""Update from Scene: re-publish a data item from the node names in its file,
whatever is selected."""

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import data, products, versions
from kaiju_suite.tools.assembler.products import (
    animation,
    blendshape,
    controlshape,
    deltamush,
    joints,
    material,
    mesh,
    pose,
    skin,
)

UPDATE = "Update from Scene"


class _Tags(data.DataProduct):
    """A made-up data product: saves each selected transform's ``tx``."""

    name = "Tags"
    kind = "tags"
    extension = ".tag"
    order = 901

    def gather(self, selection):
        nodes = cmds.ls(selection, type="transform", long=True)
        if not nodes:
            raise RuntimeError("No transforms selected.")
        return {"tags": [{"name": cmds.ls(n)[0], "tx": cmds.getAttr(f"{n}.tx")} for n in nodes]}

    def apply(self, payload):
        pass

    def nodes(self, payload):
        return [t["name"] for t in payload["tags"]]


class _NoNodes(_Tags):
    """Like :class:`_Tags`, but doesn't say which nodes it was gathered from."""

    name = "NoNodes"
    kind = "nonodes"
    extension = ".nonodes"
    order = 902
    nodes = data.DataProduct.nodes


@pytest.fixture
def tags(monkeypatch):
    extra = [_Tags(), _NoNodes()]
    monkeypatch.setattr(products, "_cache", sorted(products.discover() + extra, key=lambda p: p.order))
    return extra


def _publish(product, tmp_path, *selection, name="item"):
    path = product.create(str(tmp_path), name)
    cmds.select(selection, replace=True)
    versions.publish_action(path).fn()
    cmds.select(clear=True)
    return path


def _update(product, path):
    """Run the right-click entry with nothing selected; returns its message."""
    cmds.select(clear=True)
    (action,) = [a for a in product.actions(path) if a.label == UPDATE]
    message = action.fn()
    assert cmds.ls(selection=True) == []
    return message


def _blocked(product, path, *names):
    """Update from Scene raises naming ``names`` and adds no version."""
    before = len(versions.list_versions(path))
    problems = product.update_problems(path)
    assert problems and all(any(n in p for p in problems) for n in names), problems
    with pytest.raises(RuntimeError) as info:
        _update(product, path)
    for name in names:
        assert name in str(info.value)
    assert len(versions.list_versions(path)) == before


# -- the base class ---------------------------------------------------------


def test_entry_only_for_products_that_name_their_nodes(tags, new_scene, tmp_path):
    with_nodes, without = tags
    cmds.createNode("transform", name="a")
    path = _publish(with_nodes, tmp_path, "a")
    other = _publish(without, tmp_path, "a")
    assert [a.label for a in with_nodes.actions(path)] == [UPDATE]
    assert without.actions(other) == []
    assert not without.can_update


def test_no_entry_on_an_empty_item(tags, tmp_path):
    path = tags[0].create(str(tmp_path), "empty")
    assert tags[0].actions(path) == []
    assert tags[0].update_problems(path)


def test_update_publishes_the_scene_as_the_next_version(tags, new_scene, tmp_path):
    product = tags[0]
    a = cmds.createNode("transform", name="a")
    b = cmds.createNode("transform", name="b")
    path = _publish(product, tmp_path, a, b)
    cmds.setAttr(f"{b}.tx", 5)
    cmds.createNode("transform", name="c")
    cmds.select("c")

    assert product.update_problems(path) == []
    (action,) = product.actions(path)
    assert action.fn() == "Published Tags item.tag v002"
    assert cmds.ls(selection=True) == ["c"]  # the selection doesn't matter, and stays
    assert data.read(path, "tags") == {"tags": [{"name": "a", "tx": 0.0}, {"name": "b", "tx": 5.0}]}

    assert action.fn() == "Published Tags item.tag v002"  # unchanged: no new version


def test_missing_nodes_block_the_update(tags, new_scene, tmp_path):
    product = tags[0]
    for name in ("a", "b", "c"):
        cmds.createNode("transform", name=name)
    path = _publish(product, tmp_path, "a", "b", "c")
    cmds.delete("a", "c")
    assert product.update_problems(path) == ["Missing in the scene: a, c"]
    _blocked(product, path, "a", "c")


def test_ambiguous_names_block_the_update(tags, new_scene, tmp_path):
    product = tags[0]
    cmds.createNode("transform", name="a")
    path = _publish(product, tmp_path, "a")
    grp = cmds.createNode("transform", name="grp")
    cmds.createNode("transform", name="a", parent=grp)
    (problem,) = product.update_problems(path)
    assert problem.startswith("Several nodes are called a") and "|grp|a" in problem
    _blocked(product, path, "a")


def test_resolve_nodes_keeps_components_and_order(new_scene):
    cube = cmds.polyCube(name="box", constructionHistory=False)[0]
    cmds.createNode("transform", name="z")
    paths, problems = data.resolve_nodes(["z", f"{cube}.f[0:1]", "z", "gone"])
    assert paths == ["|z", "|box.f[0:1]"]
    assert problems == ["Missing in the scene: gone"]


# -- each product -----------------------------------------------------------


def test_joints(new_scene, tmp_path):
    cmds.select(clear=True)
    root = cmds.joint(name="root_jnt", position=(0, 0, 0))
    child = cmds.joint(name="child_jnt", position=(0, 2, 0))
    path = _publish(joints.PRODUCT, tmp_path, root)
    assert joints.PRODUCT.nodes(data.read(path, "joints")) == ["root_jnt", "child_jnt"]

    cmds.setAttr(f"{child}.translateY", 7)
    assert _update(joints.PRODUCT, path).endswith("v002")
    records = data.read(path, "joints")["joints"]
    assert [r["name"] for r in records] == ["root_jnt", "child_jnt"]
    assert records[1]["translate"][1] == pytest.approx(7)

    cmds.rename(child, "other_jnt")
    _blocked(joints.PRODUCT, path, "child_jnt")


def test_mesh(new_scene, tmp_path):
    box = cmds.polyCube(name="box", constructionHistory=False)[0]
    path = _publish(mesh.PRODUCT, tmp_path, box)
    cmds.move(0, 3, 0, f"{box}.vtx[0]", relative=True)
    assert _update(mesh.PRODUCT, path).endswith("v002")
    (record,) = data.read(path, "mesh")["meshes"]
    assert record["name"] == "box"
    assert record["points"][0][1] == pytest.approx(-0.5 + 3)

    cmds.delete(box)
    _blocked(mesh.PRODUCT, path, "box")


def test_skin(new_scene, tmp_path):
    cmds.select(clear=True)
    a = cmds.joint(name="a_jnt", position=(0, -2, 0))
    b = cmds.joint(name="b_jnt", position=(0, 2, 0))
    leg = cmds.polyCylinder(name="leg", height=4, constructionHistory=False)[0]
    cluster = cmds.skinCluster(a, b, leg, toSelectedBones=True, name="leg_skin")[0]
    path = _publish(skin.PRODUCT, tmp_path, leg)

    cmds.skinPercent(cluster, f"{leg}.vtx[0]", transformValue=[(a, 0.25), (b, 0.75)])
    assert _update(skin.PRODUCT, path).endswith("v002")
    (record,) = data.read(path, "skin")["meshes"]
    assert record["mesh"] == "leg"
    assert dict((record["influences"][i], w) for i, w in record["weights"][0]) == pytest.approx(
        {"a_jnt": 0.25, "b_jnt": 0.75}
    )

    cmds.rename(leg, "arm")
    _blocked(skin.PRODUCT, path, "leg")


def test_deltamush(new_scene, tmp_path):
    box = cmds.polyCube(name="box", constructionHistory=False)[0]
    node = cmds.deltaMush(box, name="box_dm")[0]
    path = _publish(deltamush.PRODUCT, tmp_path, box)
    cmds.setAttr(f"{node}.smoothingIterations", 17)
    cmds.setAttr(f"{node}.weightList[0].weights[2]", 0.5)
    assert _update(deltamush.PRODUCT, path).endswith("v002")
    (record,) = data.read(path, "deltamush")["deltamush"]
    assert record["smoothingIterations"] == 17
    assert record["weights"] == [[2, 0.5]]

    cmds.rename(box, "crate")
    _blocked(deltamush.PRODUCT, path, "box")


def test_blendshapes(new_scene, tmp_path):
    face = cmds.polyPlane(name="face", subdivisionsX=2, subdivisionsY=2, constructionHistory=False)[0]
    smile = cmds.duplicate(face, name="smile")[0]
    cmds.move(0, 1, 0, f"{smile}.vtx[0]", relative=True)
    node = cmds.blendShape(smile, face, name="faceBS")[0]
    cmds.delete(smile)
    path = _publish(blendshape.PRODUCT, tmp_path, face)
    cmds.setAttr(f"{node}.envelope", 0.5)
    cmds.setAttr(f"{node}.smile", 0.3)
    assert _update(blendshape.PRODUCT, path).endswith("v002")
    (record,) = data.read(path, "blendshape")["blendshapes"]
    assert record["envelope"] == pytest.approx(0.5)
    assert record["targets"][0]["weight"] == pytest.approx(0.3)

    cmds.delete(face)
    _blocked(blendshape.PRODUCT, path, "face")


def test_material_keeps_the_published_faces(new_scene, tmp_path):
    box = cmds.polyCube(name="box", constructionHistory=False)[0]
    other = cmds.polyCube(name="other", constructionHistory=False)[0]
    mat = cmds.shadingNode("lambert", asShader=True, name="red_mat")
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="red_SG")
    cmds.connectAttr(f"{mat}.outColor", f"{sg}.surfaceShader")
    cmds.sets(f"{box}.f[0:1]", forceElement=sg)
    cmds.sets(other, forceElement=sg)
    path = _publish(material.PRODUCT, tmp_path, f"{box}.f[0:1]", other)
    before = data.read(path, "material")
    assert sorted(material.PRODUCT.nodes(before)) == ["box.f[0:1]", "other"]

    cmds.setAttr(f"{mat}.color", 0.9, 0.1, 0.1, type="double3")
    assert _update(material.PRODUCT, path).endswith("v002")
    after = data.read(path, "material")
    assert after["assignments"] == before["assignments"]
    assert '".c"' not in before["network"] and '".c"' in after["network"]  # the new color

    cmds.delete(other)
    _blocked(material.PRODUCT, path, "other")


def test_pose(new_scene, tmp_path):
    ctrl = cmds.createNode("transform", name="arm_ctrl")
    path = _publish(pose.PRODUCT, tmp_path, ctrl)
    cmds.setAttr(f"{ctrl}.translateX", 4)
    assert _update(pose.PRODUCT, path).endswith("v002")
    (record,) = data.read(path, "pose")["nodes"]
    assert record["name"] == "arm_ctrl" and record["attrs"]["translateX"] == 4

    cmds.delete(ctrl)
    _blocked(pose.PRODUCT, path, "arm_ctrl")


def test_animation(new_scene, tmp_path):
    ball = cmds.createNode("transform", name="ball")
    cmds.setKeyframe(ball, attribute="translateY", time=1, value=0)
    path = _publish(animation.PRODUCT, tmp_path, ball)
    cmds.setKeyframe(ball, attribute="translateY", time=10, value=5)
    assert _update(animation.PRODUCT, path).endswith("v002")
    (record,) = data.read(path, "animation")["curves"]
    assert record["node"] == "ball"
    assert [k["time"] for k in record["keys"]] == [1, 10]

    cmds.delete(ball)
    _blocked(animation.PRODUCT, path, "ball")


def test_control_shape(new_scene, tmp_path):
    ctrl = cmds.circle(name="hand_ctrl", constructionHistory=False)[0]
    path = _publish(controlshape.PRODUCT, tmp_path, ctrl)
    before = data.read(path, "controlShape")
    cmds.scale(3, 3, 3, f"{ctrl}.cv[*]")
    assert _update(controlshape.PRODUCT, path).endswith("v002")
    after = data.read(path, "controlShape")
    assert [r["name"] for r in after["controls"]] == ["hand_ctrl"]
    assert after != before

    cmds.rename(ctrl, "foot_ctrl")
    _blocked(controlshape.PRODUCT, path, "hand_ctrl")


def test_every_data_product_in_this_repo_names_its_nodes():
    names = {p.name for p in products.all_products() if isinstance(p, data.DataProduct) and p.can_update}
    assert {
        "Joints",
        "Mesh",
        "SkinCluster",
        "DeltaMush",
        "BlendShapes",
        "Material",
        "Pose",
        "Animation",
        "ControlShape",
    } <= names
