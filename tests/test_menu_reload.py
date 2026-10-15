"""Kaiju ▸ Reload Kaiju Suite: drops every kaiju_suite module and clears
Python's import caches before importing them again.

Without clearing the caches, switching kaiju_suite-dev to another worktree
(dev/use-worktree.ps1) and reloading can keep the old folder's file list,
so a module that is there reads as missing ("No module named
kaiju_suite.tools.joint_tool.widget").

Reload builds Maya menus, so it runs in a separate mayapy process with the
menu commands stubbed out."""

import json
import os
import subprocess
import sys

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")

_PROBE = r"""
import importlib, json, sys
sys.path.insert(0, sys.argv[1])
from maya import cmds

cmds.menu = lambda *a, **k: "kaiju_menu"
cmds.menuItem = lambda *a, **k: "item"
cmds.deleteUI = lambda *a, **k: None

from kaiju_suite.ui import menu

calls = []
real = importlib.invalidate_caches


def recording():
    calls.append("kaiju_suite.ui.menu" in sys.modules)
    real()


importlib.invalidate_caches = recording
menu.reload()
print(json.dumps({"calls": calls, "menu_back": "kaiju_suite.ui.menu" in sys.modules}))
"""


def test_reload_clears_import_caches_after_dropping_the_modules():
    done = subprocess.run([sys.executable, "-c", _PROBE, SCRIPTS], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    out = json.loads([line for line in done.stdout.splitlines() if line.startswith("{")][-1])

    # Called once, after the modules were dropped and before importing them again.
    assert out["calls"] == [False]
    assert out["menu_back"] is True
