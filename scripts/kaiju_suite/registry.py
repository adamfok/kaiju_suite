"""Discovers tools under ``kaiju_suite.tools``.

A tool is any sub-package whose ``__init__.py`` defines a ``TOOL`` dict:

    TOOL = {
        "name": "Renamer",          # menu label
        "category": "Utilities",    # sub-menu
        "launch": show,             # callable run from the menu
        "icon": "renamer.png",      # optional, looked up in icons/
        "description": "...",       # optional, used as the menu tooltip
    }

Adding a tool means adding a folder; nothing else needs registering.
"""

import importlib
import pkgutil

from kaiju_suite import tools
from kaiju_suite.core.log import get_logger

log = get_logger(__name__)

REQUIRED_KEYS = ("name", "category", "launch")


def discover():
    """Return a list of valid TOOL dicts, sorted by category then name."""
    found = []
    for info in pkgutil.iter_modules(tools.__path__):
        if not info.ispkg:
            continue
        module_name = f"{tools.__name__}.{info.name}"
        try:
            module = importlib.import_module(module_name)
        except Exception:
            log.exception("Failed to import tool %s", module_name)
            continue

        tool = getattr(module, "TOOL", None)
        if not isinstance(tool, dict):
            continue
        missing = [key for key in REQUIRED_KEYS if key not in tool]
        if missing:
            log.warning("Tool %s is missing %s; skipped", module_name, missing)
            continue
        found.append(tool)

    return sorted(found, key=lambda t: (t["category"], t["name"]))
