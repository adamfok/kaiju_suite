"""ui.qc_tab: the QC tab shared by the datatype tools (SkinCluster Tool first).

maya.standalone runs a Qt application without widgets, so the tab is built
off-screen in a separate mayapy process that doesn't start Maya."""

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
from kaiju_suite.core.checks import Check, Problem, defaults
from kaiju_suite.ui import qc_tab

CHECKS = (
    Check("count", "Too many", "Over the limit.", None, {"limit": 4}),
    Check("tiny", "Tiny", "Below the threshold.", None, {"threshold": 0.001}),
    Check("clean", "Clean", "Never finds anything.", None),
)
settings = defaults(CHECKS)
changes, picks = [], []
found = [
    (CHECKS[0], [Problem("body: 2 vertices", ["body.vtx[0:1]"]), "plain text"]),
    (CHECKS[1], []),
    (CHECKS[2], []),
]

def rows(tree):
    return [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]

# The options window: record what it's opened with, and answer it.
opened = []
answer = {"values": None}


class FakeOptions:
    def __init__(self, parent, check, values):
        opened.append([check.key, values])

    def exec(self):
        return QtWidgets.QDialog.DialogCode.Accepted if answer["values"] is not None else QtWidgets.QDialog.DialogCode.Rejected

    def values(self):
        return answer["values"]


real_options = qc_tab.QCOptionsDialog
qc_tab.QCOptionsDialog = FakeOptions

tab = qc_tab.QCTab(CHECKS, settings, lambda *a: changes.append(list(a)), lambda: found, picks.append)
tree = tab.results
out = {
    "checkboxes": len(tab.findChildren(QtWidgets.QCheckBox)),
    "spins_in_tab": len(tab.findChildren(QtWidgets.QSpinBox) + tab.findChildren(QtWidgets.QDoubleSpinBox)),
    "buttons": [b.text() for b in tab.findChildren(QtWidgets.QPushButton)],
    "rows_before": [(r.text(0), r.toolTip(0), r.childCount()) for r in rows(tree)],
    "button_above_list": tab.layout().indexOf(tab.findChildren(QtWidgets.QPushButton)[0]) < tab.layout().indexOf(tree),
    "expands_on_double_click": tree.expandsOnDoubleClick(),
}
option_buttons = {r.text(0): tree.itemWidget(r, 1) for r in rows(tree)}
out["columns"] = tree.columnCount()
out["option_buttons"] = {
    name: None if button is None else [type(button).__name__, button.icon().isNull(), button.toolTip()]
    for name, button in option_buttons.items()
}
answer["values"] = {"limit": 9}
tree.itemDoubleClicked.emit(rows(tree)[0], 0)
out["double_click_opens"] = list(opened)
answer["values"] = None
option_buttons["Too many"].click()
answer["values"] = {"limit": 6}
option_buttons["Too many"].click()
option_buttons["Too many"].click()
option_buttons["Tiny"].click()
out["opened"] = list(opened)
out["changes"] = changes
out["tooltip_after"] = rows(tree)[0].toolTip(0)

[run] = [b for b in tab.findChildren(QtWidgets.QPushButton) if b.text() == "Run Checks"]
out["run_style_before"] = run.styleSheet()
run.click()
out["run_style_failed"] = run.styleSheet()
out["heads"] = [r.text(0) for r in rows(tree)]
out["expanded"] = [r.isExpanded() for r in rows(tree)]
out["children"] = [rows(tree)[0].child(i).text(0) for i in range(rows(tree)[0].childCount())]
out["tooltip_after_run"] = rows(tree)[0].toolTip(0)
out["status"] = tab.status.text()
tree.itemClicked.emit(rows(tree)[0].child(0), 0)
tree.itemClicked.emit(rows(tree)[0].child(1), 0)
tree.itemClicked.emit(rows(tree)[0], 0)
out["picks"] = [[str(p), list(getattr(p, "select", []))] for p in picks]

failed = qc_tab.QCTab(CHECKS, settings, lambda *a: None, lambda: None, picks.append)
[run] = [b for b in failed.findChildren(QtWidgets.QPushButton) if b.text() == "Run Checks"]
before = failed.status.text()
run.click()
out["status_after_failed_run"] = failed.status.text() == before

# All passing turns the button green; a run that can't happen keeps its colour.
outcome = {"found": [(c, []) for c in CHECKS]}
passing = qc_tab.QCTab(CHECKS, settings, lambda *a: None, lambda: outcome["found"], picks.append)
[run] = [b for b in passing.findChildren(QtWidgets.QPushButton) if b.text() == "Run Checks"]
run.click()
out["run_style_passed"] = run.styleSheet()
outcome["found"] = None
run.click()
out["run_style_after_no_run"] = run.styleSheet()
out["colors"] = [qc_tab.PASS_BUTTON_COLOR, qc_tab.FAIL_BUTTON_COLOR]

# The real options window: a spin box per option, OK and Cancel.
real = real_options(None, CHECKS[1], {"threshold": 0.002})
spins = real.findChildren(QtWidgets.QDoubleSpinBox)
out["real_title"] = real.windowTitle()
out["real_spins"] = [(s.prefix(), s.value()) for s in spins]
form = real.findChild(QtWidgets.QFormLayout)
out["real_form"] = [
    [form.itemAt(i, QtWidgets.QFormLayout.ItemRole.LabelRole).widget().text(),
     type(form.itemAt(i, QtWidgets.QFormLayout.ItemRole.FieldRole).widget()).__name__]
    for i in range(form.rowCount())
]
out["real_buttons"] = [b.text() for b in real.findChildren(QtWidgets.QPushButton)]
spins[0].setValue(0.01)
out["real_values"] = real.values()
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def probe():
    done = subprocess.run([sys.executable, "-c", _PROBE, SCRIPTS], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads([line for line in done.stdout.splitlines() if line.startswith("{")][-1])


def test_checks_have_no_on_off_toggles(probe):
    assert probe["checkboxes"] == 0


def test_the_button_is_run_checks_above_the_list(probe):
    assert probe["buttons"] == ["Run Checks"]
    assert probe["button_above_list"] is True


def test_the_list_shows_every_check_before_running_with_its_options_in_the_tooltip(probe):
    assert probe["rows_before"] == [
        ["Too many", "Over the limit.\nLimit: 4", 0],
        ["Tiny", "Below the threshold.\nThreshold: 0.001", 0],
        ["Clean", "Never finds anything.", 0],
    ]


def test_options_are_not_in_the_tab(probe):
    assert probe["spins_in_tab"] == 0


def test_double_click_expands_a_check_and_does_not_open_options(probe):
    assert probe["expands_on_double_click"] is True
    assert probe["double_click_opens"] == []


def test_checks_with_options_have_an_options_button_on_the_right(probe):
    assert probe["columns"] == 3
    assert probe["option_buttons"] == {
        "Too many": ["QToolButton", False, "Options..."],
        "Tiny": ["QToolButton", False, "Options..."],
        "Clean": None,
    }


def test_the_options_button_opens_the_options(probe):
    # Cancelled, then OK with 6 (opened with 6 the next time), then Tiny's.
    assert probe["opened"] == [
        ["count", {"limit": 4}],
        ["count", {"limit": 4}],
        ["count", {"limit": 6}],
        ["tiny", {"threshold": 0.001}],
    ]


def test_ok_in_the_options_reports_the_changed_options(probe):
    assert probe["changes"] == [["count", "limit", 6]]
    assert probe["tooltip_after"] == "Over the limit.\nLimit: 6"
    assert probe["tooltip_after_run"] == "Over the limit.\nLimit: 6"


def test_the_options_window_has_a_spin_box_per_option(probe):
    assert probe["real_title"] == "Tiny Options"
    assert probe["real_spins"] == [["", 0.002]]
    assert probe["real_form"] == [["Threshold", "QDoubleSpinBox"]]
    assert probe["real_buttons"] == ["OK", "Cancel"]
    assert probe["real_values"] == {"threshold": 0.01}


def test_running_puts_each_checks_problems_under_it_collapsed(probe):
    assert probe["heads"] == ["Too many: 2 found", "Tiny: OK", "Clean: OK"]
    assert probe["children"] == ["body: 2 vertices", "plain text"]
    assert probe["expanded"] == [False, False, False]
    assert probe["status"] == "2 problem(s) found."


def test_clicking_a_problem_passes_it_on_with_what_to_select(probe):
    assert probe["picks"] == [["body: 2 vertices", ["body.vtx[0:1]"]], ["plain text", []]]


def test_a_run_that_fails_leaves_the_tab_as_it_was(probe):
    assert probe["status_after_failed_run"] is True


# The dialog Builder shows when QC finds problems before publishing.
_DIALOG_PROBE = r"""
import json, os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, sys.argv[1])
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from kaiju_suite.core.checks import Check, Problem
from kaiju_suite.ui import qc_tab

CHECKS = (Check("count", "Too many", "Over.", None), Check("clean", "Clean", "Never.", None))
found = [(CHECKS[0], [Problem("body: 2 vertices", ["body.vtx[0:1]"])]), (CHECKS[1], [])]
picks = []
out = {}
for press in ("Publish Anyway", "Cancel"):
    dialog = qc_tab.QCResultsDialog(None, "QC: leg.skin", "1 problem found in leg.skin.", found, "Publish Anyway", picks.append)
    buttons = [b for b in dialog.findChildren(QtWidgets.QPushButton)]
    out["buttons"] = [b.text() for b in buttons]
    out["title"] = dialog.windowTitle()
    labels = [l.text() for l in dialog.findChildren(QtWidgets.QLabel)]
    out["labels"] = labels
    tree = dialog.results
    out["heads"] = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
    tree.itemClicked.emit(tree.topLevelItem(0).child(0), 0)
    [button] = [b for b in buttons if b.text() == press]
    button.click()
    out[press] = dialog.result() == QtWidgets.QDialog.DialogCode.Accepted
out["picks"] = [list(p.select) for p in picks]
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def dialog_probe():
    done = subprocess.run([sys.executable, "-c", _DIALOG_PROBE, SCRIPTS], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads([line for line in done.stdout.splitlines() if line.startswith("{")][-1])


def test_results_dialog_lists_the_results_under_its_message(dialog_probe):
    assert dialog_probe["title"] == "QC: leg.skin"
    assert "1 problem found in leg.skin." in dialog_probe["labels"]
    assert dialog_probe["heads"] == ["Too many: 1 found", "Clean: OK"]


def test_results_dialog_has_the_go_ahead_button_then_cancel_at_the_bottom(dialog_probe):
    assert dialog_probe["buttons"] == ["Publish Anyway", "Cancel"]
    assert dialog_probe["Publish Anyway"] is True
    assert dialog_probe["Cancel"] is False


def test_clicking_a_problem_in_the_dialog_selects_it(dialog_probe):
    assert dialog_probe["picks"] == [["body.vtx[0:1]"], ["body.vtx[0:1]"]]


def test_run_checks_starts_uncoloured(probe):
    assert probe["run_style_before"] == ""


def test_run_checks_turns_red_when_a_check_finds_problems(probe):
    passed, failed = probe["colors"]
    assert failed in probe["run_style_failed"] and passed not in probe["run_style_failed"]


def test_run_checks_turns_green_when_every_check_passes(probe):
    passed, failed = probe["colors"]
    assert passed in probe["run_style_passed"] and failed not in probe["run_style_passed"]


def test_run_checks_keeps_its_colour_when_it_could_not_run(probe):
    assert probe["run_style_after_no_run"] == probe["run_style_passed"]


# Checks with a fix get a Fix button on their row once a run finds something.
_FIX_PROBE = r"""
import json, os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, sys.argv[1])
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from kaiju_suite.core.checks import Check, defaults
from kaiju_suite.ui import qc_tab

CHECKS = (
    Check("frozen", "Unfrozen", "Not frozen.", None, fix=lambda nodes: None),
    Check("ngons", "N-gons", "Too many sides.", None),
    Check("names", "Shape name", "Bad shape name.", None, fix=lambda nodes: None),
)
results = {"now": [(CHECKS[0], ["a: not frozen"]), (CHECKS[1], ["a: 1 face"]), (CHECKS[2], [])]}
fixed = []

def on_fix(check):
    fixed.append(check.key)
    results["now"] = [(CHECKS[0], []), (CHECKS[1], ["a: 1 face"]), (CHECKS[2], [])]
    return results["now"]

tab = qc_tab.QCTab(CHECKS, defaults(CHECKS), lambda *a: None, lambda: results["now"], lambda p: None, on_fix=on_fix)
tree = tab.results

def fix_buttons():
    out = {}
    for i in range(tree.topLevelItemCount()):
        row = tree.topLevelItem(i)
        button = tree.itemWidget(row, 2)
        out[row.text(0).split(":")[0]] = (
            None if button is None or button.isHidden()
            else [type(button).__name__, button.icon().isNull(), button.toolTip()]
        )
    return out

out = {"before": fix_buttons(), "columns": tree.columnCount()}
[run] = [b for b in tab.findChildren(QtWidgets.QPushButton) if b.text() == "Run Checks"]
run.click()
out["after_run"] = fix_buttons()
[fix] = [b for b in tab.fix_buttons.values() if not b.isHidden()]
out["fix_icon_file"] = qc_tab.FIX_ICON
fix.click()
out["fixed"] = fixed
out["after_fix"] = fix_buttons()
out["heads_after_fix"] = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def fix_probe():
    done = subprocess.run([sys.executable, "-c", _FIX_PROBE, SCRIPTS], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads([line for line in done.stdout.splitlines() if line.startswith("{")][-1])


def test_no_fix_buttons_before_a_run(fix_probe):
    assert fix_probe["columns"] == 3
    assert fix_probe["before"] == {"Unfrozen": None, "N-gons": None, "Shape name": None}


def test_a_fix_button_only_where_a_fixable_check_found_something(fix_probe):
    assert fix_probe["after_run"] == {
        "Unfrozen": ["QToolButton", False, "Fix what Unfrozen found, as one undo step, then run the checks again."],
        "N-gons": None,
        "Shape name": None,
    }


def test_the_fix_button_is_the_wrench_icon(fix_probe):
    assert fix_probe["fix_icon_file"] == "qc_fix.svg"


def test_fix_fixes_then_shows_the_fresh_results(fix_probe):
    assert fix_probe["fixed"] == ["frozen"]
    assert fix_probe["heads_after_fix"] == ["Unfrozen: OK", "N-gons: 1 found", "Shape name: OK"]
    assert fix_probe["after_fix"] == {"Unfrozen": None, "N-gons": None, "Shape name": None}
