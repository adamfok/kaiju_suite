"""The ran / failed / paused icons drawn by ``ui.status_icons`` (Builder's
status column).

maya.standalone runs a Qt application without widgets, so the icons are
drawn off-screen in a separate mayapy process that doesn't start Maya."""

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
from kaiju_suite.ui import status_icons

def describe(icon, size):
    image = icon.pixmap(size, size).toImage().convertToFormat(QtGui.QImage.Format.Format_ARGB32)
    w, h = image.width(), image.height()
    alpha = [[QtGui.QColor.fromRgba(image.pixel(x, y)).alpha() for x in range(w)] for y in range(h)]
    solid = [QtGui.QColor.fromRgba(image.pixel(x, y)).getRgb()[:3]
             for y in range(h) for x in range(w) if alpha[y][x] == 255]
    return {
        "null": icon.isNull(),
        "size": [w, h],
        "alpha": alpha,
        "solid_colors": sorted(set(solid)),
        "mirrored": all(alpha[y][x] == alpha[y][w - 1 - x] for y in range(h) for x in range(w)),
        "drawn_sizes": sorted(s.width() for s in icon.availableSizes() if s.width() == s.height()),
    }

out = {}
for name, color in (("check", (110, 190, 110)), ("cross", (225, 85, 85)), ("pause", (232, 197, 71))):
    icon = getattr(status_icons, name)(QtGui.QColor(*color))
    out[name] = {"color": list(color), "16": describe(icon, 16), "32": describe(icon, 32)}
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def probe():
    done = subprocess.run([sys.executable, "-c", _PROBE, SCRIPTS], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


SHAPES = ("check", "cross", "pause")


@pytest.mark.parametrize("shape", SHAPES)
def test_icons_draw_at_tree_size(probe, shape):
    drawn = probe[shape]["16"]
    assert not drawn["null"]
    assert drawn["size"] == [16, 16]


@pytest.mark.parametrize("shape", SHAPES)
def test_icons_are_lines_on_a_clear_background(probe, shape):
    """Only the symbol is painted: no badge or tile behind it."""
    alpha = probe[shape]["16"]["alpha"]
    for x, y in ((0, 0), (15, 0), (0, 15), (15, 15)):
        assert alpha[y][x] == 0
    painted = sum(a > 0 for row in alpha for a in row)
    assert 10 < painted < 16 * 16 // 2


@pytest.mark.parametrize("shape", SHAPES)
def test_icons_are_drawn_in_the_given_color(probe, shape):
    assert probe[shape]["16"]["solid_colors"] == [probe[shape]["color"]]


@pytest.mark.parametrize("shape", SHAPES)
def test_icons_stay_sharp_at_twice_the_size(probe, shape):
    """Maya's UI scaling asks for bigger pixmaps; they're drawn, not stretched."""
    drawn = probe[shape]["32"]
    assert drawn["size"] == [32, 32]
    assert drawn["solid_colors"] == [probe[shape]["color"]]
    assert {16, 24, 32, 48} <= set(drawn["drawn_sizes"])


def test_pause_is_two_bars_with_a_gap(probe):
    alpha = probe["pause"]["16"]["alpha"]
    middle = 8
    assert alpha[middle][7] == 0 and alpha[middle][8] == 0
    assert alpha[middle][5] == 255 and alpha[middle][10] == 255


def test_cross_and_pause_are_symmetric_and_check_is_not(probe):
    assert probe["cross"]["16"]["mirrored"]
    assert probe["pause"]["16"]["mirrored"]
    assert not probe["check"]["16"]["mirrored"]
