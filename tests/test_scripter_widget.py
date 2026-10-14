"""Scripter's item and status column icons, row colors and folder double-click.

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

def same_when_selected(icon):
    normal = icon.pixmap(16, 16, QtGui.QIcon.Mode.Normal).toImage()
    selected = icon.pixmap(16, 16, QtGui.QIcon.Mode.Selected).toImage()
    return normal == selected


out = {"icons": {}, "selected_changes": []}
for status in (logic.RAN, logic.FAILED, logic.PAUSED):
    icon = widget.status_icon(status)
    out["icons"][status] = {"null": icon.isNull(), "colors": solid_colors(icon)}
out["none_is_null"] = widget.status_icon(None).isNull()
out["failed_color"] = widget.FAILED_COLOR.getRgb()[:3]
out["breakpoint_row"] = widget.ROW_COLORS[logic.BREAKPOINT].getRgb()[:3]
out["has_status_text"] = hasattr(widget, "STATUS_TEXT")
out["kinds_with_icons"] = sorted(widget.ICONS)
out["icon_files"] = sorted(widget.ICONS.values())
out["new_kinds"] = sorted(widget.NEW_KINDS)
out["kind_icons"] = {}
for kind in widget.NEW_KINDS:
    icon = widget.kind_icon(kind)
    image = icon.pixmap(16, 16).toImage()
    drawn = sum(1 for y in range(image.height()) for x in range(image.width()) if QtGui.QColor.fromRgba(image.pixel(x, y)).alpha() > 0)
    out["kind_icons"][kind] = {"null": icon.isNull(), "drawn": drawn}
    if not same_when_selected(icon):
        out["selected_changes"].append(kind)
for status in (logic.RAN, logic.FAILED, logic.PAUSED):
    if not same_when_selected(widget.status_icon(status)):
        out["selected_changes"].append(status)
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


def test_every_item_kind_has_an_icon(probe):
    assert probe["kinds_with_icons"] == probe["new_kinds"]


def test_item_icons_draw_something(probe):
    for kind, icon in probe["kind_icons"].items():
        assert not icon["null"], kind
        assert icon["drawn"] > 10, kind


def test_icons_look_the_same_when_their_row_is_selected(probe):
    # Left to itself, the style tints an icon with the selection color when its
    # row is selected, and Maya's style tints it out of sight.
    assert probe["selected_changes"] == []


def test_item_icons_ship_as_svg(probe):
    import xml.etree.ElementTree as ET

    from kaiju_suite.ui import icons

    for name in probe["icon_files"]:
        path = icons.path(name)
        assert os.path.isfile(path), path
        assert ET.parse(path).getroot().tag == "{http://www.w3.org/2000/svg}svg"


# Double-clicking a folder opens it in the file browser (there's no right-click
# "Open in Explorer"). The window's handlers run on a stand-in widget, since
# building the real window needs Maya's docking.
_FOLDER_PROBE = r"""
import json, os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, sys.argv[1])
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from kaiju_suite.tools.scripter import widget

root = tempfile.mkdtemp()
folder = os.path.join(root, "rig")
os.mkdir(folder)

opened = []
widget._open_in_file_browser = opened.append
# No Maya here: column widths come from their defaults.
widget.settings.get = lambda tool, key, default=None: default
widget.settings.set = lambda *a: None


class Stand(QtWidgets.QWidget):
    root = root
    runner = None
    attempt = staticmethod(lambda fn: fn())
    selected_paths = staticmethod(lambda: [])
    _delete_selected = staticmethod(lambda: None)
    _on_double_click = widget.ScripterWindow._on_double_click
    _on_context_menu = widget.ScripterWindow._on_context_menu


stand = Stand()
stand.tree = widget._Tree(stand)
item = QtWidgets.QTreeWidgetItem(stand.tree, ["rig"])
item.setData(0, widget.PATH_ROLE, folder)

stand._on_double_click(item, 0)

menus = []


class RecordingMenu(QtWidgets.QMenu):
    def exec(self, *_):
        actions = self.actions()
        menus.append([a.text() for a in actions] + [s.text() for a in actions if a.menu() for s in a.menu().actions()])


QtWidgets.QMenu = RecordingMenu
stand.tree.itemAt = lambda pos: item
stand._on_context_menu(stand.tree.rect().center())

print(json.dumps({
    "opened": opened,
    "folder": folder,
    "menu": menus[0] if menus else None,
    "expands_on_double_click": stand.tree.expandsOnDoubleClick(),
}))
"""


@pytest.fixture(scope="module")
def folder_probe():
    done = subprocess.run([sys.executable, "-c", _FOLDER_PROBE, SCRIPTS], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads([line for line in done.stdout.splitlines() if line.startswith("{")][-1])


def test_double_click_opens_a_folder_in_the_file_browser(folder_probe):
    assert folder_probe["opened"] == [folder_probe["folder"]]


def test_double_click_does_not_also_expand_or_collapse(folder_probe):
    assert folder_probe["expands_on_double_click"] is False


def test_folder_menu_has_no_open_in_explorer(folder_probe):
    assert folder_probe["menu"] is not None
    assert "Rename" in folder_probe["menu"]
    assert "Open in Explorer" not in folder_probe["menu"]


# Right-clicking the column header shows a menu that hides or shows the Type
# column; the choice is remembered, so a new tree starts the same way.
_HEADER_PROBE = r"""
import json, os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, sys.argv[1])
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from kaiju_suite.tools.scripter import widget

saved = {}
widget.settings.get = lambda tool, key, default=None: saved.get(key, default)
widget.settings.set = lambda tool, key, value: saved.__setitem__(key, value)

menus = []


class RecordingMenu(QtWidgets.QMenu):
    def exec(self, *_):
        menus.append(self)


widget.QtWidgets.QMenu = RecordingMenu

tree = widget._Tree(None)
out = {"policy_custom": tree.header().contextMenuPolicy() == widget.QtCore.Qt.ContextMenuPolicy.CustomContextMenu}
out["hidden_at_start"] = tree.isColumnHidden(widget.TYPE)
tree.header().customContextMenuRequested.emit(tree.header().rect().center())
type_action = [a for a in menus[-1].actions() if a.text() == "Type"][0]
out["menu"] = [a.text() for a in menus[-1].actions()]
out["checked_before"] = type_action.isChecked()
type_action.trigger()
out["hidden_after_untick"] = tree.isColumnHidden(widget.TYPE)
out["new_tree_hidden"] = widget._Tree(None).isColumnHidden(widget.TYPE)

tree.header().customContextMenuRequested.emit(tree.header().rect().center())
type_action = [a for a in menus[-1].actions() if a.text() == "Type"][0]
out["checked_when_hidden"] = type_action.isChecked()
type_action.trigger()
out["hidden_after_tick"] = tree.isColumnHidden(widget.TYPE)
out["new_tree_hidden_again"] = widget._Tree(None).isColumnHidden(widget.TYPE)

# On screen, hiding a column resizes it to 0: that mustn't be saved as its width.
shown = widget._Tree(None)
shown.resize(400, 300)
shown.show()
app.processEvents()
shown.setColumnWidth(widget.TYPE, 140)
shown._set_column_shown("Type", widget.TYPE, False)
app.processEvents()
out["saved_widths_while_hidden"] = saved["version_type_widths"]
reopened = widget._Tree(None)
reopened._set_column_shown("Type", widget.TYPE, True)
out["width_after_reopen"] = reopened.columnWidth(widget.TYPE)
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def header_probe():
    done = subprocess.run([sys.executable, "-c", _HEADER_PROBE, SCRIPTS], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads([line for line in done.stdout.splitlines() if line.startswith("{")][-1])


def test_type_column_shows_by_default(header_probe):
    assert header_probe["policy_custom"]
    assert header_probe["hidden_at_start"] is False


def test_header_menu_toggles_the_type_column(header_probe):
    assert header_probe["menu"] == ["Type"]
    assert header_probe["checked_before"] is True
    assert header_probe["hidden_after_untick"] is True
    assert header_probe["checked_when_hidden"] is False
    assert header_probe["hidden_after_tick"] is False


def test_type_column_choice_is_remembered(header_probe):
    assert header_probe["new_tree_hidden"] is True
    assert header_probe["new_tree_hidden_again"] is False


def test_hiding_type_keeps_its_saved_width(header_probe):
    assert header_probe["saved_widths_while_hidden"] == "60,140"
    assert header_probe["width_after_reopen"] == 140
