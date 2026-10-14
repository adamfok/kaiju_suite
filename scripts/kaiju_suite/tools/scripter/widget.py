import functools
import os
import subprocess
import sys

from maya import cmds
from PySide6 import QtCore, QtGui, QtWidgets

from kaiju_suite.core import settings
from kaiju_suite.core.log import get_logger
from kaiju_suite.tools.scripter import items, logic, script_editor, versions, vscode
from kaiju_suite.ui import icons, status_icons
from kaiju_suite.ui.base_window import ToolWindow

log = get_logger(__name__)

PATH_ROLE = QtCore.Qt.ItemDataRole.UserRole

# Columns: Name (fills what's left), Version, Type and the last run's status.
NAME, VERSION, TYPE, STATUS = range(4)
# The columns the user can drag wider or narrower, and their starting widths.
SIZED = (VERSION, TYPE)
DEFAULT_WIDTHS = (60, 90)
STATUS_WIDTH = 28
# Columns the header's right-click menu can hide, by label.
HIDEABLE = {"Type": TYPE}

DISABLED_COLOR = QtGui.QColor(115, 115, 115)
# Version column when the item isn't at its newest version.
OLD_VERSION_COLOR = QtGui.QColor(235, 150, 50)
FAILED_COLOR = QtGui.QColor(225, 85, 85)
RAN_COLOR = QtGui.QColor(110, 190, 110)
PAUSED_COLOR = QtGui.QColor(232, 197, 71)
ROW_COLORS = {logic.BREAKPOINT: QtGui.QColor(80, 28, 28)}
# Separator rows are the tree's background darkened by this (percent), so
# they read as dividers darker than the window in any Maya UI color scheme.
SEPARATOR_DARKER = 150
# The folder of each selected item is the tree's background lightened by this
# (percent), so you can tell at a glance where the selection lives.
PARENT_LIGHTER = 150
STATUS_ICONS = {
    logic.RAN: (status_icons.check, RAN_COLOR),
    logic.FAILED: (status_icons.cross, FAILED_COLOR),
    logic.PAUSED: (status_icons.pause, PAUSED_COLOR),
}
STATUS_TIPS = {logic.RAN: "Ran", logic.PAUSED: "Paused here. Right-click > Continue to run the rest."}
# Each item kind's icon in the module's icons/ folder.
ICONS = {
    logic.SCRIPT: "scripter_script.svg",
    logic.FOLDER: "scripter_folder.svg",
    logic.SEPARATOR: "scripter_separator.svg",
    logic.BREAKPOINT: "scripter_breakpoint.svg",
    logic.IMPORT_FILE: "scripter_import_file.svg",
    logic.EXPORT_FILE: "scripter_export_file.svg",
    logic.JOINTS: "scripter_joints.svg",
    logic.SKIN: "scripter_skin.svg",
    logic.MESH: "scripter_mesh.svg",
}
# The right-click New menu, in order.
NEW_KINDS = (
    logic.SCRIPT,
    logic.FOLDER,
    logic.SEPARATOR,
    logic.BREAKPOINT,
    logic.IMPORT_FILE,
    logic.EXPORT_FILE,
    logic.JOINTS,
    logic.SKIN,
    logic.MESH,
)
# Dividers in the New menu after these kinds.
NEW_MENU_BREAKS = (logic.BREAKPOINT, logic.EXPORT_FILE)
IMPORT_FILTER = (
    "All Files (*);;Maya Scenes (*.ma *.mb);;FBX (*.fbx);;OBJ (*.obj);;Alembic (*.abc)"
)
EXPORT_FILTER = "Maya ASCII (*.ma);;Maya Binary (*.mb);;FBX (*.fbx);;OBJ (*.obj)"
# How many names the delete confirmation lists before "...and N more".
MAX_LISTED = 10


@functools.cache
def status_icon(status):
    """The status column's icon for a run ``status``; an empty icon for none."""
    if status not in STATUS_ICONS:
        return QtGui.QIcon()
    draw, color = STATUS_ICONS[status]
    return icons.same_when_selected(draw(color))


@functools.cache
def kind_icon(kind):
    """The name column's icon for an item ``kind``; an empty icon for none."""
    if kind not in ICONS:
        return QtGui.QIcon()
    return icons.same_when_selected(icons.icon(ICONS[kind]))


def row_color(kind, palette):
    """The background for a row of ``kind`` in a tree with ``palette``; None for none."""
    if kind == logic.SEPARATOR:
        return palette.color(QtGui.QPalette.ColorRole.Base).darker(SEPARATOR_DARKER)
    return ROW_COLORS.get(kind)


def _warn(message):
    cmds.warning(f"Kaiju Scripter: {message}")


def _open_in_file_browser(path):
    if sys.platform == "win32":
        os.startfile(os.path.normpath(path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class _FolderBox(QtWidgets.QComboBox):
    """Path box that doesn't grow with its paths, so a long one can't stop the
    window getting narrower. Its dropdown still opens wide enough to read them."""

    def showPopup(self):
        metrics = self.view().fontMetrics()
        widest = max((metrics.horizontalAdvance(self.itemText(i)) for i in range(self.count())), default=0)
        self.view().setMinimumWidth(widest + 2 * metrics.averageCharWidth())
        super().showPopup()


def folder_box():
    box = _FolderBox()
    box.setEditable(True)
    box.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
    box.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    box.setMinimumContentsLength(10)
    box.lineEdit().setPlaceholderText("Scripts folder...")
    return box


class _Tree(QtWidgets.QTreeWidget):
    """Tree whose drag and drop moves and reorders files on disk, then refreshes."""

    def __init__(self, window):
        super().__init__()
        self.owner = window
        # Double-click opens a folder in the file browser; its arrow expands it.
        self.setExpandsOnDoubleClick(False)
        self.setHeaderLabels(["Name", "Version", "Type", ""])
        header = self.header()
        header.setSectionsMovable(False)
        header.setStretchLastSection(False)
        # Name fills the rest; Version and Type widths are adjustable and remembered.
        header.setSectionResizeMode(NAME, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for column, width in zip(SIZED, self._saved_widths()):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeMode.Interactive)
            self.setColumnWidth(column, width)
        header.setSectionResizeMode(STATUS, QtWidgets.QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(STATUS, STATUS_WIDTH)
        header.sectionResized.connect(self._remember_widths)
        # Right-click the header to hide or show columns; remembered per user.
        for label, column in HIDEABLE.items():
            self.setColumnHidden(column, bool(settings.get(logic.SETTINGS_KEY, self._hidden_key(label), 0)))
        header.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._on_header_menu)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)
        self.itemSelectionChanged.connect(self._grey_parent_folders)

    def _grey_parent_folders(self):
        # Only folders (items with children) are touched: they have no row color
        # of their own, unlike separators and breakpoints.
        parents = [item.parent() for item in self.selectedItems() if item.parent()]
        grey = QtGui.QBrush(self.palette().color(QtGui.QPalette.ColorRole.Base).lighter(PARENT_LIGHTER))
        iterator = QtWidgets.QTreeWidgetItemIterator(self, QtWidgets.QTreeWidgetItemIterator.IteratorFlag.HasChildren)
        while iterator.value():
            folder = iterator.value()
            brush = grey if any(folder is parent for parent in parents) else QtGui.QBrush()
            for column in range(self.columnCount()):
                folder.setBackground(column, brush)
            iterator += 1

    @staticmethod
    def _saved_widths():
        saved = settings.get(logic.SETTINGS_KEY, "version_type_widths", "")
        try:
            widths = [int(w) for w in saved.split(",")]
        except (AttributeError, ValueError):
            return DEFAULT_WIDTHS
        return widths if len(widths) == len(DEFAULT_WIDTHS) else DEFAULT_WIDTHS

    def _remember_widths(self, column, _old, _new):
        # Hiding a column resizes it to 0: a hidden column keeps its saved width.
        if column in SIZED and not self.isColumnHidden(column):
            widths = (
                saved if self.isColumnHidden(c) else self.columnWidth(c)
                for c, saved in zip(SIZED, self._saved_widths())
            )
            settings.set(logic.SETTINGS_KEY, "version_type_widths", ",".join(map(str, widths)))

    @staticmethod
    def _hidden_key(label):
        return f"{label.lower()}_column_hidden"

    def _on_header_menu(self, pos):
        menu = QtWidgets.QMenu(self)
        for label, column in HIDEABLE.items():
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(not self.isColumnHidden(column))
            action.toggled.connect(functools.partial(self._set_column_shown, label, column))
        menu.exec(self.header().mapToGlobal(pos))

    def _set_column_shown(self, label, column, shown):
        self.setColumnHidden(column, not shown)
        settings.set(logic.SETTINGS_KEY, self._hidden_key(label), not shown)

    def dropEvent(self, event):
        # Don't call super: the tree is rebuilt from disk instead.
        srcs = self.owner.selected_paths()
        if not srcs:
            return
        Indicator = QtWidgets.QAbstractItemView.DropIndicatorPosition
        position = self.dropIndicatorPosition()
        target_item = self.itemAt(event.position().toPoint())
        target = target_item.data(0, PATH_ROLE) if target_item else None
        if not target or position == Indicator.OnViewport:
            directory, index = self.owner.root, None
        elif position == Indicator.OnItem and os.path.isdir(target):
            directory, index = target, None
        else:
            # Above or below an item (or onto a file): its folder, next to it.
            parent = target_item.parent()
            directory = parent.data(0, PATH_ROLE) if parent else self.owner.root
            index = (parent or self.invisibleRootItem()).indexOfChild(target_item)
            if position != Indicator.AboveItem:
                index += 1
        if directory:
            self.owner.attempt(lambda: logic.place(srcs, directory, index))
        self.owner.populate()


class ScripterWindow(ToolWindow):
    TITLE = "Kaiju Scripter"

    def build_ui(self):
        style = self.style()
        self.root = ""
        self.runner = logic.Runner()

        top = QtWidgets.QHBoxLayout()
        self.folder_box = folder_box()
        self.folder_box.lineEdit().returnPressed.connect(lambda: self.open_folder(self.folder_box.currentText()))
        self.folder_box.activated.connect(lambda i: self.open_folder(self.folder_box.itemText(i)))
        browse = QtWidgets.QPushButton()
        browse.setFixedSize(28, 28)
        browse.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DirIcon))
        browse.setToolTip("Browse for a scripts folder")
        browse.clicked.connect(self._browse)
        refresh = QtWidgets.QPushButton()
        refresh.setFixedSize(28, 28)
        refresh.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_BrowserReload))
        refresh.setToolTip("Read the folder again")
        refresh.clicked.connect(self.populate)
        top.addWidget(self.folder_box, 1)
        top.addWidget(browse)
        top.addWidget(refresh)
        self.layout.addLayout(top)

        self.tree = _Tree(self)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        for keys, fn in (
            (QtGui.QKeySequence.StandardKey.Delete, self._delete_selected),
            (QtGui.QKeySequence(QtCore.Qt.Key.Key_F2), self._rename_current),
        ):
            shortcut = QtGui.QShortcut(keys, self.tree)
            shortcut.setContext(QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(fn)
        self.layout.addWidget(self.tree)

        # Versioned files in the tree, so the Version column updates (e.g. to
        # "v002*") as soon as one is saved, from the Script Editor or anywhere.
        self._watcher = QtCore.QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)

        recent = logic.recent_folders()
        self._fill_folder_box(recent)
        if recent:
            self.open_folder(recent[0])
        else:
            self._placeholder("Pick a scripts folder with the folder button")

    # -- folder -----------------------------------------------------------

    def _fill_folder_box(self, folders):
        self.folder_box.blockSignals(True)
        self.folder_box.clear()
        self.folder_box.addItems(folders)
        self.folder_box.setEditText(self.root)
        self.folder_box.blockSignals(False)

    def open_folder(self, folder):
        folder = folder.strip()
        if not folder or not os.path.isdir(folder):
            _warn(f"Not a folder: {folder}")
            self.folder_box.setEditText(self.root)
            return
        self.root = os.path.normpath(folder)
        logic.remember_folder(self.root)
        self._fill_folder_box(logic.recent_folders())
        self.populate()

    def _browse(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Scripts Folder", self.root or os.path.expanduser("~")
        )
        if folder:
            self.open_folder(folder)

    # -- tree -------------------------------------------------------------

    def populate(self):
        if not self.root or not os.path.isdir(self.root):
            self._placeholder("Pick a scripts folder with the folder button")
            return
        collapsed = self._collapsed_paths()
        self.tree.clear()
        if self._watcher.files():
            self._watcher.removePaths(self._watcher.files())
        entries = logic.scan(self.root)
        if not entries:
            self._placeholder("Empty folder. Right-click > New to add a script.")
            return
        self._add_entries(self.tree.invisibleRootItem(), entries)
        self.tree.expandAll()
        for path in collapsed:
            item = self._find_item(path)
            if item:
                item.setExpanded(False)

    def _collapsed_paths(self):
        collapsed = []

        def visit(item):
            for i in range(item.childCount()):
                child = item.child(i)
                if child.childCount() and not child.isExpanded():
                    collapsed.append(child.data(0, PATH_ROLE))
                visit(child)

        visit(self.tree.invisibleRootItem())
        return collapsed

    def _add_entries(self, parent, entries, inside_disabled=False):
        for entry in entries:
            item = QtWidgets.QTreeWidgetItem(parent, [entry.label, "", entry.type_label, ""])
            if entry.kind == logic.SEPARATOR:
                item.setText(VERSION, logic.SEPARATOR_TEXT)
            item.setToolTip(TYPE, entry.name)
            item.setData(0, PATH_ROLE, entry.path)
            if entry.kind in items.FILE_KINDS:
                self._show_target(item)
            item.setIcon(0, kind_icon(entry.kind))
            color = row_color(entry.kind, self.tree.palette())
            if color:
                for column in range(item.columnCount()):
                    item.setBackground(column, color)
            if not entry.is_dir:
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsDropEnabled)
            if not entry.enabled:
                font = item.font(0)
                font.setStrikeOut(True)
                item.setFont(0, font)
                item.setForeground(0, DISABLED_COLOR)
                item.setToolTip(0, "Disabled: skipped when its folder runs")
            elif inside_disabled:
                item.setForeground(0, DISABLED_COLOR)
                item.setToolTip(0, "In a disabled folder: skipped when its folder runs")
            if versions.is_versioned(entry.path):
                self._watcher.addPath(entry.path)
            self._show_version(item)
            self._show_status(item)
            if entry.is_dir:
                self._add_entries(item, entry.children, inside_disabled or not entry.enabled)

    def _show_version(self, item):
        path = item.data(0, PATH_ROLE)
        if not versions.is_versioned(path):
            return
        text = versions.label(path)
        item.setText(VERSION, text)
        tips = []
        if not text:
            tips.append("Not published yet")
        latest = versions.is_latest(path)
        item.setData(VERSION, QtCore.Qt.ItemDataRole.ForegroundRole, None if latest else OLD_VERSION_COLOR)
        if not latest:
            tips.append("Not the newest version")
        if text.endswith("*"):
            tips.append("Has changes not published yet")
        item.setToolTip(VERSION, "\n".join(tips))

    def _on_file_changed(self, path):
        # Editors may still be writing, or save by replacing the file (which
        # drops it from the watcher): look a moment later, and watch it again.
        QtCore.QTimer.singleShot(200, lambda: self._update_version(path))

    def _update_version(self, path):
        if not os.path.isfile(path):
            return
        if path not in self._watcher.files():
            self._watcher.addPath(path)
        item = self._find_item(path)
        if item:
            self._show_version(item)

    def _show_status(self, item):
        status, message = self.runner.status(item.data(0, PATH_ROLE))
        item.setIcon(STATUS, status_icon(status))
        item.setToolTip(STATUS, message or STATUS_TIPS.get(status, ""))
        if status == logic.FAILED:
            item.setForeground(0, FAILED_COLOR)
            item.setToolTip(0, message)

    def _find_item(self, path):
        def visit(item):
            for i in range(item.childCount()):
                child = item.child(i)
                if child.data(0, PATH_ROLE) == path:
                    return child
                found = visit(child)
                if found:
                    return found
            return None

        return visit(self.tree.invisibleRootItem())

    def selected_paths(self):
        """Paths of the selected items, in tree order."""
        paths = []

        def visit(item):
            for i in range(item.childCount()):
                child = item.child(i)
                path = child.data(0, PATH_ROLE)
                if path and child.isSelected():
                    paths.append(path)
                visit(child)

        visit(self.tree.invisibleRootItem())
        return paths

    def _placeholder(self, text):
        self.tree.clear()
        item = QtWidgets.QTreeWidgetItem(self.tree, [text])
        item.setForeground(0, QtGui.QColor(120, 120, 120))
        item.setFlags(QtCore.Qt.ItemFlag.NoItemFlags)
        item.setFirstColumnSpanned(True)

    # -- actions ----------------------------------------------------------

    def attempt(self, fn):
        """Call ``fn``; warn instead of raising. Returns its result, or ``None``."""
        try:
            return fn()
        except Exception as e:
            log.exception("Kaiju Scripter action failed")
            _warn(str(e))
            return None

    def _run_selected(self):
        paths = self.selected_paths()
        if not paths:
            _warn("Select items to run.")
            return
        self._report(self.attempt(lambda: self.runner.run(paths)))

    def _continue(self, path):
        self._report(self.attempt(lambda: self.runner.continue_run(path)))

    def _report(self, result):
        self.populate()
        if result == logic.FAILED:
            _warn("The run stopped at a failed script. See the Script Editor for the error.")
        elif result == logic.PAUSED:
            name = os.path.basename(self.runner.paused_at)
            cmds.inViewMessage(
                assistMessage=f"Paused at {name}. Right-click it > Continue to run the rest.",
                position="topCenter",
                fade=True,
            )

    def _show_target(self, item):
        """Name tooltip of an Import or Export File: the file it points to."""
        path = item.data(0, PATH_ROLE)
        try:
            text = items.target(path)
        except ValueError as e:
            text = str(e)
        if not item.toolTip(0):
            item.setToolTip(0, text)

    def _on_double_click(self, item, _column):
        path = item.data(0, PATH_ROLE)
        kind = logic.kind_of(path) if path else None
        if kind == logic.SCRIPT:
            self.attempt(lambda: script_editor.open_in_script_editor(path))
        elif kind in items.DATATYPES:
            lines = self.attempt(lambda: items.describe(path))
            if lines is not None:
                QtWidgets.QMessageBox.information(self, os.path.basename(path), "\n".join(lines))
        elif kind in items.FILE_KINDS:
            self._change_target(path)
        elif kind == logic.FOLDER:
            self.attempt(lambda: _open_in_file_browser(path))

    def _pick_file(self, kind, start):
        """Ask for an Import File's file (to open) or an Export File's (to
        save to, which asks before overwriting). ``""`` if cancelled."""
        if kind == logic.IMPORT_FILE:
            picked, _ = QtWidgets.QFileDialog.getOpenFileName(self, "File to Import", start, IMPORT_FILTER)
        else:
            picked, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export Selected To", start, EXPORT_FILTER)
        return os.path.normpath(picked) if picked else ""

    def _change_target(self, path):
        try:
            start = items.target(path)
        except ValueError:
            start = os.path.dirname(path)
        picked = self._pick_file(logic.kind_of(path), start)
        if picked:
            self.attempt(lambda: items.set_target(path, picked))
            self.populate()

    def _on_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        path = item.data(0, PATH_ROLE) if item else None
        if not path and not self.root:
            return
        kind = logic.kind_of(path) if path else None
        selected = self.selected_paths()
        menu = QtWidgets.QMenu(self)

        if selected:
            menu.addAction("Run", self._run_selected)
        if kind == logic.BREAKPOINT:
            action = menu.addAction("Continue", lambda: self._continue(path))
            action.setEnabled(self.runner.can_continue(path))
        if selected:
            enabled = [logic.is_enabled(p) for p in selected]
            if any(enabled):
                menu.addAction("Disable", lambda: self._set_enabled(selected, False))
            if not all(enabled):
                menu.addAction("Enable", lambda: self._set_enabled(selected, True))
        menu.addSeparator()

        new_menu = menu.addMenu("New")
        for new_kind in NEW_KINDS:
            new_menu.addAction(new_kind, lambda k=new_kind: self._create(k, item))
            if new_kind in NEW_MENU_BREAKS:
                new_menu.addSeparator()
        if kind == logic.SCRIPT:
            menu.addAction("Edit in VS Code", lambda: self.attempt(lambda: vscode.open_in_vscode(path)))
        if kind in items.FILE_KINDS:
            menu.addAction("Change File...", lambda: self._change_target(path))
        if path and versions.is_versioned(path):
            menu.addSeparator()
            menu.addAction("Publish...", lambda: self._publish(path))
            history = menu.addAction("Versions...", lambda: VersionsDialog(self, path).exec())
            history.setEnabled(versions.count(path) > 0)
        menu.addSeparator()
        if path:
            menu.addAction("Rename", lambda: self._rename(path))
            menu.addAction("Delete", self._delete_selected)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _set_enabled(self, paths, enabled):
        self.attempt(lambda: logic.set_enabled(paths, enabled))
        self.populate()

    def _new_target(self, item):
        """``(directory, index)`` for a new item: at the end of the folder
        ``item`` is; just below the file ``item`` is; at the end of the
        scripts folder when ``item`` is ``None``."""
        target = item.data(0, PATH_ROLE) if item else None
        if target and os.path.isdir(target):
            return target, None
        if target:
            parent = item.parent()
            directory = parent.data(0, PATH_ROLE) if parent else self.root
            return directory, (parent or self.tree.invisibleRootItem()).indexOfChild(item) + 1
        return self.root, None

    def _create(self, kind, item):
        directory, index = self._new_target(item)
        if not directory or not os.path.isdir(directory):
            return
        default = logic.default_name(kind, directory)
        if kind in items.DATATYPES:
            # Check the selection first, so a bad one doesn't cost a name dialog.
            selection = cmds.ls(selection=True, long=True) or []
            problems = items.selection_problems(kind, selection)
            if problems:
                _warn(" ".join(problems))
                return
            create = lambda name: logic.create_data_item(kind, directory, name, selection, index)  # noqa: E731
        elif kind in items.FILE_KINDS:
            target = self._pick_file(kind, directory)
            if not target:
                return
            default = os.path.splitext(os.path.basename(target))[0]
            create = lambda name: logic.create_file_item(kind, directory, name, target, index)  # noqa: E731
        else:
            create = lambda name: logic.create_item(kind, directory, name, index)  # noqa: E731
        name, ok = QtWidgets.QInputDialog.getText(self, f"New {kind}", "Name:", text=default)
        if not ok or not name:
            return
        path = self.attempt(lambda: create(name))
        self.populate()
        if path and kind == logic.SCRIPT:
            self.attempt(lambda: script_editor.open_in_script_editor(path))

    def _rename_current(self):
        item = self.tree.currentItem()
        path = item.data(0, PATH_ROLE) if item else None
        if path:
            self._rename(path)

    def _rename(self, path):
        current = os.path.basename(path)
        if os.path.isfile(path):
            current = os.path.splitext(current)[0]
        name, ok = QtWidgets.QInputDialog.getText(self, "Rename", "Name:", text=current)
        if ok and name:
            self.attempt(lambda: logic.rename_path(path, name))
            self.populate()

    def _delete_selected(self):
        paths = self.selected_paths()
        if not paths:
            return
        names = [os.path.basename(p) for p in paths]
        shown = "\n".join(names[:MAX_LISTED])
        if len(names) > MAX_LISTED:
            shown += f"\n...and {len(names) - MAX_LISTED} more"
        folders = "\nFolders are deleted with everything in them." if any(map(os.path.isdir, paths)) else ""
        what = "this item" if len(paths) == 1 else f"these {len(paths)} items"
        kept = sum(versions.count(p) for p in paths if os.path.isfile(p))
        if kept:
            folders += f"\n{kept} saved version{'s' if kept != 1 else ''} will be deleted too."
        Button = QtWidgets.QMessageBox.StandardButton
        answer = QtWidgets.QMessageBox.question(
            self, "Confirm Delete", f"Delete {what}?{folders}\n\n{shown}", Button.Yes | Button.No, Button.No
        )
        if answer == Button.Yes:
            self.attempt(lambda: logic.delete_paths(paths))
            self.populate()

    def _publish(self, path):
        description, ok = QtWidgets.QInputDialog.getText(
            self, f"Publish {os.path.basename(path)}", "What changed? (optional)"
        )
        if not ok:
            return
        if logic.kind_of(path) in items.DATATYPES:
            selection = cmds.ls(selection=True, long=True) or []
            number = self.attempt(lambda: items.publish_data(path, selection, description))
        else:
            number = self.attempt(lambda: versions.publish(path, description))
        self.populate()
        if number:
            cmds.inViewMessage(
                assistMessage=f"Published {os.path.basename(path)} v{number:03d}", position="topCenter", fade=True
            )


class VersionsDialog(QtWidgets.QDialog):
    """An item's versions, newest first, with Restore."""

    def __init__(self, window, path):
        super().__init__(window)
        self.owner, self.path = window, path
        self.setWindowTitle(f"Versions of {os.path.basename(path)}")
        self.resize(460, 300)
        layout = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTreeWidget()
        self.table.setHeaderLabels(["Version", "Saved", "Description"])
        self.table.setRootIsDecorated(False)
        self.table.header().setStretchLastSection(True)
        self.table.itemDoubleClicked.connect(lambda *_: self._restore())
        layout.addWidget(self.table)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        restore = QtWidgets.QPushButton("Restore")
        restore.setToolTip("Put this version back. Asks first if there are changes not published yet.")
        restore.clicked.connect(self._restore)
        buttons.addWidget(restore)
        layout.addLayout(buttons)
        self._fill()

    def _fill(self):
        self.table.clear()
        current = versions.label(self.path).rstrip("*")
        for version in reversed(versions.list_versions(self.path)):
            name = f"v{version.number:03d}"
            saved = QtCore.QDateTime.fromSecsSinceEpoch(int(version.mtime)).toString("yyyy-MM-dd hh:mm")
            row = QtWidgets.QTreeWidgetItem(self.table, [name, saved, version.description])
            row.setData(0, PATH_ROLE, version.number)
            if name == current:
                font = row.font(0)
                font.setBold(True)
                for column in range(3):
                    row.setFont(column, font)
        self.table.resizeColumnToContents(0)
        self.table.resizeColumnToContents(1)

    def _restore(self):
        row = self.table.currentItem()
        if row is None:
            return
        number = row.data(0, PATH_ROLE)
        if versions.has_unpublished(self.path):
            Button = QtWidgets.QMessageBox.StandardButton
            answer = QtWidgets.QMessageBox.question(
                self,
                "Restore",
                f"{os.path.basename(self.path)} has changes not published yet. "
                f"Restoring v{number:03d} loses them.\n\nRestore anyway?",
                Button.Yes | Button.No,
                Button.No,
            )
            if answer != Button.Yes:
                return
        script_editor.watch_in_script_editor(self.path)
        self.owner.attempt(lambda: versions.restore(self.path, number))
        self.owner.populate()
        self._fill()
