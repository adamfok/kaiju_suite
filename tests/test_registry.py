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
