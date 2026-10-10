import sys

import pytest

from kaiju_suite import registry
from kaiju_suite.tools.assembler import logic, products

# Product name -> the utility tool double-clicking its items opens.
UTILITIES = {
    "Joints": "Joint Tool",
    "Mesh": "Mesh Tool",
    "SkinCluster": "SkinCluster Tool",
    "DeltaMush": "DeltaMush Tool",
    "BlendShapes": "BlendShape Tool",
    "Material": "Material Tool",
    "Pose": "Pose Tool",
    "Animation": "Animation Tool",
    "ControlShape": "ControlShape Tool",
    "Rig Module": "Rig Module Editor",
}


def _product(name):
    return next(p for p in products.all_products() if p.name == name)


def test_find_returns_the_tool_with_that_name():
    assert registry.find("Renamer")["name"] == "Renamer"


def test_find_returns_none_for_an_unknown_name():
    assert registry.find("No Such Tool") is None


def test_there_is_no_scene_tool():
    assert registry.find("Scene Tool") is None


def test_utilities_sit_under_the_utilities_menu():
    found = {tool["name"]: tool for tool in registry.discover()}

    for name in UTILITIES.values():
        assert found[name].get("category") == "Utilities", name


def test_discovering_utilities_does_not_load_their_windows():
    registry.discover()

    loaded = [
        name
        for name in sys.modules
        if name.startswith("kaiju_suite.tools.") and name.endswith(".widget") and ".assembler." not in name
    ]
    assert loaded == []


@pytest.mark.parametrize("product_name, utility", sorted(UTILITIES.items()))
def test_each_product_opens_its_utility(product_name, utility):
    tool = logic.utility_for(_product(product_name))

    assert tool["name"] == utility
    assert callable(tool["launch"])


@pytest.mark.parametrize("product_name", ["Script", "Folder", "Separator", "Scene", "Connections"])
def test_scripts_folders_separators_and_scenes_have_no_utility(product_name):
    assert logic.utility_for(_product(product_name)) is None


def test_every_other_product_has_a_utility():
    names = {p.name for p in products.all_products()} - {"Script", "Folder", "Separator", "Scene", "Connections"}

    assert names == set(UTILITIES)


@pytest.mark.parametrize("product_name", sorted(set(UTILITIES) | {"Scene", "Connections"}))
def test_products_with_an_info_window_get_right_click_info(product_name):
    assert logic.has_info(_product(product_name))


@pytest.mark.parametrize("product_name", ["Script", "Folder", "Separator"])
def test_products_without_an_info_window_get_no_right_click_info(product_name):
    assert not logic.has_info(_product(product_name))


# -- opening a utility on an item --------------------------------------------


@pytest.fixture
def fake_utility(monkeypatch):
    """Make every product's utility a recording stand-in; returns the calls."""
    calls = []
    tool = {"name": "Fake", "launch": lambda: calls.append(("launch",))}
    monkeypatch.setattr(logic, "utility_for", lambda product: tool)
    return tool, calls


def test_open_utility_launches_a_tool_that_takes_no_file(fake_utility):
    tool, calls = fake_utility

    logic.open_utility(_product("Mesh"), "a.mesh")

    assert calls == [("launch",)]


def test_open_utility_passes_the_item_to_a_tool_that_opens_files(fake_utility):
    tool, calls = fake_utility
    tool["open"] = lambda path: calls.append(("open", path))

    logic.open_utility(_product("Rig Module"), "L_arm.rig")

    assert calls == [("open", "L_arm.rig")]


def test_open_utility_says_when_the_tool_is_missing(monkeypatch):
    monkeypatch.setattr(logic, "utility_for", lambda product: None)

    with pytest.raises(LookupError) as info:
        logic.open_utility(_product("Mesh"), "a.mesh")
    assert "Mesh Tool" in str(info.value)


def test_rig_module_editor_opens_files():
    tool = registry.find("Rig Module Editor")

    assert callable(tool["open"]) and callable(tool["launch"])
