"""Republish: publish a data item again from the objects named in its file,
whatever is selected; Select Objects; Republish on a folder."""

import os

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import data, products, republish, versions
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

REPUBLISH = "Republish"
SELECT = "Select Objects"


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


def _action(product, path, label):
    (action,) = [a for a in product.actions(path) if a.label == label]
    return action


def _republish(product, path):
    """Run the right-click entry with nothing selected; returns its message."""
    cmds.select(clear=True)
    message = _action(product, path, REPUBLISH).fn()
    assert cmds.ls(selection=True) == []
    return message


def _blocked(product, path, *names):
    """Republish raises naming ``names`` and adds no version."""
    before = len(versions.list_versions(path))
    problems = product.republish_problems(path)
    assert problems and all(any(n in p for p in problems) for n in names), problems
    assert _action(product, path, REPUBLISH).problems() == problems
    with pytest.raises(RuntimeError) as info:
        _republish(product, path)
    for name in names:
        assert name in str(info.value)
    assert len(versions.list_versions(path)) == before


# -- the base class ---------------------------------------------------------


def test_entries_only_for_products_that_name_their_nodes(tags, new_scene, tmp_path):
    with_nodes, without = tags
    cmds.createNode("transform", name="a")
    path = _publish(with_nodes, tmp_path, "a")
    other = _publish(without, tmp_path, "a")
    assert [a.label for a in with_nodes.actions(path)] == [REPUBLISH, SELECT]
    assert without.actions(other) == []
    assert with_nodes.can_republish and not without.can_republish
    assert with_nodes.republishable(path) and not without.republishable(other)


def test_republish_explains_itself_and_asks_for_a_description(tags, new_scene, tmp_path):
    cmds.createNode("transform", name="a")
    path = _publish(tags[0], tmp_path, "a")
    action = _action(tags[0], path, REPUBLISH)
    assert action.describe
    assert "ignoring the selection" in action.tooltip
    assert action.problems() == []


def test_no_entries_on_an_empty_item(tags, tmp_path):
    path = tags[0].create(str(tmp_path), "empty")
    assert tags[0].actions(path) == []
    assert not tags[0].republishable(path)
    assert tags[0].republish_problems(path)


def test_other_products_cant_republish(tmp_path):
    folder = tmp_path / "f"
    folder.mkdir()
    product = products.product_for(str(folder))
    assert not product.can_republish
    assert not product.republishable(str(folder))


def test_republish_publishes_the_scene_as_the_next_version(tags, new_scene, tmp_path):
    product = tags[0]
    a = cmds.createNode("transform", name="a")
    b = cmds.createNode("transform", name="b")
    path = _publish(product, tmp_path, a, b)
    cmds.setAttr(f"{b}.tx", 5)
    cmds.createNode("transform", name="c")
    cmds.select("c")

    assert product.republish_problems(path) == []
    action = _action(product, path, REPUBLISH)
    assert action.fn() == "Published Tags item.tag v002"
    assert cmds.ls(selection=True) == ["c"]  # the selection doesn't matter, and stays
    assert data.read(path, "tags") == {"tags": [{"name": "a", "tx": 0.0}, {"name": "b", "tx": 5.0}]}

    assert action.fn() == "Published Tags item.tag v002"  # unchanged: no new version


def test_missing_nodes_block_the_republish(tags, new_scene, tmp_path):
    product = tags[0]
    for name in ("a", "b", "c"):
        cmds.createNode("transform", name=name)
    path = _publish(product, tmp_path, "a", "b", "c")
    cmds.delete("a", "c")
    assert product.republish_problems(path) == ["Missing in the scene: a, c"]
    _blocked(product, path, "a", "c")


def test_ambiguous_names_block_the_republish(tags, new_scene, tmp_path):
    product = tags[0]
    cmds.createNode("transform", name="a")
    path = _publish(product, tmp_path, "a")
    grp = cmds.createNode("transform", name="grp")
    cmds.createNode("transform", name="a", parent=grp)
    (problem,) = product.republish_problems(path)
    assert problem.startswith("Several nodes are called a") and "|grp|a" in problem
    _blocked(product, path, "a")


def test_resolve_nodes_keeps_components_and_order(new_scene):
    cube = cmds.polyCube(name="box", constructionHistory=False)[0]
    cmds.createNode("transform", name="z")
    paths, problems = data.resolve_nodes(["z", f"{cube}.f[0:1]", "z", "gone"])
    assert paths == ["|z", "|box.f[0:1]"]
    assert problems == ["Missing in the scene: gone"]


# -- the double-click panel -------------------------------------------------


def test_panel_lists_missing_objects(tags, new_scene, tmp_path):
    product = tags[0]
    for name in ("a", "b"):
        cmds.createNode("transform", name=name)
    path = _publish(product, tmp_path, "a", "b")
    assert not any("Missing" in line for line in product.panel(path).info)

    cmds.delete("b")
    assert "Missing in the scene: b" in product.panel(path).info


def test_panel_of_a_product_without_nodes_doesnt_check_the_scene(tags, new_scene, tmp_path):
    cmds.createNode("transform", name="a")
    path = _publish(tags[1], tmp_path, "a")
    cmds.delete("a")
    assert not any("Missing" in line for line in tags[1].panel(path).info)


# -- Select Objects ---------------------------------------------------------


def test_select_objects_selects_whats_named_in_the_file(tags, new_scene, tmp_path):
    for name in ("a", "b"):
        cmds.createNode("transform", name=name)
    path = _publish(tags[0], tmp_path, "a", "b")
    cmds.createNode("transform", name="c")
    cmds.select("c")
    assert _action(tags[0], path, SELECT).fn() == "Selected 2 objects from item.tag"
    assert cmds.ls(selection=True) == ["a", "b"]


def test_select_objects_reports_missing_and_ambiguous(tags, new_scene, tmp_path):
    for name in ("a", "b", "c"):
        cmds.createNode("transform", name=name)
    path = _publish(tags[0], tmp_path, "a", "b", "c")
    cmds.delete("b")
    grp = cmds.createNode("transform", name="grp")
    cmds.createNode("transform", name="c", parent=grp)

    message = _action(tags[0], path, SELECT).fn()
    assert message.startswith("Selected 1 object from item.tag. ")
    assert "Missing in the scene: b" in message
    assert "Several nodes are called c" in message
    assert cmds.ls(selection=True, long=True) == ["|a"]


def test_select_objects_with_nothing_found_clears_the_selection(tags, new_scene, tmp_path):
    cmds.createNode("transform", name="a")
    path = _publish(tags[0], tmp_path, "a")
    cmds.delete("a")
    cmds.createNode("transform", name="other")
    cmds.select("other")
    message = _action(tags[0], path, SELECT).fn()
    assert message.startswith("Selected 0 objects from item.tag. Missing in the scene: a")
    assert cmds.ls(selection=True) == []


def test_select_objects_keeps_components(new_scene, tmp_path):
    box = cmds.polyCube(name="box", constructionHistory=False)[0]
    mat = cmds.shadingNode("lambert", asShader=True, name="red_mat")
    sg = cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name="red_SG")
    cmds.connectAttr(f"{mat}.outColor", f"{sg}.surfaceShader")
    cmds.sets(f"{box}.f[0:1]", forceElement=sg)
    path = _publish(material.PRODUCT, tmp_path, f"{box}.f[0:1]")
    _action(material.PRODUCT, path, SELECT).fn()
    assert cmds.ls(selection=True) == ["box.f[0:1]"]


# -- Republish on a folder --------------------------------------------------


def _folder(tmp_path, name="build"):
    folder = os.path.join(str(tmp_path), name)
    os.makedirs(folder)
    return folder


def _rels(folder, paths):
    return [os.path.relpath(p, folder).replace(os.sep, "/") for p in paths]


def test_folder_targets_are_published_republishable_items_in_subfolders_too(tags, new_scene, tmp_path):
    cmds.createNode("transform", name="a")
    folder = _folder(tmp_path)
    sub = _folder(folder, "sub")
    _publish(tags[0], folder, "a", name="one")
    _publish(tags[0], sub, "a", name="two")
    tags[0].create(folder, "empty")  # not published: skipped
    _publish(tags[1], folder, "a", name="nonodes")  # can't Republish: skipped
    with open(os.path.join(folder, "notes.py"), "w") as f:
        f.write("pass\n")  # not a data item: skipped

    assert _rels(folder, republish.targets(folder)) == ["one.tag", "sub/two.tag"]
    assert republish.can_republish(folder)
    assert not republish.can_republish(_folder(tmp_path, "nothing"))


def test_folder_problems_are_grouped_by_item(tags, new_scene, tmp_path):
    for name in ("a", "b", "c"):
        cmds.createNode("transform", name=name)
    folder = _folder(tmp_path)
    _publish(tags[0], folder, "a", name="one")
    _publish(tags[0], _folder(folder, "sub"), "b", "c", name="two")
    assert republish.problems(folder) == []

    cmds.delete("b", "c")
    assert republish.problems(folder) == [("sub/two.tag", ["Missing in the scene: b, c"])]
    assert republish.problem_lines(republish.problems(folder)) == [
        "sub/two.tag",
        "    Missing in the scene: b, c",
    ]


def test_folder_republish_republishes_every_item_then_the_folder(tags, new_scene, tmp_path):
    a = cmds.createNode("transform", name="a")
    cmds.createNode("transform", name="b")
    folder = _folder(tmp_path)
    one = _publish(tags[0], folder, "a", name="one")
    two = _publish(tags[0], folder, "b", name="two")
    versions.publish(folder)
    cmds.setAttr(f"{a}.tx", 3)

    with versions.describing("Moved a"):
        message = republish.republish_folder(folder)
    assert message == "Republished 2 items in build: 1 changed, 1 unchanged. Published Folder build v002"
    assert [v.number for v in versions.list_versions(one)] == [2, 1]
    assert [v.number for v in versions.list_versions(two)] == [1]  # unchanged: no new version
    assert data.read(one, "tags")["tags"][0]["tx"] == 3

    latest = versions.list_versions(folder)[0]
    assert latest.number == 2 and latest.description == "Moved a"
    assert versions.list_versions(one)[0].description == "Moved a"


def test_folder_republish_skips_items_with_problems(tags, new_scene, tmp_path):
    a = cmds.createNode("transform", name="a")
    cmds.createNode("transform", name="b")
    folder = _folder(tmp_path)
    one = _publish(tags[0], folder, "a", name="one")
    two = _publish(tags[0], folder, "b", name="two")
    cmds.setAttr(f"{a}.tx", 3)
    cmds.delete("b")

    message = republish.republish_folder(folder)
    assert message.startswith(
        "Republished 1 item in build: 1 changed, 0 unchanged. Skipped 1 with missing objects: two.tag. "
    )
    assert message.endswith("Published Folder build v001")
    assert len(versions.list_versions(one)) == 2
    assert len(versions.list_versions(two)) == 1
    assert versions.list_versions(folder)[0].number == 1


def test_folder_republish_when_the_folder_cant_be_published(tags, new_scene, tmp_path):
    """A skipped item with unpublished edits stops the folder's own publish;
    the items republished before it stay published."""
    a = cmds.createNode("transform", name="a")
    cmds.createNode("transform", name="b")
    folder = _folder(tmp_path)
    one = _publish(tags[0], folder, "a", name="one")
    two = _publish(tags[0], folder, "b", name="two")
    with open(two, "a") as f:
        f.write(" ")  # an unpublished change
    cmds.delete("b")
    cmds.setAttr(f"{a}.tx", 3)

    message = republish.republish_folder(folder)
    assert "Didn't publish build" in message and "two.tag" in message
    assert len(versions.list_versions(one)) == 2
    assert versions.list_versions(folder) == []


def test_folder_republish_with_nothing_to_do_raises(tags, new_scene, tmp_path):
    folder = _folder(tmp_path)
    with pytest.raises(RuntimeError, match="Nothing to republish"):
        republish.republish_folder(folder)


def test_folder_republish_when_every_item_has_problems_raises(tags, new_scene, tmp_path):
    cmds.createNode("transform", name="a")
    folder = _folder(tmp_path)
    one = _publish(tags[0], folder, "a", name="one")
    cmds.delete("a")
    with pytest.raises(RuntimeError, match="Missing in the scene: a"):
        republish.republish_folder(folder)
    assert len(versions.list_versions(one)) == 1
    assert versions.list_versions(folder) == []


# -- each product -----------------------------------------------------------


def test_joints(new_scene, tmp_path):
    cmds.select(clear=True)
    root = cmds.joint(name="root_jnt", position=(0, 0, 0))
    child = cmds.joint(name="child_jnt", position=(0, 2, 0))
    path = _publish(joints.PRODUCT, tmp_path, root)
    assert joints.PRODUCT.nodes(data.read(path, "joints")) == ["root_jnt", "child_jnt"]

    cmds.setAttr(f"{child}.translateY", 7)
    assert _republish(joints.PRODUCT, path).endswith("v002")
    records = data.read(path, "joints")["joints"]
    assert [r["name"] for r in records] == ["root_jnt", "child_jnt"]
    assert records[1]["translate"][1] == pytest.approx(7)

    cmds.rename(child, "other_jnt")
    _blocked(joints.PRODUCT, path, "child_jnt")


def test_mesh(new_scene, tmp_path):
    box = cmds.polyCube(name="box", constructionHistory=False)[0]
    path = _publish(mesh.PRODUCT, tmp_path, box)
    cmds.move(0, 3, 0, f"{box}.vtx[0]", relative=True)
    assert _republish(mesh.PRODUCT, path).endswith("v002")
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
    assert _republish(skin.PRODUCT, path).endswith("v002")
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
    assert _republish(deltamush.PRODUCT, path).endswith("v002")
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
    assert _republish(blendshape.PRODUCT, path).endswith("v002")
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
    assert _republish(material.PRODUCT, path).endswith("v002")
    after = data.read(path, "material")
    assert after["assignments"] == before["assignments"]
    assert '".c"' not in before["network"] and '".c"' in after["network"]  # the new color

    cmds.delete(other)
    _blocked(material.PRODUCT, path, "other")


def test_pose(new_scene, tmp_path):
    ctrl = cmds.createNode("transform", name="arm_ctrl")
    path = _publish(pose.PRODUCT, tmp_path, ctrl)
    cmds.setAttr(f"{ctrl}.translateX", 4)
    assert _republish(pose.PRODUCT, path).endswith("v002")
    (record,) = data.read(path, "pose")["nodes"]
    assert record["name"] == "arm_ctrl" and record["attrs"]["translateX"] == 4

    cmds.delete(ctrl)
    _blocked(pose.PRODUCT, path, "arm_ctrl")


def test_animation(new_scene, tmp_path):
    ball = cmds.createNode("transform", name="ball")
    cmds.setKeyframe(ball, attribute="translateY", time=1, value=0)
    path = _publish(animation.PRODUCT, tmp_path, ball)
    cmds.setKeyframe(ball, attribute="translateY", time=10, value=5)
    assert _republish(animation.PRODUCT, path).endswith("v002")
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
    assert _republish(controlshape.PRODUCT, path).endswith("v002")
    after = data.read(path, "controlShape")
    assert [r["name"] for r in after["controls"]] == ["hand_ctrl"]
    assert after != before

    cmds.rename(ctrl, "foot_ctrl")
    _blocked(controlshape.PRODUCT, path, "hand_ctrl")


def test_exactly_these_products_can_republish():
    names = {p.name for p in products.all_products() if p.can_republish}
    assert names == {
        "Joints",
        "Mesh",
        "SkinCluster",
        "DeltaMush",
        "BlendShapes",
        "Material",
        "Pose",
        "Animation",
        "ControlShape",
    }
