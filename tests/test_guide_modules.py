"""Guide modules (kaiju_suite.rigging.guides): the registry, the
GuideModule base class and the Chain guide module."""

import ast
import os

import pytest
from maya import cmds

from kaiju_suite.rigging import guides
from kaiju_suite.rigging.guides import planar_chain
from kaiju_suite.rigging.guides.guide_module import GuideError, GuideModule

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
    root = os.path.dirname(guides.__file__)
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
    chain = guides.get_guide_module("chain")
    assert chain.name == "Chain Guide"
    assert chain in guides.all_guide_modules()
    assert all(isinstance(m, GuideModule) for m in guides.all_guide_modules())


def test_get_rejects_an_unknown_guide_module():
    with pytest.raises(LookupError, match="Unknown guide module 'nope' \\(known: .*chain"):
        guides.get_guide_module("nope")


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


# -- Chain ----------------------------------------------------------------------


def test_chain_default_layout_is_a_buildable_chain(new_scene):
    chain = guides.get_guide_module("chain")
    layout = chain.default_layout("L_arm")
    assert layout["name"] == "L_arm" and (layout["aim"], layout["up"]) == ("x", "y")
    assert len(layout["guides"]) == 3
    assert chain.problems(layout) == []
    group = chain.build(layout)
    assert chain.layout(group) == layout


def test_chain_default_layout_falls_back_to_chain_for_a_name_that_cant_name_nodes():
    assert guides.get_guide_module("chain").default_layout("2 arms")["name"] == "chain"


def test_chain_problems(new_scene):
    chain = guides.get_guide_module("chain")
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
    assert guides.get_guide_module("chain").layout(group) == {
        **L_ARM,
        "guides": [[2.0, 10.0, 0.0], [7.0, 9.0, -1.0]],
        "up_guide": [5.0, 10.0, -5.0],
    }


def test_chain_describe_nodes_and_fields():
    chain = guides.get_guide_module("chain")
    assert chain.describe(L_ARM) == ["L_arm: 2 guides, aim x, up -z"]
    assert chain.nodes(L_ARM) == ["L_arm_guides_grp"]
    five = dict(L_ARM, guides=[[0, 0, 0]] * 5)
    assert chain.fields(five) == {"name": "L_arm", "count": 3, "aim": "x", "up": "-z"}


def test_chain_mirrored_flips_across_x_and_reverses_its_axes():
    chain = guides.get_guide_module("chain")
    assert chain.mirrorable
    assert chain.mirrored(L_ARM) == {
        "name": "R_arm", "aim": "-x", "up": "z", "guides": [[-2, 10, 0], [-7, 9, -1]], "up_guide": [-5, 10, -5],
    }
    assert chain.mirrored(chain.mirrored(L_ARM)) == L_ARM
    unsided = {"name": "tail", "aim": "-y", "up": "x", "guides": [[0, 5, -2], [0, 2, -8]], "up_guide": [3, 4, -5]}
    assert chain.mirrored(unsided)["name"] == "tail_mirrored"
    assert chain.mirrored(unsided)["up"] == "-x"
