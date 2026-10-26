"""Smoke check, run inside the test Maya by kaiju_ui_agent.run_file.

The Kaiju menu lists every menu tool, and every tool opens its window
without errors, warnings or dialogs. Takes a screenshot of each window.
"""

import kaiju_suite
from kaiju_suite import registry
from kaiju_suite.ui import menu

import maya_ui


def _menu_labels(menu_path):
    labels = []
    for item in cmds.menu(menu_path, query=True, itemArray=True) or []:
        path = f"{menu_path}|{item}"
        if cmds.menuItem(path, query=True, divider=True):
            continue
        if cmds.menuItem(path, query=True, subMenu=True):
            labels += _menu_labels(path)
        else:
            labels.append(cmds.menuItem(path, query=True, label=True))
    return labels


with ui.step("Kaiju menu lists every tool"):
    found = [
        label for label in _menu_labels(menu.MENU_NAME)
        if label not in ("Reload Kaiju Suite", f"v{kaiju_suite.__version__}")
    ]
    missing, extra = maya_ui.compare_menu([t["name"] for t in registry.menu_tools()], found)
    if missing or extra:
        raise AssertionError(f"missing from the menu: {missing}; in the menu but not a tool: {extra}")

for tool in registry.discover():
    with ui.step(f"Open {tool['name']}"):
        window = ui.open_tool(tool["name"])
        ui.screenshot(window, tool["name"])
        ui.close_tool(window)
