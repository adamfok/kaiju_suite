"""Builds the Kaiju menu in Maya's main menu bar from the tool registry."""

import os
import sys

from maya import cmds

import kaiju_suite
from kaiju_suite.core.log import get_logger

log = get_logger(__name__)

MENU_NAME = "kaijuSuiteMenu"
MENU_LABEL = "Kaiju"
ICON_DIR = os.path.normpath(
    os.path.join(os.path.dirname(kaiju_suite.__file__), "..", "..", "icons")
)


def build():
    """(Re)build the menu. Safe to call repeatedly."""
    from kaiju_suite import registry

    remove()
    root = cmds.menu(
        MENU_NAME, label=MENU_LABEL, parent="MayaWindow", tearOff=True
    )

    submenus = {}
    for tool in registry.discover():
        category = tool["category"]
        if category not in submenus:
            submenus[category] = cmds.menuItem(
                label=category, subMenu=True, tearOff=True, parent=root
            )
        kwargs = {
            "label": tool["name"],
            "parent": submenus[category],
            "command": _runner(tool),
            "annotation": tool.get("description", ""),
        }
        icon = tool.get("icon")
        if icon:
            kwargs["image"] = os.path.join(ICON_DIR, icon)
        cmds.menuItem(**kwargs)

    cmds.menuItem(divider=True, parent=root)
    cmds.menuItem(label="Reload Kaiju Suite", parent=root, command=lambda *_: reload())
    cmds.menuItem(
        label=f"v{kaiju_suite.__version__}", parent=root, enable=False
    )
    return root


def remove():
    if cmds.menu(MENU_NAME, exists=True):
        cmds.deleteUI(MENU_NAME, menu=True)


def reload():
    """Drop every kaiju_suite module and rebuild the menu (for development)."""
    for name in list(sys.modules):
        if name == "kaiju_suite" or name.startswith("kaiju_suite."):
            del sys.modules[name]
    from kaiju_suite.ui import menu as fresh

    fresh.build()
    log.info("Kaiju Suite reloaded")


def _runner(tool):
    def run(*_):
        try:
            tool["launch"]()
        except Exception:
            log.exception("Tool '%s' failed", tool["name"])
            cmds.warning(f"Kaiju: '{tool['name']}' failed, see Script Editor.")

    return run
