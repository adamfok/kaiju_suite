"""The Publish description prompt and the Versions window (the changelog).

maya.standalone runs a Qt application without widgets, so the windows are
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
from kaiju_suite.tools.assembler import versions, versions_widget
from kaiju_suite.tools.assembler.products import Action

out = {}

# -- the prompt
prompt = versions_widget.DescriptionDialog(None, "Publish spine.jnt")
edit = prompt.findChild(QtWidgets.QLineEdit)
ok = prompt.ok_button
out["ok_when_empty"] = ok.isEnabled()
edit.setText("   ")
out["ok_when_blank"] = ok.isEnabled()
edit.setText("  Fixed the knee  ")
out["ok_with_text"] = ok.isEnabled()
out["description"] = prompt.description()
edit.setText("")
out["empty_description"] = prompt.description()
out["placeholder"] = edit.placeholderText()
out["prompt_title"] = prompt.windowTitle()
filled = versions_widget.DescriptionDialog(None, "Publish rig", "a.py v002, removed b.py")
out["prefilled"] = filled.findChild(QtWidgets.QLineEdit).text()
out["prefilled_ok"] = filled.ok_button.isEnabled()

# -- the Versions window
restored, compared, built = [], [], []
long_text = "A very long description " * 6


def make(can_compare=True):
    def changelog():
        built.append(1)
        rows = [
            versions.ChangelogRow(3, "v003", "2026-10-12 10:00", long_text, True, None),
            versions.ChangelogRow(2, "v002", "2026-10-11 09:00", versions.NO_DESCRIPTION, False,
                                  Action("Restore v002", lambda: None)),
            versions.ChangelogRow(1, "v001", "2026-10-10 08:00", "First", False,
                                  Action("Restore v001", lambda: None, "Lose changes?")),
        ]
        return versions.Changelog("Current: v003 (3 versions)", rows, can_compare)
    return changelog


window = versions_widget.VersionsDialog(None, "Versions of spine.jnt", make(), restored.append, compared.append)
table = window.findChild(QtWidgets.QTableWidget)
buttons = {b.text(): b for b in window.findChildren(QtWidgets.QPushButton)}
out["headers"] = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
out["cells"] = [[table.item(r, c).text() for c in range(table.columnCount())] for r in range(table.rowCount())]
out["description_tooltip"] = table.item(0, 2).toolTip()
out["labels"] = [l.text() for l in window.findChildren(QtWidgets.QLabel)]
out["buttons"] = sorted(buttons)
out["nothing_selected"] = [buttons["Restore"].isEnabled(), buttons["Compare"].isEnabled()]
table.selectRow(0)
out["current_selected"] = [buttons["Restore"].isEnabled(), buttons["Compare"].isEnabled()]
table.selectRow(2)
out["old_selected"] = [buttons["Restore"].isEnabled(), buttons["Compare"].isEnabled()]
builds_before = len(built)
buttons["Restore"].click()
buttons["Compare"].click()
out["restored"] = [a.label for a in restored]
out["compared"] = compared
out["rebuilt_after_restore"] = len(built) > builds_before

plain = versions_widget.VersionsDialog(None, "Versions of rig", make(can_compare=False), restored.append, compared.append)
compare_button = [b for b in plain.findChildren(QtWidgets.QPushButton) if b.text() == "Compare"]
out["compare_hidden"] = all(b.isHidden() for b in compare_button)
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def probe():
    done = subprocess.run([sys.executable, "-c", _PROBE, SCRIPTS], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


# -- the prompt -------------------------------------------------------------------


def test_prompt_description_is_optional(probe):
    assert probe["ok_when_empty"] is True
    assert probe["ok_when_blank"] is True
    assert probe["ok_with_text"] is True
    assert probe["empty_description"] == ""


def test_prompt_hints_what_an_empty_description_shows(probe):
    assert probe["placeholder"] == "(no description)"


def test_prompt_trims_the_description(probe):
    assert probe["description"] == "Fixed the knee"
    assert probe["prompt_title"] == "Publish spine.jnt"


def test_prompt_can_start_with_a_suggestion(probe):
    assert probe["prefilled"] == "a.py v002, removed b.py"
    assert probe["prefilled_ok"] is True


# -- the Versions window ----------------------------------------------------------


def test_versions_window_lists_version_date_and_description(probe):
    assert probe["headers"] == ["Version", "Date", "Description"]
    assert [row[:2] for row in probe["cells"]] == [
        ["v003 (current)", "2026-10-12 10:00"],
        ["v002", "2026-10-11 09:00"],
        ["v001", "2026-10-10 08:00"],
    ]
    assert probe["cells"][1][2] == "(no description)"
    assert probe["cells"][2][2] == "First"


def test_long_descriptions_show_whole_on_hover(probe):
    assert probe["description_tooltip"] == probe["cells"][0][2]
    assert probe["description_tooltip"].startswith("A very long description")


def test_versions_window_shows_the_summary(probe):
    assert "Current: v003 (3 versions)" in probe["labels"]


def test_restore_and_compare_act_on_the_selected_version(probe):
    assert probe["buttons"] == ["Compare", "Restore"]
    assert probe["nothing_selected"] == [False, False]
    # The current version is already in the file: nothing to restore or compare.
    assert probe["current_selected"] == [False, False]
    assert probe["old_selected"] == [True, True]
    assert probe["restored"] == ["Restore v001"]
    assert probe["compared"] == [1]


def test_versions_window_refreshes_after_a_restore(probe):
    assert probe["rebuilt_after_restore"] is True


def test_compare_is_hidden_when_the_item_cant_be_compared(probe):
    assert probe["compare_hidden"] is True
