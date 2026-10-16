import sys

import pytest

from kaiju_suite import registry

# The tools under Kaiju > Utility Tools, one per Builder data item kind.
UTILITIES = [
    "Animation Tool",
    "BlendShape Tool",
    "ControlShape Tool",
    "Curve Tool",
    "DeltaMush Tool",
    "Joint Tool",
    "Loft Tool",
    "Mesh Tool",
    "Pose Tool",
    "ProximityWrap Tool",
    "SkinCluster Tool",
    "Surface Tool",
]


def test_find_returns_the_tool_with_that_name():
    assert registry.find("Outliner Tool")["name"] == "Outliner Tool"


def test_find_returns_none_for_an_unknown_name():
    assert registry.find("No Such Tool") is None


def test_there_is_no_scene_tool():
    assert registry.find("Scene Tool") is None


# Tools that were removed; nothing should register them any more.
REMOVED = [
    "Rig Validator",
    "Offset & Snap Tool",
    "Attribute Manager",
    "Space Switch Tool",
    "Selection Sets",
    "Wrap Tool",
    "Assembler",
    "Asset Library",
    "Guide Module Editor",
    "Rig Module Editor",
    "Constraint Tool",
    "Deformer Tool",
    "Material Tool",
]


@pytest.mark.parametrize("name", REMOVED)
def test_removed_tools_are_gone(name):
    assert registry.find(name) is None


def test_utilities_sit_under_the_utility_tools_menu():
    found = {tool["name"]: tool for tool in registry.discover()}

    for name in UTILITIES:
        assert found[name].get("category") == "Utility Tools", name


def test_nothing_else_sits_under_the_utility_tools_menu():
    names = {tool["name"] for tool in registry.discover() if tool.get("category") == "Utility Tools"}

    assert names == set(UTILITIES)


def test_discovering_utilities_does_not_load_their_windows():
    registry.discover()

    loaded = [
        name
        for name in sys.modules
        if name.startswith("kaiju_suite.tools.") and name.endswith(".widget")
    ]
    assert loaded == []
