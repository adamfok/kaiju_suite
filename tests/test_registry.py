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


def test_builder_and_outliner_tool_sit_at_the_top_of_the_menu():
    found = {tool["name"]: tool for tool in registry.discover()}

    assert "category" not in found["Builder"]
    assert "category" not in found["Outliner Tool"]


def test_menu_tools_leave_out_tools_marked_menu_false(fake_tools):
    fake_tools("shown", '{"name": "Shown", "launch": show}')
    fake_tools("hidden", '{"name": "Hidden", "launch": show, "menu": False}')

    assert [tool["name"] for tool in registry.menu_tools()] == ["Shown"]
    # Still discovered, so another tool can open it by name.
    assert registry.find("Hidden")["name"] == "Hidden"


def test_run_startup_calls_each_tools_startup_hook_once(fake_tools):
    fake_tools("one", '{"name": "One", "launch": show, "startup": lambda: CALLS.append("one")}')
    fake_tools("two", '{"name": "Two", "launch": show}')
    fake_tools("three", '{"name": "Three", "launch": show, "startup": lambda: CALLS.append("three")}')
    import builtins

    builtins.CALLS = []
    try:
        registry.run_startup()
        assert sorted(builtins.CALLS) == ["one", "three"]
    finally:
        del builtins.CALLS


def test_a_failing_startup_hook_doesnt_stop_the_others(fake_tools):
    fake_tools("bad", '{"name": "Bad", "launch": show, "startup": lambda: 1 / 0}')
    fake_tools("good", '{"name": "Good", "launch": show, "startup": lambda: CALLS.append("good")}')
    import builtins

    builtins.CALLS = []
    try:
        registry.run_startup()
        assert builtins.CALLS == ["good"]
    finally:
        del builtins.CALLS
