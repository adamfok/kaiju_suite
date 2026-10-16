"""Shared save/load helpers in kaiju_suite.datatypes, used by Builder and the
tools."""

import ast
import os

import pytest
from maya import cmds

from kaiju_suite import datatypes

PACKAGE = os.path.dirname(datatypes.__file__)
FORBIDDEN = ("kaiju_suite.tools", "kaiju_suite.ui", "kaiju_suite.rigging", "PySide6", "PySide2", "shiboken")


def _imports(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module


def test_datatypes_only_import_core():
    files = [os.path.join(PACKAGE, f) for f in os.listdir(PACKAGE) if f.endswith(".py")]
    assert files
    bad = [
        (os.path.basename(f), name)
        for f in files
        for name in _imports(f)
        if any(name == x or name.startswith(x + ".") for x in FORBIDDEN)
    ]
    assert bad == []


def test_require_nodes_names_every_missing_node(new_scene):
    cmds.createNode("transform", name="there")
    datatypes.require_nodes(["there"])
    with pytest.raises(datatypes.MissingNodesError) as info:
        datatypes.require_nodes(["a", "there", "b", "a"], "influences")
    assert str(info.value) == "Missing influences: a, b"


def test_skip_missing_warns_through_maya(new_scene, monkeypatch):
    cmds.createNode("transform", name="there")
    warnings = []
    monkeypatch.setattr(cmds, "warning", warnings.append)
    assert datatypes.skip_missing(["there", "gone"], "meshes") == {"gone"}
    assert warnings == ["Skipped missing meshes: gone"]


def test_meshes_takes_transforms_shapes_and_components(new_scene):
    a = cmds.polyCube(name="a")[0]
    b = cmds.polyCube(name="b")[0]
    cmds.createNode("transform", name="empty")
    found = datatypes.meshes(["b.vtx[0]", "|a|aShape", "empty", "b", "a"])
    assert found == ["|b", "|a"]
    assert datatypes.mesh_shape("a") == "|a|aShape"
    assert datatypes.mesh_shape("empty") is None


def test_plural():
    assert datatypes.plural(1, "mesh", "meshes") == "1 mesh"
    assert datatypes.plural(2, "mesh", "meshes") == "2 meshes"
    assert datatypes.plural(3, "influence") == "3 influences"


def test_save_and_load_go_through_a_datatype_module(new_scene, tmp_path):
    class Names:
        KIND = "names"

        @staticmethod
        def gather(nodes):
            return {"names": [cmds.ls(n)[0] for n in nodes]}

        @staticmethod
        def apply(payload, info=None):
            for name in payload["names"]:
                cmds.createNode("transform", name=name)
            return f"Made {len(payload['names'])}"

    cmds.createNode("transform", name="hero")
    path = datatypes.save(Names, str(tmp_path / "a.names"), ["hero"])
    assert datatypes.read(path, "names") == {"names": ["hero"]}
    cmds.file(new=True, force=True)
    assert datatypes.load(Names, path) == "Made 1"
    assert cmds.objExists("hero")
