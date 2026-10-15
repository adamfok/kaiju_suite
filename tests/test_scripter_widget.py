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
# Maya's dark UI: window background 68 grey, tree background 43.
maya_palette = QtGui.QPalette()
maya_palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor(68, 68, 68))
maya_palette.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor(43, 43, 43))
out["row_colors"] = {}
for kind in widget.NEW_KINDS:
    color = widget.row_color(kind, maya_palette)
    out["row_colors"][kind] = color.getRgb()[:3] if color else None
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


def test_new_menu_offers_a_selection_item_with_its_icon(probe):
    assert "Selection" in probe["new_kinds"]
    assert "scripter_selection.svg" in probe["icon_files"]


def test_new_menu_offers_a_pose_item_with_its_icon(probe):
    assert "Pose" in probe["new_kinds"]
    assert "scripter_pose.svg" in probe["icon_files"]


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


def test_folders_have_no_background_color(probe):
    assert probe["row_colors"]["Folder"] is None
    assert probe["row_colors"]["Breakpoint"] == probe["breakpoint_row"]


def test_separator_rows_are_darker_than_the_window_and_tree(probe):
    separator = probe["row_colors"]["Separator"]
    assert separator is not None
    assert max(separator) < 43  # the tree background, itself darker than the window's 68


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
    copied = []
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
new_icons = {}


class RecordingMenu(QtWidgets.QMenu):
    def exec(self, *_):
        actions = self.actions()
        menus.append([a.text() for a in actions] + [s.text() for a in actions if a.menu() for s in a.menu().actions()])
        for a in actions:
            if a.menu() and a.text() == "New":
                for s in a.menu().actions():
                    if not s.isSeparator():
                        new_icons[s.text()] = s.icon().cacheKey() == widget.kind_icon(s.text()).cacheKey()


QtWidgets.QMenu = RecordingMenu
stand.tree.itemAt = lambda pos: item
stand._on_context_menu(stand.tree.rect().center())

print(json.dumps({
    "opened": opened,
    "folder": folder,
    "menu": menus[0] if menus else None,
    "new_icons": new_icons,
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


def test_new_menu_shows_each_kinds_icon(folder_probe):
    # The same icon the item gets in the tree, so the menu previews it.
    assert sorted(folder_probe["new_icons"]) == sorted(
        ["Script", "Folder", "Separator", "Breakpoint", "Import File", "Export File", "Selection", "Joints", "Skin", "Mesh", "NurbsCurve", "Animation", "Pose", "ControlShape", "BlendShapes", "ProximityWrap"]
    )
    assert all(folder_probe["new_icons"].values()), folder_probe["new_icons"]


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


# Selecting an item gives its folder a grey background, so you can tell where
# it lives; the grey moves with the selection.
_PARENT_PROBE = r"""
import json, os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, sys.argv[1])
from PySide6 import QtGui, QtWidgets
app = QtWidgets.QApplication([])
from kaiju_suite.tools.scripter import widget

widget.settings.get = lambda tool, key, default=None: default
widget.settings.set = lambda *a: None

palette = QtGui.QPalette()
palette.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor(43, 43, 43))
tree = widget._Tree(None)
tree.setPalette(palette)


def build():
    tree.clear()
    names = {}
    names["rig"] = QtWidgets.QTreeWidgetItem(tree, ["rig"])
    names["arm.py"] = QtWidgets.QTreeWidgetItem(names["rig"], ["arm.py"])
    names["body"] = QtWidgets.QTreeWidgetItem(tree, ["body"])
    names["legs"] = QtWidgets.QTreeWidgetItem(names["body"], ["legs"])
    names["leg.py"] = QtWidgets.QTreeWidgetItem(names["legs"], ["leg.py"])
    names["top.py"] = QtWidgets.QTreeWidgetItem(tree, ["top.py"])
    return names


def grey(names):
    return sorted(n for n, item in names.items() if item.background(0).style() != widget.QtCore.Qt.BrushStyle.NoBrush)


def select(names, *picked):
    tree.clearSelection()
    for name in picked:
        names[name].setSelected(True)
    return grey(names)


names = build()
out = {
    "arm": select(names, "arm.py"),
    "leg": select(names, "leg.py"),
    "both": select(names, "arm.py", "leg.py"),
    "folder": select(names, "legs"),
    "top": select(names, "top.py"),
    "none": select(names),
}
select(names, "arm.py")
out["color"] = names["rig"].background(widget.NAME).color().getRgb()[:3]
out["all_columns"] = all(names["rig"].background(c) == names["rig"].background(0) for c in range(tree.columnCount()))
# The tree is rebuilt from disk after most actions: selecting in the new tree still works.
names = build()
out["after_rebuild"] = select(names, "leg.py")
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def parent_probe():
    done = subprocess.run([sys.executable, "-c", _PARENT_PROBE, SCRIPTS], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads([line for line in done.stdout.splitlines() if line.startswith("{")][-1])


def test_selecting_an_item_greys_its_folder(parent_probe):
    assert parent_probe["arm"] == ["rig"]
    assert parent_probe["leg"] == ["legs"]  # only its own folder, not the ones above


def test_each_selected_items_folder_is_grey(parent_probe):
    assert parent_probe["both"] == ["legs", "rig"]
    assert parent_probe["folder"] == ["body"]


def test_no_folder_is_grey_for_top_level_or_no_selection(parent_probe):
    assert parent_probe["top"] == []
    assert parent_probe["none"] == []


def test_folder_grey_is_lighter_than_the_tree_across_the_row(parent_probe):
    assert min(parent_probe["color"]) > 43
    assert parent_probe["all_columns"]


def test_folder_grey_works_after_the_tree_is_rebuilt(parent_probe):
    assert parent_probe["after_rebuild"] == ["legs"]


_FOLDER_BOX_PROBE = r"""
import json, os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, sys.argv[1])
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from kaiju_suite.tools.scripter import widget

long_path = "D:/" + "/".join(["a_very_long_folder_name"] * 12)
box = widget.folder_box()
empty = box.minimumSizeHint().width()
box.addItems(["D:/short", long_path])
box.setEditText(long_path)
box.show()
box.showPopup()
app.processEvents()
print(json.dumps({
    "empty": empty,
    "filled": box.minimumSizeHint().width(),
    "hint": box.sizeHint().width(),
    "popup": box.view().minimumWidth(),
    "text": box.fontMetrics().horizontalAdvance(long_path),
}))
"""


@pytest.fixture(scope="module")
def folder_box_probe():
    done = subprocess.run([sys.executable, "-c", _FOLDER_BOX_PROBE, SCRIPTS], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads([line for line in done.stdout.splitlines() if line.startswith("{")][-1])


def test_long_folder_path_does_not_widen_the_path_box(folder_box_probe):
    assert folder_box_probe["filled"] == folder_box_probe["empty"]
    assert folder_box_probe["hint"] < folder_box_probe["text"]


def test_path_box_dropdown_is_wide_enough_for_full_paths(folder_box_probe):
    assert folder_box_probe["popup"] >= folder_box_probe["text"]


_SELECTION_DIALOG_PROBE = r"""
import json, os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, sys.argv[1])
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest
app = QtWidgets.QApplication([])
from kaiju_suite.tools.scripter import items, widget

# A fake scene: what each entry finds, without Maya.
SCENE = {"body_geo": ["body_geo"], "hair_geo": ["hair_geo"], "*_eye_geo": ["L_eye_geo", "R_eye_geo"],
         "new_geo": ["new_geo"]}
items.lookup = lambda entry: (
    [found for name in items._names(entry) for found in SCENE.get(name, [])],
    [name for name in items._names(entry) if not SCENE.get(name)],
)
scene_selection = ["new_geo"]
items.selected_names = lambda: list(scene_selection)
selected = []
widget.cmds.select = lambda objects, replace=True: selected.append(list(objects))
warnings = []
widget._warn = warnings.append
saved = []

entries = [
    {"type": items.SELECTED, "value": ["body_geo", "hair_geo"]},
    {"type": items.PATTERN, "value": "*_eye_geo"},
]
dialog = widget.SelectionDialog(None, "hero", entries, saved.append)
dialog.resize(400, 600)
dialog.show()
app.processEvents()
table = dialog.table
labels = [w.text() for w in dialog.findChildren(QtWidgets.QLabel)]
buttons = [b.text() for b in dialog.findChildren(QtWidgets.QAbstractButton)]

def preview():
    return [dialog.preview.item(i).text() for i in range(dialog.preview.count())]

def row(i):
    return [table.topLevelItem(i).text(c) for c in range(3)]

def click(i):
    QTest.mouseClick(table.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=table.visualItemRect(table.topLevelItem(i)).center())

def actions(menu):
    return [a.text() for a in menu.actions() if not a.isSeparator()]

out = {
    "labels": labels,
    "buttons": buttons,
    "modal": dialog.isModal(),
    "add_buttons": [[b.toolTip(), b.icon().isNull(), b.autoRaise()] for b in dialog.add_buttons],
    "delete_button": [dialog.delete_button.toolTip(), dialog.delete_button.icon().isNull(), dialog.delete_button.isEnabled()],
    "delete_on_the_right": dialog.delete_button.geometry().left() > table.geometry().center().x()
    and dialog.delete_button.geometry().bottom() < table.geometry().top(),
    "rows": [row(0), row(1)],
    "entry_fills": [table.header().sectionResizeMode(c) == QtWidgets.QHeaderView.ResizeMode.Stretch for c in range(3)],
    "no_sideways_scroll": table.horizontalScrollBar().maximum() == 0,
    "columns_fill_the_list": table.header().sectionSize(0) + table.header().sectionSize(1) + table.header().sectionSize(2)
    == table.viewport().width(),
    "preview_header": [
        w for w in (dialog.preview_row.itemAt(i).widget() for i in range(dialog.preview_row.count())) if w
    ] == [dialog.preview_label, dialog.count],
    "all": [preview(), dialog.count.text()],
    "empty_menu": actions(dialog.entry_menu(None)),
    "row_menu": actions(dialog.entry_menu(table.topLevelItem(0))),
    "preview_has_menu": dialog.preview.contextMenuPolicy() == QtCore.Qt.ContextMenuPolicy.CustomContextMenu,
}
table.clearSelection()
SCENE["hair_geo"] = []
click(0)
out["selected_row"] = [preview(), dialog.count.text(), row(0)[2]]
SCENE["hair_geo"] = ["hair_geo"]
click(1)
out["pattern_row"] = [preview(), dialog.count.text(), row(0)[2]]
out["selected_by_clicking_rows"] = list(selected)

# Picking preview rows selects those objects in the scene.
dialog.preview.item(0).setSelected(True)
dialog.preview.item(1).setSelected(True)
out["preview_pick"] = selected[-1]
QTest.mouseDClick(dialog.preview.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=QtCore.QPoint(10, dialog.preview.viewport().height() - 5))
out["select_all"] = [selected[-1], len(dialog.preview.selectedItems())]
selected.append(None)
QTest.mouseDClick(dialog.preview.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=dialog.preview.visualItemRect(dialog.preview.item(0)).center())
out["select_all_on_a_row"] = [selected[-1], len(dialog.preview.selectedItems())]

QTest.mouseClick(table.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=QtCore.QPoint(10, table.viewport().height() - 5))
out["empty_click"] = [len(table.selectedItems()), preview()]

# Double-clicking a Selected row opens a window for its objects; the row
# changes only when that window's OK is pressed.
SCENE["hair_geo"] = []
dialog._edit_row(table.topLevelItem(0), 1)
objects_window = dialog.objects_window
objects_list = objects_window.list
def object_rows():
    return [objects_list.item(i).text() for i in range(objects_list.count())]
out["objects_window"] = {
    "modal": objects_window.isModal(),
    "rows": object_rows(),
    "missing_red": objects_list.item(1).foreground().color().getRgb()[:3] == widget.FAILED_COLOR.getRgb()[:3],
    "buttons": [[b.toolTip(), b.icon().isNull(), b.autoRaise()] for b in objects_window.buttons],
    "has_menu": objects_list.contextMenuPolicy() == QtCore.Qt.ContextMenuPolicy.CustomContextMenu,
    "remove_enabled_with_nothing_picked": objects_window.remove_button.isEnabled(),
    "entries_locked": not table.isEnabled(),
}
objects_list.item(0).setSelected(True)
out["objects_window"]["pick"] = selected[-1]
out["objects_window"]["remove_enabled_with_a_pick"] = objects_window.remove_button.isEnabled()
objects_window.add_selected()
out["objects_window"]["added"] = object_rows()
objects_list.clearSelection()
objects_list.item(0).setSelected(True)
objects_window.remove_selected()
out["objects_window"]["removed"] = object_rows()
out["objects_window"]["row_before_ok"] = row(0)[:2]
objects_window.reject()
out["objects_window"]["after_cancel"] = [row(0), table.isEnabled()]

dialog._edit_row(table.topLevelItem(0), 1)
objects_window = dialog.objects_window
objects_window.replace_with_selected()
out["replaced"] = [objects_window.list.item(i).text() for i in range(objects_window.list.count())]
scene_selection.clear()
objects_window.add_selected()
objects_window.replace_with_selected()
out["nothing_selected_warns"] = len(warnings)
objects_window.accept()
out["repicked"] = [row(0), table.isEnabled()]
SCENE["hair_geo"] = ["hair_geo"]

table.topLevelItem(1).setSelected(True)
out["delete_enabled_with_a_selection"] = dialog.delete_button.isEnabled()
dialog.delete_button.click()
out["after_remove"] = table.topLevelItemCount()
dialog.accept()
out["saved"] = saved

new_pattern = widget.PatternDialog(None)
types = new_pattern.node_type
out["pattern_dialog"] = {
    "types": [types.itemText(i) for i in range(types.count())],
    "default": new_pattern.values(),
}
new_pattern.pattern.setText("  *_geo ")
types.setCurrentText("Geo")
out["pattern_dialog"]["picked"] = new_pattern.values()
out["pattern_dialog"]["editing"] = widget.PatternDialog(None, "*_jnt", "Joint").values()

# The Selection Set picker, and making a new set from the selection.
scene_sets = ["anim_set", "render_set"]
items.scene_sets = lambda: list(scene_sets)
made = []
def create_set(name, members):
    made.append([name, members])
    scene_sets.append(name + "1")
    return name + "1"
items.create_set = create_set
deleted = []
def delete_set(name):
    deleted.append(name)
    scene_sets.remove(name)
items.delete_set = delete_set
asked_names = []
def get_text(*args, **kwargs):
    asked_names.append(kwargs.get("text"))
    return ("new_set", True)
QtWidgets.QInputDialog.getText = staticmethod(get_text)

def names(d):
    return [d.set_list.item(i).text() for i in range(d.set_list.count())]

def click_set(d, name):
    item = d.set_list.findItems(name, QtCore.Qt.MatchFlag.MatchExactly)[0]
    QTest.mouseClick(d.set_list.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=d.set_list.visualItemRect(item).center())
    app.processEvents()

picked_sets = []
set_dialog = widget.SetDialog(None, "render_set", picked_sets.append)
set_dialog.show()
app.processEvents()
set_list = set_dialog.set_list
out["set_dialog"] = {
    "title": set_dialog.windowTitle(),
    "is_list": isinstance(set_list, QtWidgets.QListWidget) and not set_dialog.findChildren(QtWidgets.QComboBox),
    "single": set_list.selectionMode() == QtWidgets.QAbstractItemView.SelectionMode.SingleSelection,
    "sets": names(set_dialog),
    "current": set_dialog.value(),
    "new_button": [set_dialog.new_button.toolTip(), set_dialog.new_button.icon().isNull()],
    "new_icon_is_add_set": set_dialog.new_button.icon().pixmap(16, 16).toImage()
    == widget.icons.same_when_selected(widget.icons.icon("scripter_add_set.svg")).pixmap(16, 16).toImage(),
    "delete_button": [set_dialog.delete_button.toolTip(), set_dialog.delete_button.icon().isNull()],
    "delete_beside_new": set_dialog.layout().itemAt(0).layout().itemAt(1).widget() is set_dialog.delete_button,
    "button_above_list": set_dialog.layout().itemAt(0).layout().itemAt(0).widget() is set_dialog.new_button
    and set_dialog.layout().itemAt(1).widget() is set_list,
}
scene_selection[:] = ["a_geo", "b_geo"]
set_dialog.new_button.click()
out["set_dialog"]["made"] = made
out["set_dialog"]["after_new"] = [names(set_dialog), set_dialog.value()]
scene_selection.clear()
before = len(warnings)
set_dialog.new_button.click()
out["set_dialog"]["nothing_selected_warns"] = [len(warnings) - before, len(made)]
out["set_dialog"]["missing_current_kept"] = widget.SetDialog(None, "gone_set", print).value()
out["set_dialog"]["default_name"] = asked_names[0]

# A missing set's name is the default for a new set, which then replaces it.
missing = widget.SetDialog(None, "gone_set", print)
scene_selection[:] = ["a_geo"]
QtWidgets.QInputDialog.getText = staticmethod(lambda *a, **k: (asked_names.append(k.get("text")), (k.get("text"), True))[1])
def create_named(name, members):
    scene_sets.append(name)
    return name
items.create_set = create_named
missing.new_button.click()
out["set_dialog"]["missing_default"] = asked_names[-1]
out["set_dialog"]["after_remaking_missing"] = [names(missing), missing.value()]
scene_sets.remove("gone_set")
scene_selection.clear()
items.create_set = create_set

# Sets made or deleted in the scene show up when a set is clicked.
scene_sets.append("fx_set")
scene_sets.remove("render_set")
click_set(set_dialog, "new_set1")
out["set_dialog"]["reread_on_click"] = [names(set_dialog), set_dialog.value()]
scene_sets.remove("anim_set")
click_set(set_dialog, "anim_set")
out["set_dialog"]["clicked_set_gone"] = [names(set_dialog), set_dialog.value()]
scene_sets.insert(0, "anim_set")
click_set(set_dialog, "fx_set")

click_set(set_dialog, "anim_set")
set_dialog.delete_button.click()
out["set_dialog"]["deleted"] = [deleted, names(set_dialog)]
set_list.clearSelection()
out["set_dialog"]["delete_enabled_with_no_pick"] = set_dialog.delete_button.isEnabled()
set_dialog.accept()
out["set_dialog"]["empty_ok_picks_nothing"] = list(picked_sets)

double_picked = []
double = widget.SetDialog(None, None, double_picked.append)
double.show()
app.processEvents()
item = double.set_list.findItems("fx_set", QtCore.Qt.MatchFlag.MatchExactly)[0]
# As a real double-click arrives: a click (the list refills after it), then press and double-click.
where = double.set_list.visualItemRect(item).center()
QTest.mouseClick(double.set_list.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=where)
app.processEvents()
QTest.mousePress(double.set_list.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=where)
QTest.mouseDClick(double.set_list.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=where)
app.processEvents()
out["set_dialog"]["double_click_picks"] = [double_picked, double.isVisible()]

# Adding a set entry opens the picker without blocking Maya; the editor waits.
scene_sets[:] = ["anim_set", "render_set"]
saved2 = []
editor = widget.SelectionDialog(None, "hero", [], saved2.append)
editor._add_set()
set_window = editor.set_window
out["set_window"] = {"modal": set_window.isModal(), "visible": set_window.isVisible(), "editor_locked": not editor.table.isEnabled()}
set_window.set_list.findItems("render_set", QtCore.Qt.MatchFlag.MatchExactly)[0].setSelected(True)
set_window.accept()
out["set_window"]["after_ok"] = [editor.entries, editor.table.isEnabled(), editor.set_window is None]
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def selection_dialog_probe():
    done = subprocess.run(
        [sys.executable, "-c", _SELECTION_DIALOG_PROBE, SCRIPTS], capture_output=True, text=True, timeout=120
    )
    assert done.returncode == 0, done.stderr
    return json.loads([line for line in done.stdout.splitlines() if line.startswith("{")][-1])


def test_selection_editor_has_no_entries_label(selection_dialog_probe):
    assert "Entries" not in selection_dialog_probe["labels"]


def test_selection_editor_shows_selected_entries_as_one_row(selection_dialog_probe):
    assert selection_dialog_probe["rows"] == [
        ["Selected", "body_geo, hair_geo", "2"],
        ["Pattern", "*_eye_geo", "2"],
    ]


def test_selection_editor_does_not_block_maya(selection_dialog_probe):
    assert not selection_dialog_probe["modal"]


def test_selection_editor_text_buttons_are_only_ok_and_cancel(selection_dialog_probe):
    assert sorted(b for b in selection_dialog_probe["buttons"] if b) == ["Cancel", "OK"]


def test_selection_editor_has_icon_buttons_to_add_entries(selection_dialog_probe):
    assert selection_dialog_probe["add_buttons"] == [
        ["Add Selected", False, True],
        ["Add Pattern", False, True],
        ["Add Selection Set", False, True],
    ]


def test_entries_empty_space_menu_adds(selection_dialog_probe):
    assert selection_dialog_probe["empty_menu"] == ["Add Selected", "Add Pattern...", "Add Selection Set..."]


def test_entry_menu_removes(selection_dialog_probe):
    assert selection_dialog_probe["row_menu"] == ["Remove"]
    assert selection_dialog_probe["after_remove"] == 1


def test_selection_preview_is_labelled_with_its_count(selection_dialog_probe):
    assert "Preview:" in selection_dialog_probe["labels"]
    assert selection_dialog_probe["preview_header"]
    assert selection_dialog_probe["all"] == [["body_geo", "hair_geo", "L_eye_geo", "R_eye_geo"], "4 objects"]


def test_clicking_an_entry_refreshes_and_previews_just_it(selection_dialog_probe):
    # The scene changed (hair_geo went away) before the row was clicked: its count updates.
    assert selection_dialog_probe["selected_row"] == [["body_geo"], "1 object", "1"]
    assert selection_dialog_probe["pattern_row"] == [["L_eye_geo", "R_eye_geo"], "2 objects", "2"]
    # Refreshing the preview doesn't touch the scene selection.
    assert selection_dialog_probe["selected_by_clicking_rows"] == []


def test_picking_preview_rows_selects_them_in_the_scene(selection_dialog_probe):
    assert selection_dialog_probe["preview_pick"] == ["L_eye_geo", "R_eye_geo"][:2]


def test_double_clicking_the_preview_selects_all(selection_dialog_probe):
    assert not selection_dialog_probe["preview_has_menu"]
    assert selection_dialog_probe["select_all"] == [["L_eye_geo", "R_eye_geo"], 2]
    assert selection_dialog_probe["select_all_on_a_row"] == [["L_eye_geo", "R_eye_geo"], 2]


def test_clicking_empty_space_previews_everything(selection_dialog_probe):
    assert selection_dialog_probe["empty_click"] == [0, ["body_geo", "hair_geo", "L_eye_geo", "R_eye_geo"]]


def test_double_clicking_a_selected_entry_opens_its_objects(selection_dialog_probe):
    window = selection_dialog_probe["objects_window"]
    assert not window["modal"]
    assert window["rows"] == ["body_geo", "hair_geo"]
    assert window["missing_red"]
    assert window["entries_locked"]


def test_objects_window_has_icon_buttons_instead_of_a_menu(selection_dialog_probe):
    window = selection_dialog_probe["objects_window"]
    assert window["buttons"] == [
        ["Add Selected", False, True],
        ["Replace with Selected", False, True],
        ["Remove", False, True],
    ]
    assert not window["has_menu"]


def test_objects_window_remove_needs_a_picked_object(selection_dialog_probe):
    window = selection_dialog_probe["objects_window"]
    assert not window["remove_enabled_with_nothing_picked"]
    assert window["remove_enabled_with_a_pick"]


def test_objects_window_picks_adds_and_removes(selection_dialog_probe):
    window = selection_dialog_probe["objects_window"]
    assert window["pick"] == ["body_geo"]
    assert window["added"] == ["body_geo", "hair_geo", "new_geo"]
    assert window["removed"] == ["hair_geo", "new_geo"]


def test_objects_window_changes_nothing_until_ok(selection_dialog_probe):
    window = selection_dialog_probe["objects_window"]
    assert window["row_before_ok"] == ["Selected", "body_geo, hair_geo"]
    assert window["after_cancel"] == [["Selected", "body_geo, hair_geo", "1"], True]


def test_objects_window_replace_and_ok(selection_dialog_probe):
    assert selection_dialog_probe["replaced"] == ["new_geo"]
    assert selection_dialog_probe["nothing_selected_warns"] == 2
    assert selection_dialog_probe["repicked"] == [["Selected", "new_geo", "1"], True]


def test_ok_saves_the_entries(selection_dialog_probe):
    assert selection_dialog_probe["saved"] == [[{"type": "selected", "value": ["new_geo"]}]]


def test_pattern_window_has_a_type_dropdown_defaulting_to_any(selection_dialog_probe):
    from kaiju_suite.tools.scripter import items

    window = selection_dialog_probe["pattern_dialog"]
    assert window["types"] == list(items.NODE_TYPES)
    assert window["default"] == ["", "*"]
    assert window["picked"] == ["*_geo", "Geo"]
    assert window["editing"] == ["*_jnt", "Joint"]


def test_delete_button_at_the_top_right_removes_selected_entries(selection_dialog_probe):
    assert selection_dialog_probe["delete_button"] == ["Remove", False, False]
    assert selection_dialog_probe["delete_on_the_right"]
    assert selection_dialog_probe["delete_enabled_with_a_selection"]
    assert selection_dialog_probe["after_remove"] == 1


def test_set_picker_is_titled_selection_set(selection_dialog_probe):
    window = selection_dialog_probe["set_dialog"]
    assert window["title"] == "Selection Set"
    assert window["is_list"] and window["single"]
    assert window["sets"] == ["anim_set", "render_set"]
    assert window["current"] == "render_set"
    assert window["missing_current_kept"] == "gone_set"


def test_set_picker_makes_a_new_set_from_the_selection(selection_dialog_probe):
    window = selection_dialog_probe["set_dialog"]
    assert window["new_button"] == ["New Selection Set from Selected", False]
    assert window["new_icon_is_add_set"]
    assert window["button_above_list"]
    assert window["made"] == [["new_set", ["a_geo", "b_geo"]]]
    assert window["after_new"] == [["anim_set", "render_set", "new_set1"], "new_set1"]
    assert window["nothing_selected_warns"] == [1, 1]


def test_set_picker_deletes_the_picked_set(selection_dialog_probe):
    window = selection_dialog_probe["set_dialog"]
    assert window["delete_button"] == ["Delete Selection Set", False]
    assert window["delete_beside_new"]
    assert window["deleted"] == [["anim_set"], ["new_set1", "fx_set"]]
    assert not window["delete_enabled_with_no_pick"]
    assert window["empty_ok_picks_nothing"] == []


def test_set_picker_does_not_block_maya(selection_dialog_probe):
    window = selection_dialog_probe["set_window"]
    assert not window["modal"] and window["visible"]
    assert window["editor_locked"]
    assert window["after_ok"] == [[{"type": "set", "value": "render_set"}], True, True]


def test_set_list_rereads_the_scene_when_a_set_is_clicked(selection_dialog_probe):
    window = selection_dialog_probe["set_dialog"]
    assert window["reread_on_click"] == [["anim_set", "new_set1", "fx_set"], "new_set1"]
    # Clicking a set someone just deleted: it goes, and nothing is picked.
    assert window["clicked_set_gone"] == [["new_set1", "fx_set"], ""]


def test_double_clicking_a_set_picks_it(selection_dialog_probe):
    assert selection_dialog_probe["set_dialog"]["double_click_picks"] == [["fx_set"], False]


def test_new_set_is_named_after_a_missing_set(selection_dialog_probe):
    window = selection_dialog_probe["set_dialog"]
    assert window["default_name"] == "selection_set"
    assert window["missing_default"] == "gone_set"
    # Making it again lists it once, picked.
    names, picked = window["after_remaking_missing"]
    assert names.count("gone_set") == 1 and picked == "gone_set"


def test_entry_column_fills_the_width(selection_dialog_probe):
    assert selection_dialog_probe["entry_fills"] == [False, True, False]
    assert selection_dialog_probe["no_sideways_scroll"]
    assert selection_dialog_probe["columns_fill_the_list"]


# Copy and Paste: the right-click entries, and Copy then Paste copying the
# items into the clicked folder. Handlers run on a stand-in, as above.
_COPY_PASTE_PROBE = r"""
import json, os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, sys.argv[1])
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from kaiju_suite.tools.scripter import widget

widget.settings.get = lambda tool, key, default=None: default
widget.settings.set = lambda *a: None

root = tempfile.mkdtemp()
folder = os.path.join(root, "rig")
os.mkdir(folder)
script = os.path.join(root, "setup.py")
with open(script, "w") as f:
    f.write("x = 1\n")


class Stand(QtWidgets.QWidget):
    root = root
    runner = None
    copied = []
    attempt = staticmethod(lambda fn: fn())
    populate = staticmethod(lambda: None)
    _delete_selected = staticmethod(lambda: None)
    _run_selected = staticmethod(lambda: None)
    _on_context_menu = widget.ScripterWindow._on_context_menu
    _copy_selected = widget.ScripterWindow._copy_selected
    _paste = widget.ScripterWindow._paste
    _new_target = widget.ScripterWindow._new_target
    _find_item = widget.ScripterWindow._find_item


stand = Stand()
stand.selected = []
stand.selected_paths = lambda: list(stand.selected)
stand.tree = widget._Tree(stand)
folder_item = QtWidgets.QTreeWidgetItem(stand.tree, ["rig"])
folder_item.setData(0, widget.PATH_ROLE, folder)
script_item = QtWidgets.QTreeWidgetItem(stand.tree, ["setup"])
script_item.setData(0, widget.PATH_ROLE, script)

menus = []


class RecordingMenu(QtWidgets.QMenu):
    def exec(self, *_):
        menus.append({a.text(): a.isEnabled() for a in self.actions() if a.text()})


QtWidgets.QMenu = RecordingMenu
stand.tree.itemAt = lambda pos: folder_item

out = {}
stand._on_context_menu(stand.tree.rect().center())
out["menu_nothing_selected"] = menus[-1]

stand.selected = [script]
stand._on_context_menu(stand.tree.rect().center())
out["menu_selected"] = menus[-1]

stand._copy_selected()
out["copied"] = stand.copied
stand._on_context_menu(stand.tree.rect().center())
out["menu_after_copy"] = menus[-1]

# Closing Scripter and opening it again (or on another library) keeps what was copied.
reopened = Stand()
out["copied_after_reopen"] = reopened.copied

stand._paste(folder_item)
out["in_folder"] = sorted(n for n in os.listdir(folder) if not n.startswith("."))
out["original_kept"] = os.path.isfile(script)

print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def copy_paste_probe():
    done = subprocess.run(
        [sys.executable, "-c", _COPY_PASTE_PROBE, SCRIPTS], capture_output=True, text=True, timeout=120
    )
    assert done.returncode == 0, done.stderr
    return json.loads([line for line in done.stdout.splitlines() if line.startswith("{")][-1])


def test_copy_is_offered_only_with_something_selected(copy_paste_probe):
    assert "Copy" not in copy_paste_probe["menu_nothing_selected"]
    assert copy_paste_probe["menu_selected"]["Copy"] is True


def test_paste_is_greyed_until_something_is_copied(copy_paste_probe):
    assert copy_paste_probe["menu_selected"]["Paste"] is False
    assert copy_paste_probe["menu_after_copy"]["Paste"] is True


def test_copy_then_paste_on_a_folder_copies_into_it(copy_paste_probe):
    assert copy_paste_probe["copied"] and copy_paste_probe["copied"][0].endswith("setup.py")
    assert copy_paste_probe["in_folder"] == ["setup.py"]
    assert copy_paste_probe["original_kept"] is True


def test_what_was_copied_survives_reopening_scripter(copy_paste_probe):
    assert copy_paste_probe["copied_after_reopen"] == copy_paste_probe["copied"]


# Double-clicking a data item whose kind has a tool (Skin: the SkinCluster
# Tool) opens it on the item's objects; other data items show their info,
# which a right-click "Info..." also shows.
_DATA_PROBE = r"""
import json, os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, sys.argv[1])
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from kaiju_suite.tools.scripter import widget

root = tempfile.mkdtemp()
paths = {}
for name in ("leg.skin", "skeleton.jnt", "body.mesh", "spine.curve", "rest.pose", "ctrls.ctrl", "shirt.pwrap"):
    paths[name] = os.path.join(root, name)
    open(paths[name], "w").close()

calls = []
widget.items.open_in_tool = lambda path: calls.append(("tool", os.path.basename(path))) or "Selected 1 object"
widget.items.describe = lambda path: calls.append(("describe", os.path.basename(path))) or ["info"]
widget.QtWidgets.QMessageBox.information = staticmethod(lambda *a: calls.append(("box", a[1])))
widget.settings.get = lambda tool, key, default=None: default
widget.settings.set = lambda *a: None
widget.versions.is_versioned = lambda path: False


class Stand(QtWidgets.QWidget):
    root = root
    runner = None
    copied = []
    attempt = staticmethod(lambda fn: fn())
    selected_paths = staticmethod(lambda: [])
    _delete_selected = staticmethod(lambda: None)
    _on_double_click = widget.ScripterWindow._on_double_click
    _on_context_menu = widget.ScripterWindow._on_context_menu
    _show_info = widget.ScripterWindow._show_info


stand = Stand()
stand.status = QtWidgets.QLabel()
stand.tree = widget._Tree(stand)
out = {"double_click": {}, "menus": {}}
for name, path in paths.items():
    item = QtWidgets.QTreeWidgetItem(stand.tree, [name])
    item.setData(0, widget.PATH_ROLE, path)
    calls.clear()
    stand._on_double_click(item, 0)
    out["double_click"][name] = list(calls)

    menus = []

    class RecordingMenu(QtWidgets.QMenu):
        def exec(self, *_):
            menus.append(self.actions())

    real_menu = QtWidgets.QMenu
    QtWidgets.QMenu = RecordingMenu
    stand.tree.itemAt = lambda pos, item=item: item
    stand._on_context_menu(stand.tree.rect().center())
    QtWidgets.QMenu = real_menu
    out["menus"][name] = [a.text() for a in menus[0]]
    calls.clear()
    [info] = [a for a in menus[0] if a.text() == "Info..."]
    info.trigger()
    out.setdefault("info", {})[name] = list(calls)
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def data_probe():
    done = subprocess.run([sys.executable, "-c", _DATA_PROBE, SCRIPTS], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads([line for line in done.stdout.splitlines() if line.startswith("{")][-1])


def test_double_click_on_a_skin_item_opens_the_skincluster_tool(data_probe):
    assert data_probe["double_click"]["leg.skin"] == [["tool", "leg.skin"]]


def test_double_click_on_a_mesh_item_opens_the_mesh_tool(data_probe):
    assert data_probe["double_click"]["body.mesh"] == [["tool", "body.mesh"]]


def test_double_click_on_a_joints_item_opens_the_joint_tool(data_probe):
    assert data_probe["double_click"]["skeleton.jnt"] == [["tool", "skeleton.jnt"]]


def test_double_click_on_a_proximitywrap_item_opens_its_tool(data_probe):
    assert data_probe["double_click"]["shirt.pwrap"] == [["tool", "shirt.pwrap"]]
    assert "Info..." in data_probe["menus"]["shirt.pwrap"]


def test_double_click_on_a_nurbs_curve_item_opens_the_curve_tool(data_probe):
    assert data_probe["double_click"]["spine.curve"] == [["tool", "spine.curve"]]


def test_double_click_on_a_pose_item_opens_the_pose_tool(data_probe):
    assert data_probe["double_click"]["rest.pose"] == [["tool", "rest.pose"]]


def test_double_click_on_a_controlshape_item_opens_the_controlshape_tool(data_probe):
    assert data_probe["double_click"]["ctrls.ctrl"] == [["tool", "ctrls.ctrl"]]


@pytest.mark.parametrize("name", ["leg.skin", "skeleton.jnt", "body.mesh", "spine.curve", "rest.pose", "ctrls.ctrl"])
def test_data_items_have_right_click_info(data_probe, name):
    assert "Info..." in data_probe["menus"][name]
    assert data_probe["info"][name] == [["describe", name], ["box", name]]


# Publish of a Skin item runs QC first: all passing goes straight on to the
# description; problems show a dialog whose Publish Anyway goes on and whose
# Cancel publishes nothing.
_PUBLISH_PROBE = r"""
import json, os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, sys.argv[1])
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from kaiju_suite.core.checks import Check, Problem
from kaiju_suite.tools.scripter import widget

root = tempfile.mkdtemp()
paths = {}
for name in ("leg.skin", "skeleton.jnt"):
    paths[name] = os.path.join(root, name)
    open(paths[name], "w").close()

CHECK = Check("unused", "Unused influences", "No weight.", None)
events = []
qc = {"found": []}
answer = {"value": QtWidgets.QDialog.DialogCode.Accepted}


class FakeCmds:
    @staticmethod
    def ls(*a, **k):
        return ["|leg"]

    @staticmethod
    def inViewMessage(**k):
        events.append(["message", k["assistMessage"]])


class FakeDialog:
    def __init__(self, parent, title, message, found, go_label, on_pick):
        events.append(["dialog", title, message, go_label, [str(p) for _, ps in found for p in ps]])

    def exec(self):
        return answer["value"]


widget.cmds = FakeCmds
widget.QCResultsDialog = FakeDialog
widget.items.selection_problems = lambda kind, sel: []
widget.items.unchanged_since = lambda path, objects: None
widget.items.publish_qc = lambda path, objects: events.append(["qc", os.path.basename(path), objects]) or qc["found"]
widget.items.publish_data = lambda path, objects, description: events.append(["publish", description]) or 2
widget.QtWidgets.QInputDialog.getText = staticmethod(lambda *a: (events.append(["describe"]) or ("fixed", True)))


class Stand(QtWidgets.QWidget):
    root = root
    attempt = staticmethod(lambda fn: fn())
    populate = staticmethod(lambda: None)
    _publish = widget.ScripterWindow._publish
    _publish_source = widget.ScripterWindow._publish_source
    _passes_qc = widget.ScripterWindow._passes_qc


stand = Stand()
out = {}
cases = {
    "passes": ("leg.skin", [(CHECK, [])], None),
    "anyway": ("leg.skin", [(CHECK, [Problem("leg: 1 unused influence: knee", ["knee"])])], QtWidgets.QDialog.DialogCode.Accepted),
    "cancel": ("leg.skin", [(CHECK, [Problem("leg: 1 unused influence: knee", ["knee"])])], QtWidgets.QDialog.DialogCode.Rejected),
    "no_checks": ("skeleton.jnt", [], None),
}
for case, (name, found, choice) in cases.items():
    events.clear()
    qc["found"] = found
    answer["value"] = choice
    stand._publish(paths[name])
    out[case] = list(events)
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def publish_probe():
    done = subprocess.run([sys.executable, "-c", _PUBLISH_PROBE, SCRIPTS], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads([line for line in done.stdout.splitlines() if line.startswith("{")][-1])


def test_publish_with_qc_passing_goes_straight_on(publish_probe):
    assert publish_probe["passes"] == [
        ["qc", "leg.skin", ["|leg"]],
        ["describe"],
        ["publish", "fixed"],
        ["message", "Published leg.skin v002"],
    ]


def test_publish_with_qc_problems_asks_and_publish_anyway_goes_on(publish_probe):
    assert publish_probe["anyway"] == [
        ["qc", "leg.skin", ["|leg"]],
        ["dialog", "QC: leg.skin", "QC found 1 problem in leg.skin.", "Publish Anyway", ["leg: 1 unused influence: knee"]],
        ["describe"],
        ["publish", "fixed"],
        ["message", "Published leg.skin v002"],
    ]


def test_publish_with_qc_problems_then_cancel_publishes_nothing(publish_probe):
    assert publish_probe["cancel"] == [
        ["qc", "leg.skin", ["|leg"]],
        ["dialog", "QC: leg.skin", "QC found 1 problem in leg.skin.", "Publish Anyway", ["leg: 1 unused influence: knee"]],
    ]


def test_publish_of_a_kind_without_checks_shows_no_dialog(publish_probe):
    assert [e[0] for e in publish_probe["no_checks"]] == ["qc", "describe", "publish", "message"]
