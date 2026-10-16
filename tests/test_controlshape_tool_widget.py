"""The ControlShape Tool window: a QC tab and a Utilities tab.

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
from kaiju_suite.tools.controlshape_tool import logic, widget

saved = {}
widget.settings.get = lambda tool, key, default=None: saved.get(key, default)
widget.settings.set = lambda tool, key, value: saved.__setitem__(key, value)
logic.qc_settings = lambda: checks.defaults(logic.QC_CHECKS)
logic.preset_names = lambda library=None: []
widget.color_rgb = lambda index: (0.5, 0.5, 0.5)  # needs Maya's color table
warnings = []
widget._warn = warnings.append
widget.selected = lambda: []

Stand = type(
    "Stand", (QtWidgets.QWidget,), {k: v for k, v in vars(widget.ControlShapeToolWindow).items() if not k.startswith("__")}
)
stand = Stand()
stand.layout = QtWidgets.QVBoxLayout(stand)
stand.build_ui()

[tabs] = stand.findChildren(QtWidgets.QTabWidget)
qc, utilities = tabs.widget(0), tabs.widget(1)
out = {
    "tabs": [tabs.tabText(i) for i in range(tabs.count())],
    "qc_checks": [qc.results.topLevelItem(i).text(0) for i in range(qc.results.topLevelItemCount())],
    "utility_boxes": [b.title() for b in utilities.findChildren(QtWidgets.QGroupBox)],
    "utility_labels": [label.text() for label in utilities.findChildren(QtWidgets.QLabel)],
}
[run] = [b for b in qc.findChildren(QtWidgets.QPushButton) if b.text() == "Run Checks"]
run.click()
out["warnings"] = warnings
tabs.setCurrentIndex(1)
out["saved_tab"] = saved.get("tab")
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def probe():
    done = subprocess.run([sys.executable, "-c", _PROBE, SCRIPTS], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads([line for line in done.stdout.splitlines() if line.startswith("{")][-1])


def test_the_window_has_a_qc_tab_then_a_utilities_tab(probe):
    assert probe["tabs"] == ["QC", "Utilities"]


def test_the_qc_tab_lists_the_controlshape_checks(probe):
    assert probe["qc_checks"] == [
        "No curve shapes",
        "Shape name mismatch",
        "No color",
        "Duplicate names",
        "Rational curves",
    ]


def test_the_utilities_tab_is_an_empty_placeholder(probe):
    assert probe["utility_boxes"] == []
    assert probe["utility_labels"] == ["No control shape utilities yet."]


def test_checking_with_nothing_selected_warns(probe):
    assert probe["warnings"] == ["Nothing selected. Select the controls to check."]


def test_the_open_tab_is_remembered(probe):
    assert probe["saved_tab"] == 1
