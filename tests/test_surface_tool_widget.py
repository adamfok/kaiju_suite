"""The Surface Tool window: a QC tab and a Utilities tab (empty for now).

maya.standalone runs a Qt application without widgets, so the window's
build_ui runs on a stand-in widget off-screen, in a separate mayapy process
that doesn't start Maya (building the real window needs Maya's docking)."""

import json
import os
import subprocess
import sys

import pytest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")

_PROBE = r"""
import json, os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, sys.argv[1])
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from kaiju_suite.core import checks
from kaiju_suite.tools.surface_tool import logic, widget

saved = {}
widget.settings.get = lambda tool, key, default=None: saved.get(key, default)
widget.settings.set = lambda tool, key, value: saved.__setitem__(key, value)
logic.qc_settings = lambda: checks.defaults(logic.QC_CHECKS)
warnings = []
widget._warn = warnings.append
widget.selected = lambda: []

Stand = type("Stand", (QtWidgets.QWidget,), {k: v for k, v in vars(widget.SurfaceToolWindow).items() if not k.startswith("__")})
stand = Stand()
stand.layout = QtWidgets.QVBoxLayout(stand)
stand.build_ui()

[tabs] = stand.findChildren(QtWidgets.QTabWidget)
qc = tabs.widget(0)
out = {
    "title": widget.SurfaceToolWindow.TITLE,
    "tabs": [tabs.tabText(i) for i in range(tabs.count())],
    "qc_checks": [qc.results.topLevelItem(i).text(0) for i in range(qc.results.topLevelItemCount())],
    "qc_hint": qc.status.text(),
    "qc_run_tip": [b for b in qc.findChildren(QtWidgets.QPushButton) if b.text() == "Run Checks"][0].toolTip(),
    "fix_rows": sorted(qc.fix_buttons),
}
[run] = [b for b in qc.findChildren(QtWidgets.QPushButton) if b.text() == "Run Checks"]
run.click()
out["warnings"] = warnings
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def probe():
    done = subprocess.run([sys.executable, "-c", _PROBE, SCRIPTS], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads([line for line in done.stdout.splitlines() if line.startswith("{")][-1])


def test_the_window_is_the_kaiju_surface_tool(probe):
    assert probe["title"] == "Kaiju Surface Tool"


def test_the_window_has_qc_and_utilities_tabs(probe):
    assert probe["tabs"] == ["QC", "Utilities"]


def test_the_qc_tab_lists_the_surface_checks(probe):
    assert probe["qc_checks"] == ["Duplicate name", "Rational CVs", "Trimmed", "Construction history"]


def test_no_check_has_a_fix_button(probe):
    assert probe["fix_rows"] == []


def test_checking_with_no_surfaces_selected_warns(probe):
    assert probe["warnings"] == ["No NURBS surfaces selected. Select the NURBS surfaces to check."]


def test_the_qc_tab_names_what_it_checks(probe):
    assert probe["qc_hint"].startswith("Select surfaces and click Run Checks.")
    assert "selected surfaces." in probe["qc_run_tip"]
