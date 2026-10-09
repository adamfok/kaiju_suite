import sys

import pytest

from kaiju_suite import registry
from kaiju_suite.tools.assembler import logic, products

# Product name -> the utility tool double-clicking its items opens.
UTILITIES = {
    "Scene": "Scene Tool",
    "Joints": "Joint Tool",
    "Mesh": "Mesh Tool",
    "SkinCluster": "SkinCluster Tool",
    "DeltaMush": "DeltaMush Tool",
    "BlendShapes": "BlendShape Tool",
    "Material": "Material Tool",
    "Pose": "Pose Tool",
    "Animation": "Animation Tool",
    "ControlShape": "ControlShape Tool",
}


def _product(name):
    return next(p for p in products.all_products() if p.name == name)


def test_find_returns_the_tool_with_that_name():
    assert registry.find("Renamer")["name"] == "Renamer"


def test_find_returns_none_for_an_unknown_name():
    assert registry.find("No Such Tool") is None


def test_utilities_sit_under_the_utilities_menu():
    found = {tool["name"]: tool for tool in registry.discover()}

    for name in UTILITIES.values():
        assert found[name].get("category") == "Utilities", name


def test_discovering_utilities_does_not_load_their_windows():
    registry.discover()

    loaded = [name for name in sys.modules if name.startswith("kaiju_suite.tools.") and name.endswith("_tool.widget")]
    assert loaded == []


@pytest.mark.parametrize("product_name, utility", sorted(UTILITIES.items()))
def test_each_product_opens_its_utility(product_name, utility):
    tool = logic.utility_for(_product(product_name))

    assert tool["name"] == utility
    assert callable(tool["launch"])


@pytest.mark.parametrize("product_name", ["Script", "Folder"])
def test_scripts_and_folders_have_no_utility(product_name):
    assert logic.utility_for(_product(product_name)) is None


def test_every_other_product_has_a_utility():
    names = {p.name for p in products.all_products()} - {"Script", "Folder"}

    assert names == set(UTILITIES)
