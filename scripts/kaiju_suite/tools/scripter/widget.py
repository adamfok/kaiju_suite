import functools
import os
import subprocess
import sys

from maya import cmds
from PySide6 import QtCore, QtGui, QtWidgets

from kaiju_suite.core import checks, settings
from kaiju_suite.core.log import get_logger
from kaiju_suite.tools.scripter import items, logic, script_editor, versions, vscode
from kaiju_suite.ui import icons, status_icons
from kaiju_suite.ui.base_window import ToolWindow
from kaiju_suite.ui.qc_tab import QCResultsDialog

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
    logic.SELECTION: "scripter_selection.svg",
    items.NURBS_CURVE: "scripter_nurbs_curve.svg",
}
# The right-click New menu, in order.
NEW_KINDS = (
    logic.SCRIPT,
    logic.FOLDER,
    logic.SEPARATOR,
    logic.BREAKPOINT,
    logic.IMPORT_FILE,
    logic.EXPORT_FILE,
    logic.SELECTION,
    logic.JOINTS,
    logic.SKIN,
    logic.MESH,
    items.NURBS_CURVE,
)
# Dividers in the New menu after these kinds.
NEW_MENU_BREAKS = (logic.BREAKPOINT, logic.SELECTION)
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
    # Paths of the items Copy picked, for Paste. Kept by the class, so it lasts
    # the Maya session: you can open another scripts folder, or close and
    # reopen Scripter, and paste them there.
    copied = []

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
            (QtGui.QKeySequence.StandardKey.Copy, self._copy_selected),
            (QtGui.QKeySequence.StandardKey.Paste, lambda: self._paste(self.tree.currentItem())),
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
            elif entry.kind == logic.SELECTION:
                self._show_entries(item)
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
        if logic.runs_a_folder(paths) and not logic.scene_is_new():
            if not self._ask_new_scene():
                return
        self._report(self.attempt(lambda: self.runner.run(paths)))

    def _ask_new_scene(self):
        """Ask whether a folder run starts from a new scene, and start one if
        so. Returns ``False`` if the run is cancelled."""
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Run Folder")
        box.setIcon(QtWidgets.QMessageBox.Icon.Question)
        box.setText("The scene isn't new. Start a new scene before running?")
        box.setInformativeText("A new scene drops any unsaved changes.")
        Role = QtWidgets.QMessageBox.ButtonRole
        new = box.addButton("New Scene", Role.AcceptRole)
        box.addButton("Run in This Scene", Role.DestructiveRole)
        cancel = box.addButton(QtWidgets.QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(new)
        box.setEscapeButton(cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is cancel:
            return False
        if clicked is new:
            logic.start_new_scene()
        return True

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

    def _show_entries(self, item):
        """Name tooltip of a Selection: a summary of its entries."""
        path = item.data(0, PATH_ROLE)
        try:
            text = items.summary(items.read_entries(path))
        except (OSError, ValueError) as e:
            text = str(e)
        if not item.toolTip(0):
            item.setToolTip(0, text)

    def _edit_selection(self, path):
        entries = self.attempt(lambda: items.read_entries(path))
        if entries is None:
            return

        def save(edited):
            self.attempt(lambda: items.write_entries(path, edited))
            self.populate()

        # Not modal, so you can select objects in Maya while it's open.
        dialog = SelectionDialog(self, os.path.splitext(os.path.basename(path))[0], entries, save)
        dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.show()

    def _on_double_click(self, item, _column):
        path = item.data(0, PATH_ROLE)
        kind = logic.kind_of(path) if path else None
        if kind == logic.SCRIPT:
            self.attempt(lambda: script_editor.open_in_script_editor(path))
        elif items.tool_for(kind):
            # Missing objects are warned about; the tool still opens.
            self.attempt(lambda: items.open_in_tool(path))
        elif kind in items.DATATYPES:
            self._show_info(path)
        elif kind in items.FILE_KINDS:
            self._change_target(path)
        elif kind == logic.SELECTION:
            self._edit_selection(path)
        elif kind == logic.FOLDER:
            self.attempt(lambda: _open_in_file_browser(path))

    def _show_info(self, path):
        lines = self.attempt(lambda: items.describe(path))
        if lines is not None:
            QtWidgets.QMessageBox.information(self, os.path.basename(path), "\n".join(lines))

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

        if selected and kind != logic.BREAKPOINT:
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
            new_menu.addAction(kind_icon(new_kind), new_kind, lambda k=new_kind: self._create(k, item))
            if new_kind in NEW_MENU_BREAKS:
                new_menu.addSeparator()
        if kind == logic.SCRIPT:
            menu.addAction("Edit in VS Code", lambda: self.attempt(lambda: vscode.open_in_vscode(path)))
        if kind in items.FILE_KINDS:
            menu.addAction("Change File...", lambda: self._change_target(path))
        if kind in items.DATATYPES:
            menu.addAction("Select Objects", lambda: self._select_saved(path))
            menu.addAction("Info...", lambda: self._show_info(path))
        if path and versions.is_versioned(path):
            menu.addSeparator()
            menu.addAction("Publish...", lambda: self._publish(path))
            history = menu.addAction("Versions...", lambda: VersionsDialog(self, path).exec())
            history.setEnabled(versions.count(path) > 0)
        menu.addSeparator()
        if selected:
            menu.addAction("Copy", self._copy_selected)
        paste = menu.addAction("Paste", lambda: self._paste(item))
        paste.setEnabled(bool(self.copied))
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
        elif kind == logic.SELECTION:
            selection = items.selected_names()
            create = lambda name: logic.create_selection_item(directory, name, selection, index)  # noqa: E731
        else:
            create = lambda name: logic.create_item(kind, directory, name, index)  # noqa: E731
        name, ok = QtWidgets.QInputDialog.getText(self, f"New {kind}", "Name:", text=default)
        if not ok or not name:
            return
        path = self.attempt(lambda: create(name))
        self.populate()
        if path and kind == logic.SCRIPT:
            self.attempt(lambda: script_editor.open_in_script_editor(path))
        elif path and kind == logic.SELECTION:
            self._edit_selection(path)

    def _copy_selected(self):
        paths = self.selected_paths()
        if paths:
            type(self).copied = paths

    def _paste(self, item):
        """Paste copies of the copied items where New would put one (see
        :meth:`_new_target`), and select them."""
        if not self.copied:
            return
        directory, index = self._new_target(item)
        if not directory or not os.path.isdir(directory):
            return
        pasted = self.attempt(lambda: logic.paste(self.copied, directory, index))
        self.populate()
        self.tree.clearSelection()
        for path in pasted or []:
            found = self._find_item(path)
            if found:
                found.setSelected(True)

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

    def _select_saved(self, path):
        message = self.attempt(lambda: items.select_saved(path))
        if message:
            cmds.inViewMessage(assistMessage=message, position="topCenter", fade=True)

    def _publish_source(self, path):
        """``(objects, from_saved)`` to publish the data item at ``path``
        from: the selection, or with nothing selected the objects saved in
        it. Shows why not and returns ``None`` if they won't do."""
        selection = cmds.ls(selection=True, long=True) or []
        from_saved = not selection
        if from_saved:
            found = self.attempt(lambda: items.saved_objects(path))
            if found is None:
                return None
            selection, problems = found
            reason = "Nothing is selected, and the objects saved in it can't all be found:\n\n"
        else:
            problems = self.attempt(lambda: items.selection_problems(logic.kind_of(path), selection))
            if problems is None:
                return None
            reason = ""
        if problems:
            title = f"Can't Publish {os.path.basename(path)}"
            QtWidgets.QMessageBox.information(self, title, reason + "\n".join(problems))
            return None
        return selection, from_saved

    def _publish(self, path):
        name = os.path.basename(path)
        is_data = logic.kind_of(path) in items.DATATYPES
        from_saved = False
        if is_data:
            source = self._publish_source(path)
            if source is None:
                return
            objects, from_saved = source
        # Catch "nothing changed" before asking anything.
        try:
            same = items.unchanged_since(path, objects) if is_data else versions.unchanged_since(path)
        except Exception as e:
            log.exception("Kaiju Scripter publish check failed")
            _warn(str(e))
            return
        if same:
            cmds.inViewMessage(
                assistMessage=f"Nothing to publish: {name} is the same as v{same:03d}",
                position="topCenter",
                fade=True,
            )
            return
        if from_saved:
            count = len(objects)
            Button = QtWidgets.QMessageBox.StandardButton
            answer = QtWidgets.QMessageBox.question(
                self,
                f"Publish {name}",
                f"Nothing is selected. Update {name} from the {count} object{'s' if count != 1 else ''} "
                "saved in it instead?",
                Button.Yes | Button.No,
                Button.Yes,
            )
            if answer != Button.Yes:
                return
        if is_data and not self._passes_qc(path, objects):
            return
        description, ok = QtWidgets.QInputDialog.getText(self, f"Publish {name}", "What changed? (optional)")
        if not ok:
            return
        if is_data:
            number = self.attempt(lambda: items.publish_data(path, objects, description))
        else:
            number = self.attempt(lambda: versions.publish(path, description))
        self.populate()
        if number:
            cmds.inViewMessage(assistMessage=f"Published {name} v{number:03d}", position="topCenter", fade=True)

    def _passes_qc(self, path, objects):
        """Run the item's QC checks on ``objects`` before publishing. True if
        they all pass (or its kind has none), or the user picks Publish Anyway
        in the dialog listing the problems."""
        found = self.attempt(lambda: items.publish_qc(path, objects))
        if found is None:
            return False
        count = sum(len(problems) for _, problems in found)
        if not count:
            return True
        name = os.path.basename(path)
        dialog = QCResultsDialog(
            self,
            f"QC: {name}",
            f"QC found {count} problem{'s' if count != 1 else ''} in {name}.",
            found,
            "Publish Anyway",
            checks.select_problem,
        )
        return dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted


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


class _EntryList(QtWidgets.QTreeWidget):
    """The Selection editor's entries: clicking empty space clears the selection."""

    def mousePressEvent(self, event):
        if self.itemAt(event.position().toPoint()) is None:
            self.clearSelection()
        super().mousePressEvent(event)


class _PreviewList(QtWidgets.QListWidget):
    """The Selection editor's preview: double-click anywhere calls ``on_double_click``."""

    def __init__(self, on_double_click):
        super().__init__()
        self.on_double_click = on_double_click

    def mouseDoubleClickEvent(self, event):
        self.on_double_click()
        event.accept()


class SelectionDialog(QtWidgets.QDialog):
    """Edit a Selection item's entries and preview what they find now. It
    isn't modal; OK calls ``on_save`` with the edited entries.

    Right-click empty space in the entries list to add an entry, or an entry
    to remove it; double-click one to change it. Picking objects in the
    preview selects them in the scene."""

    TYPE_LABELS = {items.SELECTED: "Selected", items.PATTERN: "Pattern", items.SET: "Set"}

    def __init__(self, window, name, entries, on_save):
        super().__init__(window)
        self.entries = [dict(e) for e in entries]
        self.on_save = on_save
        self.setWindowTitle(f"Selection: {name}")
        self.resize(460, 520)

        self.table = _EntryList()
        self.table.setHeaderLabels(["Type", "Entry", "Found"])
        self.table.setRootIsDecorated(False)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(
            lambda pos: self.entry_menu(self.table.itemAt(pos)).exec(self.table.viewport().mapToGlobal(pos))
        )
        self.table.itemDoubleClicked.connect(self._edit_row)
        self.table.itemSelectionChanged.connect(self._refresh)
        # Entry takes the width left by Type and Found; long entries end in "...".
        header = self.table.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.resizeSection(0, 70)
        header.resizeSection(2, 50)
        self.table.setTextElideMode(QtCore.Qt.TextElideMode.ElideRight)

        # The preview shows what the selected entries find, or all of them
        # when none is selected; the objects it lists are self.previewed.
        self.previewed = []
        self.preview = _PreviewList(self.select_all)
        self.preview.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.preview.setToolTip("Pick objects to select them in the scene; double-click to select them all")
        self.preview.itemSelectionChanged.connect(self._select_picked)
        self.preview_label = QtWidgets.QLabel("Preview:")
        self.count = QtWidgets.QLabel()
        self.preview_row = QtWidgets.QHBoxLayout()
        self.preview_row.addWidget(self.preview_label)
        self.preview_row.addWidget(self.count)
        self.preview_row.addStretch(1)

        ok_cancel = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        ok_cancel.accepted.connect(self.accept)
        ok_cancel.rejected.connect(self.reject)
        self.ok_cancel = ok_cancel
        # The open window editing a Selected entry's objects, or picking a
        # set, if any. The entries wait while one is open.
        self.objects_window = None
        self.set_window = None

        add_row = QtWidgets.QHBoxLayout()
        self.add_buttons = []
        for tip, icon_file, slot in (
            ("Add Selected", "scripter_add_selected.svg", self._add_selected),
            ("Add Pattern", "scripter_add_pattern.svg", self._add_pattern),
            ("Add Selection Set", "scripter_add_set.svg", self._add_set),
        ):
            button = QtWidgets.QToolButton()
            button.setIcon(icons.same_when_selected(icons.icon(icon_file)))
            button.setToolTip(tip)
            button.setAutoRaise(True)
            button.clicked.connect(slot)
            add_row.addWidget(button)
            self.add_buttons.append(button)
        add_row.addStretch(1)
        self.delete_button = QtWidgets.QToolButton()
        self.delete_button.setIcon(icons.same_when_selected(icons.icon("scripter_delete.svg")))
        self.delete_button.setToolTip("Remove")
        self.delete_button.setAutoRaise(True)
        self.delete_button.clicked.connect(self.remove_selected)
        add_row.addWidget(self.delete_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(add_row)
        layout.addWidget(self.table, 1)
        layout.addLayout(self.preview_row)
        layout.addWidget(self.preview, 1)
        layout.addWidget(ok_cancel)
        self._rebuild()

    def _lock(self, locked):
        """Hold the entries (list, add buttons and OK) while a Selected
        entry's objects window is open."""
        for widget in [self.table, self.ok_cancel, *self.add_buttons]:
            widget.setEnabled(not locked)
        self.delete_button.setEnabled(not locked and bool(self.table.selectedItems()))

    def accept(self):
        self.on_save(self.entries)
        super().accept()

    def entry_menu(self, row):
        """The entries list's right-click menu: adding on empty space, Remove on an entry."""
        menu = QtWidgets.QMenu(self)
        if row is None:
            menu.addAction("Add Selected", self._add_selected)
            menu.addAction("Add Pattern...", self._add_pattern)
            menu.addAction("Add Selection Set...", self._add_set)
        else:
            if not row.isSelected():
                self.table.clearSelection()
                row.setSelected(True)
            menu.addAction("Remove", self.remove_selected)
        return menu

    def _rebuild(self):
        """Fill the entries list again after it was edited."""
        with QtCore.QSignalBlocker(self.table):
            self.table.clear()
            for index, entry in enumerate(self.entries):
                label = entry["value"] if entry["type"] == items.SET else items.entry_label(entry)
                row = QtWidgets.QTreeWidgetItem(self.table, [self.TYPE_LABELS.get(entry["type"], entry["type"]), label, ""])
                row.setData(0, PATH_ROLE, index)
        self._refresh()

    def _refresh(self):
        """Look the entries up in the scene again: their counts, and the preview."""
        default = self.table.palette().color(QtGui.QPalette.ColorRole.Text)
        chosen = []
        for i in range(self.table.topLevelItemCount()):
            row = self.table.topLevelItem(i)
            entry = self.entries[row.data(0, PATH_ROLE)]
            found, missing = items.lookup(entry)
            row.setText(2, str(len(found)))
            for column in range(3):
                row.setForeground(column, FAILED_COLOR if missing else default)
            row.setToolTip(1, f"Not in the scene now: {', '.join(missing)}" if missing else items.entry_label(entry))
            if row.isSelected():
                chosen.append(entry)
        self.delete_button.setEnabled(self.table.isEnabled() and bool(chosen))
        self.previewed, _missing = items.resolve(chosen or self.entries)
        # Filling the preview mustn't change the scene selection.
        with QtCore.QSignalBlocker(self.preview):
            self.preview.clear()
            self.preview.addItems(self.previewed)
        self.count.setText(f"{len(self.previewed)} object{'' if len(self.previewed) == 1 else 's'}")

    def _select_picked(self):
        """Select the objects picked in the preview in the scene."""
        picked = [item.text() for item in self.preview.selectedItems()]
        if picked:
            cmds.select(picked, replace=True)

    def select_all(self):
        """Pick every object in the preview, selecting them all in the scene."""
        if not self.previewed:
            _warn("Nothing to select: the preview is empty.")
            return
        with QtCore.QSignalBlocker(self.preview):
            self.preview.selectAll()
        cmds.select(self.previewed, replace=True)

    def _add_selected(self):
        names = items.selected_names()
        if not names:
            _warn("Nothing selected to add.")
            return
        self.entries = items.add_selected(self.entries, names)
        self._rebuild()

    def _ask_pattern(self, entry=None):
        """``(pattern, node_type)`` for a new or edited pattern entry; ``None`` if cancelled."""
        dialog = PatternDialog(self, *((entry["value"], entry.get("node_type", items.ANY_TYPE)) if entry else ()))
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return None
        pattern, node_type = dialog.values()
        return (pattern, node_type) if pattern else None

    def _ask_set(self, on_pick, current=None):
        """Open the Selection Set picker (not modal); its OK calls ``on_pick`` with the set's name."""
        self._open_child("set_window", SetDialog(self, current, on_pick))

    def _add_pattern(self):
        answer = self._ask_pattern()
        if answer:
            self.entries.append({"type": items.PATTERN, "value": answer[0], "node_type": answer[1]})
            self._rebuild()

    def _add_set(self):
        def add(name):
            self.entries.append({"type": items.SET, "value": name})
            self._rebuild()

        self._ask_set(add)

    def _edit_row(self, row, _column):
        """Change an entry: a Selected one in a window of its objects, a
        pattern or set by asking for its new value."""
        entry = self.entries[row.data(0, PATH_ROLE)]
        if entry["type"] == items.SELECTED:
            self._edit_objects(entry)
            return
        if entry["type"] == items.PATTERN:
            answer = self._ask_pattern(entry)
            if answer:
                entry["value"], entry["node_type"] = answer
                self._rebuild()
            return
        if entry["type"] == items.SET:

            def change(name):
                entry["value"] = name
                self._rebuild()

            self._ask_set(change, entry["value"])

    def _edit_objects(self, entry):
        """Open a window on a Selected entry's objects. The entries list and
        OK wait until it closes; its OK puts the objects back in the entry."""

        def save(names):
            entry["value"] = names
            self._rebuild()

        self._open_child("objects_window", SelectedObjectsDialog(self, entry["value"], save))

    def _open_child(self, attr, window):
        """Show ``window`` (not modal) as ``self.<attr>``, holding the entries until it closes."""

        def closed():
            setattr(self, attr, None)
            self._lock(False)
            self._refresh()

        setattr(self, attr, window)
        window.finished.connect(closed)
        self._lock(True)
        window.show()

    def remove_selected(self):
        gone = {row.data(0, PATH_ROLE) for row in self.table.selectedItems()}
        self.entries = [e for i, e in enumerate(self.entries) if i not in gone]
        self._rebuild()


class SelectedObjectsDialog(QtWidgets.QDialog):
    """Edit the objects of one Selected entry. It isn't modal, so you can
    select objects in Maya while it's open; OK calls ``on_save`` with them.

    The icon buttons at the top add the scene selection, replace the objects
    with it, or remove the picked objects. Picking objects selects them in
    the scene."""

    def __init__(self, parent, names, on_save):
        super().__init__(parent)
        self.names = list(names)
        self.on_save = on_save
        self.setWindowTitle("Selected Objects")
        self.resize(320, 400)

        self.list = QtWidgets.QListWidget()
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.itemSelectionChanged.connect(self._select_picked)

        button_row = QtWidgets.QHBoxLayout()
        self.buttons = []
        for tip, icon_file, slot in (
            ("Add Selected", "scripter_add_selected.svg", self.add_selected),
            ("Replace with Selected", "scripter_replace_selected.svg", self.replace_with_selected),
            ("Remove", "scripter_remove.svg", self.remove_selected),
        ):
            button = QtWidgets.QToolButton()
            button.setIcon(icons.same_when_selected(icons.icon(icon_file)))
            button.setToolTip(tip)
            button.setAutoRaise(True)
            button.clicked.connect(slot)
            button_row.addWidget(button)
            self.buttons.append(button)
        button_row.addStretch(1)
        self.remove_button = self.buttons[-1]

        ok_cancel = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        ok_cancel.accepted.connect(self.accept)
        ok_cancel.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(button_row)
        layout.addWidget(self.list, 1)
        layout.addWidget(ok_cancel)
        self._fill()

    def accept(self):
        if not self.names:
            _warn("An entry needs at least one object: add some, or remove the entry instead.")
            return
        self.on_save(self.names)
        super().accept()

    def _fill(self):
        with QtCore.QSignalBlocker(self.list):
            self.list.clear()
            for name in self.names:
                item = QtWidgets.QListWidgetItem(name, self.list)
                if items.missing({"type": items.SELECTED, "value": [name]}):
                    item.setForeground(FAILED_COLOR)
                    item.setToolTip("Not in the scene now")
        self.remove_button.setEnabled(False)

    def _select_picked(self):
        self.remove_button.setEnabled(bool(self.list.selectedItems()))
        picked = [item.text() for item in self.list.selectedItems() if item.foreground().color() != FAILED_COLOR]
        if picked:
            cmds.select(picked, replace=True)

    def _scene_selection(self):
        names = items.selected_names()
        if not names:
            _warn("Nothing selected in the scene.")
        return names

    def add_selected(self):
        names = self._scene_selection()
        if names:
            self.names = list(dict.fromkeys(self.names + names))
            self._fill()

    def replace_with_selected(self):
        names = self._scene_selection()
        if names:
            self.names = list(dict.fromkeys(names))
            self._fill()

    def remove_selected(self):
        gone = {item.text() for item in self.list.selectedItems()}
        self.names = [name for name in self.names if name not in gone]
        self._fill()


class PatternDialog(QtWidgets.QDialog):
    """Ask for a pattern entry's name pattern and the node type it finds."""

    def __init__(self, parent, pattern="", node_type=items.ANY_TYPE):
        super().__init__(parent)
        self.setWindowTitle("Pattern")
        self.pattern = QtWidgets.QLineEdit(pattern)
        self.pattern.setPlaceholderText("*_geo")
        self.pattern.setToolTip("Maya wildcards (* and ?); separate several patterns with spaces")
        self.node_type = QtWidgets.QComboBox()
        self.node_type.addItems(items.NODE_TYPES)
        self.node_type.setCurrentText(node_type)
        self.node_type.setToolTip("Geo, Nurbs Curve, Nurbs Surface and Locator find transforms with that shape")

        ok_cancel = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        ok_cancel.accepted.connect(self.accept)
        ok_cancel.rejected.connect(self.reject)

        form = QtWidgets.QFormLayout(self)
        form.addRow("Name:", self.pattern)
        form.addRow("Type:", self.node_type)
        form.addRow(ok_cancel)
        self.resize(320, self.sizeHint().height())

    def values(self):
        """``[pattern, node_type]``, the pattern stripped of outer spaces."""
        return [self.pattern.text().strip(), self.node_type.currentText()]


class _SetList(QtWidgets.QListWidget):
    """The Selection Set picker's list: calls ``on_click`` after every click in it."""

    def __init__(self, on_click):
        super().__init__()
        self.on_click = on_click

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        # Later, not while the click is still being handled.
        QtCore.QTimer.singleShot(0, self.on_click)


class SetDialog(QtWidgets.QDialog):
    """Pick a selection set for a set entry from a list of the scene's sets,
    or make or delete one with the buttons above it. It isn't modal; OK, or
    double-clicking a set, calls ``on_pick`` with the picked set's name.

    The list reads the scene's sets again after each click in it and
    each time the window is activated, so sets made or deleted in Maya show up."""

    def __init__(self, parent, current, on_pick):
        super().__init__(parent)
        self.on_pick = on_pick
        self.setWindowTitle("Selection Set")
        self.new_button = QtWidgets.QToolButton()
        self.new_button.setIcon(icons.same_when_selected(icons.icon("scripter_add_set.svg")))
        self.new_button.setToolTip("New Selection Set from Selected")
        self.new_button.setAutoRaise(True)
        self.new_button.clicked.connect(self._new_set)
        self.delete_button = QtWidgets.QToolButton()
        self.delete_button.setIcon(icons.same_when_selected(icons.icon("scripter_delete_set.svg")))
        self.delete_button.setToolTip("Delete Selection Set")
        self.delete_button.setAutoRaise(True)
        self.delete_button.clicked.connect(self._delete_set)
        button_row = QtWidgets.QHBoxLayout()
        button_row.addWidget(self.new_button)
        button_row.addWidget(self.delete_button)
        button_row.addStretch(1)

        self.set_list = _SetList(self._fill)
        self.set_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.set_list.itemSelectionChanged.connect(lambda: self.delete_button.setEnabled(bool(self.value())))
        self.set_list.itemDoubleClicked.connect(lambda _item: self.accept())
        # The entry's set when it's already missing from the scene, kept in the
        # list so OK keeps it; a set deleted while this is open just goes.
        self.current = current if current and current not in items.scene_sets() else None
        self._fill(current)

        self.ok_cancel = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self.ok_cancel.accepted.connect(self.accept)
        self.ok_cancel.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(button_row)
        layout.addWidget(self.set_list, 1)
        layout.addWidget(self.ok_cancel)
        self.resize(300, 320)

    def _fill(self, pick=None):
        """List the scene's sets again and pick ``pick`` (by default, the
        picked set) if it's still there."""
        pick = self.value() if pick is None else pick
        sets = items.scene_sets()
        if self.current and self.current not in sets:
            sets.insert(0, self.current)
        scroll = self.set_list.verticalScrollBar().value()
        with QtCore.QSignalBlocker(self.set_list):
            self.set_list.clear()
            self.set_list.addItems(sets)
            for item in self.set_list.findItems(pick, QtCore.Qt.MatchFlag.MatchExactly) if pick else []:
                item.setSelected(True)
                self.set_list.setCurrentItem(item)
        self.set_list.verticalScrollBar().setValue(scroll)
        self.delete_button.setEnabled(bool(self.value()))

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.Type.ActivationChange and self.isActiveWindow():
            self._fill()

    def value(self):
        """The picked set's name; ``""`` if none is picked."""
        picked = self.set_list.selectedItems()
        return picked[0].text() if picked else ""

    def accept(self):
        if self.value():
            self.on_pick(self.value())
        super().accept()

    def _new_set(self):
        members = items.selected_names()
        if not members:
            _warn("Nothing selected to make a set from.")
            return
        # Named after the entry's missing set, if any, so making it again fixes the entry.
        default = self.current or "selection_set"
        name, ok = QtWidgets.QInputDialog.getText(self, "New Selection Set", "Name:", text=default)
        if not ok or not name.strip():
            return
        try:
            made = items.create_set(name, members)
        except (ValueError, RuntimeError) as e:
            _warn(str(e))
            return
        self._fill(made)

    def _delete_set(self):
        """Delete the picked set from the scene (not its members), as one undo step."""
        try:
            items.delete_set(self.value())
        except (ValueError, RuntimeError) as e:
            _warn(str(e))
            return
        self._fill("")
