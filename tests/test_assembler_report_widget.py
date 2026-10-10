"""Build report window: Step / Status / Time columns and a "..." button that
opens a step's log, as double-clicking does.

maya.standalone runs a Qt application without widgets, so the window is
built off-screen in a separate mayapy process that doesn't start Maya."""

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
from kaiju_suite.tools.assembler import report, report_widget
report.runlog.exists = lambda path: True
# Skipped steps have no log.
results = [report.StepResult("/build/a_ok.py", report.OK, 0.5),
           report.StepResult("/build/b_skipped.py", report.SKIPPED)]
opened = []
window = report_widget.ReportDialog(None, "Build Report", results, opened.append)
table = window.findChild(QtWidgets.QTableWidget)
header = table.horizontalHeader()
table.cellDoubleClicked.emit(1, 0)
skipped_opened = list(opened)
table.cellDoubleClicked.emit(0, 2)
double_clicked = list(opened)
del opened[:]
buttons = [table.cellWidget(row, 3) for row in range(table.rowCount())]
for button in buttons:
    if button.isEnabled():
        button.click()
window.show()
app.processEvents()
opening_width = window.width()
columns_width = sum(max(table.sizeHintForColumn(c), header.sectionSizeHint(c)) for c in range(table.columnCount()))
window.resize(window.width() + 300, window.height())
app.processEvents()
print(json.dumps({
    "headers": [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())],
    "push_buttons": [b.text() for b in window.findChildren(QtWidgets.QPushButton)],
    "log_buttons": [[b.text(), b.isEnabled()] for b in buttons],
    "button_column": header.sectionSize(3),
    "dots_width": buttons[0].fontMetrics().horizontalAdvance("..."),
    "opening_width": opening_width,
    "columns_width": columns_width,
    "table_gap": table.viewport().width() - header.length(),
    "skipped_opened": skipped_opened,
    "double_clicked": double_clicked,
    "clicked": opened,
}))
"""


@pytest.fixture(scope="module")
def probe():
    done = subprocess.run([sys.executable, "-c", _PROBE, SCRIPTS], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_columns_are_step_status_time_and_a_log_button(probe):
    assert probe["headers"] == ["Step", "Status", "Time", ""]


def test_log_button_is_a_narrow_dots_button_greyed_out_without_a_log(probe):
    assert probe["log_buttons"] == [["...", True], ["...", False]]
    assert probe["button_column"] <= probe["dots_width"] + 30


def test_no_copy_or_close_buttons(probe):
    assert probe["push_buttons"] == []


def test_window_opens_about_as_wide_as_its_columns(probe):
    # Room for the scroll bar, frame and margins, but nothing else (such
    # as the totals line under the table) widens it.
    assert probe["opening_width"] <= probe["columns_width"] + 60


def test_table_fills_the_window_when_it_is_widened(probe):
    assert probe["table_gap"] <= 1


def test_log_button_and_double_click_open_the_log_of_a_step_that_has_one(probe):
    assert probe["skipped_opened"] == []
    assert probe["double_clicked"] == ["/build/a_ok.py"]
    assert probe["clicked"] == ["/build/a_ok.py"]
