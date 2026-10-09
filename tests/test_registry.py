import sys

import pytest

from kaiju_suite import registry, tools


@pytest.fixture
def fake_tools(tmp_path, monkeypatch):
    """Point the registry at a temporary tools folder; returns a tool writer."""
    monkeypatch.setattr(tools, "__path__", [str(tmp_path)])

    def add(folder, tool_source):
        package = tmp_path / folder
        package.mkdir()
        (package / "__init__.py").write_text(
            f"def show():\n    pass\n\nTOOL = {tool_source}\n"
        )
        return f"{tools.__name__}.{folder}"

    added = []
    yield lambda folder, source: added.append(add(folder, source))
    for name in added:
        sys.modules.pop(name, None)


def test_tool_without_category_is_discovered(fake_tools):
    fake_tools("plain", '{"name": "Plain", "launch": show}')

    assert [tool["name"] for tool in registry.discover()] == ["Plain"]


def test_top_level_tools_sort_before_categories(fake_tools):
    fake_tools("zed", '{"name": "Zed", "launch": show}')
    fake_tools("alpha", '{"name": "Alpha", "launch": show}')
    fake_tools("rig", '{"name": "Aardvark", "category": "Rigging", "launch": show}')

    names = [tool["name"] for tool in registry.discover()]

    assert names == ["Alpha", "Zed", "Aardvark"]


def test_assembler_and_renamer_sit_at_the_top_of_the_menu():
    found = {tool["name"]: tool for tool in registry.discover()}

    assert "category" not in found["Assembler"]
    assert "category" not in found["Renamer"]


def test_menu_tools_leave_out_tools_marked_menu_false(fake_tools):
    fake_tools("shown", '{"name": "Shown", "launch": show}')
    fake_tools("hidden", '{"name": "Hidden", "launch": show, "menu": False}')

    assert [tool["name"] for tool in registry.menu_tools()] == ["Shown"]
    # Still discovered, so the Assembler can open it by name.
    assert registry.find("Hidden")["name"] == "Hidden"


def test_rig_module_editor_is_not_in_the_menu():
    assert "Rig Module Editor" not in [tool["name"] for tool in registry.menu_tools()]
    assert registry.find("Rig Module Editor") is not None
