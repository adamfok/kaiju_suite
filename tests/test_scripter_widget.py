"""Scripter's status column icons and row colors.

maya.standalone runs a Qt application without widgets, so the widget module
is loaded off-screen in a separate mayapy process that doesn't start Maya."""

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
from PySide6 import QtGui, QtWidgets
app = QtWidgets.QApplication([])
from kaiju_suite.tools.scripter import logic, widget

def solid_colors(icon):
    image = icon.pixmap(16, 16).toImage().convertToFormat(QtGui.QImage.Format.Format_ARGB32)
    colors = set()
    for y in range(image.height()):
        for x in range(image.width()):
            color = QtGui.QColor.fromRgba(image.pixel(x, y))
            if color.alpha() == 255:
                colors.add(color.getRgb()[:3])
    return sorted(colors)

out = {"icons": {}}
for status in (logic.RAN, logic.FAILED, logic.PAUSED):
    icon = widget.status_icon(status)
    out["icons"][status] = {"null": icon.isNull(), "colors": solid_colors(icon)}
out["none_is_null"] = widget.status_icon(None).isNull()
out["failed_color"] = widget.FAILED_COLOR.getRgb()[:3]
out["breakpoint_row"] = widget.ROW_COLORS[logic.BREAKPOINT].getRgb()[:3]
out["has_status_text"] = hasattr(widget, "STATUS_TEXT")
out["kinds_with_icons"] = sorted(widget.ICONS)
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def probe():
    done = subprocess.run([sys.executable, "-c", _PROBE, SCRIPTS], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    # Maya may print a swig "memory leak" note on exit, after the result.
    return json.loads([line for line in done.stdout.splitlines() if line.startswith("{")][-1])


def test_each_status_has_an_icon(probe):
    for status in ("ran", "failed", "paused"):
        assert not probe["icons"][status]["null"]
    assert probe["none_is_null"]


def test_status_column_shows_icons_not_characters(probe):
    assert not probe["has_status_text"]


def test_failed_icon_matches_the_failed_row_name(probe):
    assert probe["icons"]["failed"]["colors"] == [probe["failed_color"]]


def test_each_status_has_its_own_color(probe):
    colors = [tuple(probe["icons"][s]["colors"][0]) for s in ("ran", "failed", "paused")]
    assert len(set(colors)) == 3
    red, green, blue = probe["icons"]["ran"]["colors"][0]
    assert green > red and green > blue


def test_breakpoint_rows_are_a_dark_red(probe):
    red, green, blue = probe["breakpoint_row"]
    assert red < 110  # darker than it was
    assert red > 2 * green and red > 2 * blue


def test_only_folders_have_an_icon(probe):
    assert probe["kinds_with_icons"] == ["Folder"]
