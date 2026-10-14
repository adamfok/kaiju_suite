"""Guide modules (kaiju_suite.rigging.guide_module): the registry, the
GuideModule base class and the Chain guide module."""

import ast
import os

import pytest
from maya import cmds

from kaiju_suite.rigging import guide_module as guide_module_package
from kaiju_suite.rigging.guide_module import all_guide_modules, delete_all_guides, get_guide_module, planar_chain
from kaiju_suite.rigging.guide_module.guide_module import GuideError, GuideModule

FORBIDDEN = ("kaiju_suite.tools", "kaiju_suite.ui", "kaiju_suite.datatypes", "PySide6", "PySide2", "shiboken")
L_ARM = {
    "name": "L_arm",
    "aim": "x",
    "up": "-z",
    "guides": [[2, 10, 0], [7, 9, -1]],
    "up_guide": [5, 10, -5],
}


def _imports(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_guides_never_import_qt_tools_ui_or_datatypes():
    root = os.path.dirname(guide_module_package.__file__)
    files = [os.path.join(d, f) for d, _, names in os.walk(root) for f in names if f.endswith(".py")]
    assert len(files) >= 5
    bad = [
        (os.path.relpath(f, root), name)
        for f in files
        for name in _imports(f)
        if any(name == x or name.startswith(x + ".") for x in FORBIDDEN)
    ]
    assert bad == []


# -- the registry ---------------------------------------------------------------


def test_chain_is_discovered():
    chain = get_guide_module("chain")
    assert chain.name == "Chain Guide"
    assert chain in all_guide_modules()
    assert all(isinstance(m, GuideModule) for m in all_guide_modules())


def test_get_rejects_an_unknown_guide_module():
    with pytest.raises(LookupError, match="Unknown guide module 'nope' \\(known: .*chain"):
        get_guide_module("nope")


# -- the base class -------------------------------------------------------------


class _Dot(GuideModule):
    key = "dot"
    name = "Dot Guide"

    def default_layout(self, name):
        return {"name": name}

    def check(self, layout):
        return [] if layout["name"] else ["Name is required."]

    def create(self, layout):
        return cmds.createNode("transform", name=f"{layout['name']}_guides_grp")

    def layout(self, group):
        return {"name": cmds.ls(group)[0][: -len("_guides_grp")]}


def test_build_checks_then_tags_the_group(new_scene):
    group = _Dot().build({"name": "a"})
    assert cmds.getAttr(f"{group}.kaijuGuideModule") == "dot"
    with pytest.raises(GuideError, match="Can't build Dot Guide:\n- Name is required."):
        _Dot().build({"name": ""})


def test_build_is_one_undo_step(new_scene):
    cmds.undoInfo(state=True)
    cmds.flushUndo()
    _Dot().build({"name": "a"})
    cmds.undo()
    assert not cmds.objExists("a_guides_grp")


def test_build_refuses_a_layout_that_isnt_a_dict(new_scene):
    assert _Dot().problems([]) == ["The Dot Guide layout must be a dictionary."]


def test_rebuild_builds_when_nothing_is_left_to_reuse(new_scene):
    group = _Dot().rebuild({"name": "a"})
    assert cmds.getAttr(f"{group}.kaijuGuideModule") == "dot"


class _Peg(_Dot):
    """A Dot whose guides make one joint, for extract."""

    key = "peg"

    def create(self, layout):
        group = super().create(layout)
        cmds.select(clear=True)
        cmds.joint(name=f"{layout['name']}_jnt")
        return group

    def check_extract(self, group):
        return [] if cmds.objExists(f"{self.layout(group)['name']}_jnt") else ["Its joint is gone."]

    def delete(self, group):
        joint = cmds.ls(f"{self.layout(group)['name']}_jnt", long=True)
        cmds.delete(group)
        return joint


def test_extract_deletes_the_guides_and_returns_the_joints(new_scene):
    group = _Peg().build({"name": "a"})
    assert cmds.ls(_Peg().extract(group)) == ["a_jnt"]
    assert not cmds.objExists("a_guides_grp")


def test_extract_checks_first_and_changes_nothing(new_scene):
    group = _Peg().build({"name": "a"})
    cmds.delete("a_jnt")
    with pytest.raises(GuideError, match="Can't extract the joints of a_guides_grp:\n- Its joint is gone."):
        _Peg().extract(group)
    assert cmds.objExists("a_guides_grp")


def test_extract_is_one_undo_step(new_scene):
    group = _Peg().build({"name": "a"})
    cmds.undoInfo(state=True)
    cmds.flushUndo()
    _Peg().extract(group)
    cmds.undo()
    assert cmds.objExists("a_guides_grp")


def test_restore_refuses_the_guides_of_another_name(new_scene):
    group = _Dot().build({"name": "a"})
    with pytest.raises(GuideError, match="a_guides_grp holds a, not b."):
        _Dot().restore(group, {"name": "b"})


# -- Chain ----------------------------------------------------------------------


def test_chain_default_layout_is_a_buildable_chain(new_scene):
    chain = get_guide_module("chain")
    layout = chain.default_layout("L_arm")
    assert layout["name"] == "L_arm" and (layout["aim"], layout["up"]) == ("x", "y")
    assert len(layout["guides"]) == 3
    assert chain.problems(layout) == []
    group = chain.build(layout)
    assert chain.layout(group) == layout


def test_chain_default_layout_falls_back_to_chain_for_a_name_that_cant_name_nodes():
    assert get_guide_module("chain").default_layout("2 arms")["name"] == "chain"


def test_chain_problems(new_scene):
    chain = get_guide_module("chain")
    assert chain.problems({"name": "a"}) == ["The Chain Guide layout is missing aim, up, guides, up_guide."]
    assert chain.problems(dict(L_ARM, guides="none")) == ["L_arm: guides and up_guide must be [x, y, z] positions."]
    in_line = dict(L_ARM, up_guide=[12, 8, -2])
    assert chain.problems(in_line) == [
        "L_arm: The up guide is in line with the start and end guides; move it to the side."
    ]
    planar_chain.build_at("L_arm", L_ARM["guides"], L_ARM["up_guide"])
    assert chain.problems(L_ARM) == ["Guides already in the scene: L_arm. Delete them first."]


def test_chain_layout_reads_any_planar_chain_group(new_scene):
    group = planar_chain.build_at("L_arm", L_ARM["guides"], L_ARM["up_guide"], aim="x", up="-z")
    assert get_guide_module("chain").layout(group) == {
        **L_ARM,
        "guides": [[2.0, 10.0, 0.0], [7.0, 9.0, -1.0]],
        "up_guide": [5.0, 10.0, -5.0],
    }


def test_chain_describe_nodes_and_fields():
    chain = get_guide_module("chain")
    assert chain.describe(L_ARM) == ["L_arm: 2 guides, aim x, up -z"]
    assert chain.nodes(L_ARM) == ["L_arm_guides_grp"]
    five = dict(L_ARM, guides=[[0, 0, 0]] * 5)
    assert chain.fields(five) == {
        "name": "L_arm", "count": 3, "axes": [{"part": "chain", "label": "", "aim": "x", "up": "-z"}]
    }


def test_chain_mirrored_flips_across_x_and_reverses_its_axes():
    chain = get_guide_module("chain")
    assert chain.mirrorable
    assert chain.mirrored(L_ARM) == {
        "name": "R_arm", "aim": "-x", "up": "z", "guides": [[-2, 10, 0], [-7, 9, -1]], "up_guide": [-5, 10, -5],
    }
    assert chain.mirrored(chain.mirrored(L_ARM)) == L_ARM
    unsided = {"name": "tail", "aim": "-y", "up": "x", "guides": [[0, 5, -2], [0, 2, -8]], "up_guide": [3, 4, -5]}
    assert chain.mirrored(unsided)["name"] == "tail_mirrored"
    assert chain.mirrored(unsided)["up"] == "-x"


def test_chain_rebuild_brings_the_joints_delete_guides_left_back_live(new_scene):
    chain = get_guide_module("chain")
    group = chain.build(L_ARM)
    joints = cmds.ls(planar_chain.joints(group), uuid=True)
    moved = planar_chain.delete_guides(group)
    cmds.xform(moved[-1], worldSpace=True, translation=(8, 8, -1))  # moved after Delete Guides

    group = chain.rebuild(L_ARM)

    assert cmds.ls(planar_chain.joints(group), uuid=True) == joints
    assert cmds.getAttr(f"{group}.kaijuGuideModule") == "chain"
    assert chain.layout(group)["guides"][-1] == [8.0, 8.0, -1.0]  # the guides go where the joints are


def test_chain_rebuild_without_leftovers_builds_the_layout(new_scene):
    chain = get_guide_module("chain")
    group = chain.rebuild(L_ARM)
    assert chain.layout(group)["guides"] == [[2.0, 10.0, 0.0], [7.0, 9.0, -1.0]]


def test_chain_rebuild_is_one_undo_step(new_scene):
    chain = get_guide_module("chain")
    planar_chain.delete_guides(chain.build(L_ARM))
    cmds.undoInfo(state=True)
    cmds.flushUndo()
    before = set(cmds.ls())
    chain.rebuild(L_ARM)
    cmds.undo()
    assert set(cmds.ls()) == before


def test_chain_restore_puts_the_guides_back_and_keeps_the_tag(new_scene):
    chain = get_guide_module("chain")
    group = chain.build(L_ARM)
    planar_chain.build_guides("L_arm", 3)  # another count, and an untagged group
    group = "L_arm_guides_grp"

    group = chain.restore(group, L_ARM)

    assert chain.layout(group) == chain.layout(chain.restore(group, L_ARM))
    assert chain.layout(group)["guides"] == [[2.0, 10.0, 0.0], [7.0, 9.0, -1.0]]
    assert cmds.getAttr(f"{group}.kaijuGuideModule") == "chain"


def test_chain_restore_is_one_undo_step(new_scene):
    chain = get_guide_module("chain")
    group = chain.build(L_ARM)
    found = planar_chain.guides(group)
    cmds.xform(found["chain"][0], worldSpace=True, translation=(1, 1, 1))
    moved = chain.layout(group)
    cmds.undoInfo(state=True)
    cmds.flushUndo()
    chain.restore(group, L_ARM)
    cmds.undo()
    assert chain.layout("L_arm_guides_grp") == moved


def test_chain_extract_cuts_the_joints_loose_where_they_are(new_scene):
    chain = get_guide_module("chain")
    group = chain.build(L_ARM)
    uuids = cmds.ls(planar_chain.joints(group), uuid=True)

    joints = chain.extract(group)

    assert cmds.ls(joints, uuid=True) == uuids
    assert not cmds.objExists("L_arm_guides_grp")
    assert not cmds.getAttr(f"{joints[0]}.tx", lock=True)
    assert planar_chain.leftover_joint("L_arm") is not None  # Rebuild can bring the guides back


def test_chain_check_extract_names_missing_guides(new_scene):
    chain = get_guide_module("chain")
    group = chain.build(L_ARM)
    cmds.delete(planar_chain.guides(group)["up"])
    (problem,) = chain.check_extract(group)
    assert "missing" in problem


# -- delete_all_guides: every guide module's guides to joints ------------------


R_LEG = {"name": "R_leg", "aim": "x", "up": "y", "guides": [[-2, 8, 0], [-2, 0, 0]], "up_guide": [-2, 4, 5]}


def test_delete_all_guides_extracts_every_guide_module(new_scene):
    chain = get_guide_module("chain")
    arm, leg = chain.build(L_ARM), chain.build(R_LEG)
    uuids = {"L_arm": cmds.ls(planar_chain.joints(arm), uuid=True), "R_leg": cmds.ls(planar_chain.joints(leg), uuid=True)}

    extracted = delete_all_guides()

    assert {name: cmds.ls(joints, uuid=True) for name, joints in extracted.items()} == uuids
    assert not cmds.objExists("L_arm_guides_grp")
    assert not cmds.objExists("R_leg_guides_grp")
    assert cmds.ls(type="locator") == []


def test_delete_all_guides_with_no_guides_does_nothing(new_scene):
    cmds.joint(name="loose_jnt")
    assert delete_all_guides() == {}
    assert cmds.objExists("loose_jnt")


def test_delete_all_guides_with_a_broken_one_changes_nothing(new_scene):
    chain = get_guide_module("chain")
    arm = chain.build(L_ARM)
    chain.build(R_LEG)
    cmds.delete(planar_chain.guides(arm)["up"])

    with pytest.raises(GuideError, match="L_arm_guides_grp"):
        delete_all_guides()

    assert cmds.objExists("L_arm_guides_grp")
    assert cmds.objExists("R_leg_guides_grp")


def test_delete_all_guides_refuses_an_unknown_guide_module(new_scene):
    group = _Dot().build({"name": "a"})
    cmds.setAttr(f"{group}.kaijuGuideModule", "nope", type="string")
    get_guide_module("chain").build(L_ARM)

    with pytest.raises(GuideError, match="a_guides_grp: Unknown guide module 'nope'"):
        delete_all_guides()

    assert cmds.objExists("L_arm_guides_grp")


def test_delete_all_guides_is_one_undo_step(new_scene):
    chain = get_guide_module("chain")
    chain.build(L_ARM)
    chain.build(R_LEG)
    cmds.undoInfo(state=True)
    cmds.flushUndo()
    delete_all_guides()
    cmds.undo()
    assert cmds.objExists("L_arm_guides_grp") and cmds.objExists("R_leg_guides_grp")
