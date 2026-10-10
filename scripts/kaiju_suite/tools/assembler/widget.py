import os

from maya import cmds
from PySide6 import QtCore, QtGui, QtWidgets

from kaiju_suite.core import settings
from kaiju_suite.core.log import get_logger
from kaiju_suite.tools.assembler import logic, plan, products, report, runlog, versions
from kaiju_suite.tools.assembler.report_widget import ReportDialog
from kaiju_suite.ui.base_window import ToolWindow

log = get_logger(__name__)

SETTINGS_KEY = "assembler"
_PLAN_FILTER = "Build Plans (*.json);;All Files (*)"
PATH_ROLE = QtCore.Qt.ItemDataRole.UserRole

DISABLED_COLOR = QtGui.QColor(115, 115, 115)
# Version column when the file isn't at its latest version.
OLD_VERSION_COLOR = QtGui.QColor(235, 150, 50)
# Starting widths of the Name and Version columns, until the user drags them.
# Type, the last column, stretches to fill the rest.
DEFAULT_WIDTHS = (220, 60)
# Name color for the last run of each step; see logic.run_steps.
STATUS_COLORS = {
    logic.RUNNING: QtGui.QColor(110, 180, 240),
    logic.SUCCESS: QtGui.QColor(95, 190, 95),
    logic.WARNING: QtGui.QColor(230, 200, 60),
    logic.ERROR: QtGui.QColor(225, 85, 85),
}
STATUS_TIPS = {
    logic.WARNING: "Ran with warnings. Right-click > Show Log to see them.",
    logic.ERROR: "Failed. Right-click > Show Log to see why.",
}
# Line colors in the Show Log window, by level; header lines are dimmed.
LOG_COLORS = {
    None: QtGui.QColor(150, 150, 150),
    runlog.WARNING: STATUS_COLORS[logic.WARNING],
    runlog.ERROR: STATUS_COLORS[logic.ERROR],
}


def _warn(message):
    cmds.warning(f"Kaiju Assembler: {message}")


def _notify(message):
    log.info(message)
    cmds.inViewMessage(assistMessage=message, position="topCenter", fade=True)


class _AssemblerTree(QtWidgets.QTreeWidget):
    """Tree whose drag/drop moves and reorders files on disk, then refreshes."""

    def __init__(self, window):
        super().__init__()
        self.window = window
        # Name (without extension), current version, product type. Name and Version
        # widths are adjustable and remembered; Type fills the rest.
        self.setHeaderLabels(["Name", "Version", "Type"])
        header = self.header()
        header.setSectionsMovable(False)
        header.setStretchLastSection(True)
        for column in range(len(DEFAULT_WIDTHS)):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeMode.Interactive)
        for column, width in enumerate(self._saved_widths()):
            self.setColumnWidth(column, width)
        header.sectionResized.connect(self._remember_widths)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)

    @staticmethod
    def _saved_widths():
        saved = settings.get(SETTINGS_KEY, "column_widths", "")
        try:
            widths = [int(w) for w in saved.split(",")]
        except (AttributeError, ValueError):
            return DEFAULT_WIDTHS
        return widths if len(widths) == len(DEFAULT_WIDTHS) else DEFAULT_WIDTHS

    def _remember_widths(self, column, _old, _new):
        if column < len(DEFAULT_WIDTHS):  # Type just fills what's left
            widths = ",".join(str(self.columnWidth(c)) for c in range(len(DEFAULT_WIDTHS)))
            settings.set(SETTINGS_KEY, "column_widths", widths)

    def dropEvent(self, event):
        # Don't call super: the tree is rebuilt from disk instead.
        srcs = self.window.selected_paths()
        if not srcs:
            return
        Indicator = QtWidgets.QAbstractItemView.DropIndicatorPosition
        position = self.dropIndicatorPosition()
        target_item = self.itemAt(event.position().toPoint())
        target = target_item.data(0, PATH_ROLE) if target_item else None

        if not target or position == Indicator.OnViewport:
            directory, index = self.window.root_dir(), None
        elif position == Indicator.OnItem and os.path.isdir(target):
            directory, index = target, None
        else:
            # Above or below an item (or onto a file): its folder, next to it.
            parent = target_item.parent()
            directory = parent.data(0, PATH_ROLE) if parent else self.window.root_dir()
            index = (parent or self.invisibleRootItem()).indexOfChild(target_item)
            if position != Indicator.AboveItem:
                index += 1
        if not directory:
            return
        try:
            logic.place(srcs, directory, index)
        except Exception as e:
            _warn(str(e))
        self.window.populate()


class _NameDialog(QtWidgets.QDialog):
    """Asks for a name, with one button per extension.

    ``on_create(name, ext)`` may raise; the dialog then warns and stays open.
    """

    def __init__(self, parent, title, choices, on_create):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedWidth(300)
        self._on_create = on_create

        layout = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Name:"))
        self.name = QtWidgets.QLineEdit()
        row.addWidget(self.name)
        layout.addLayout(row)

        buttons = QtWidgets.QHBoxLayout()
        for i, (label, ext) in enumerate(choices):
            btn = QtWidgets.QPushButton(label)
            btn.clicked.connect(lambda _=False, ext=ext: self._create(ext))
            if i == 0:
                # Enter picks the first choice.
                btn.setDefault(True)
            buttons.addWidget(btn)
        layout.addLayout(buttons)
        self.name.setFocus()

    def _create(self, ext):
        try:
            self._on_create(self.name.text(), ext)
        except Exception as e:
            _warn(str(e))
            return
        self.accept()


class _PanelDialog(QtWidgets.QDialog):
    """Non-modal window showing the :class:`products.Panel` that ``make_panel()`` returns.

    Rebuilt after every button press so it shows the item's new state.
    ``path`` is the item the Run and Show Log buttons act on, if any.
    """

    def __init__(self, window, title, make_panel, path=None):
        super().__init__(window)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(title)
        self.setMinimumWidth(320)
        self._window = window
        self._make_panel = make_panel
        self._path = path
        self._body = QtWidgets.QVBoxLayout(self)
        self._build()

    def _build(self):
        while self._body.count():
            widget = self._body.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        try:
            panel = self._make_panel()
        except Exception as e:
            # The file was moved or deleted while the window was open.
            _warn(str(e))
            self.close()
            return
        if panel.toggles:
            checklist = QtWidgets.QListWidget()
            height = 2 * checklist.frameWidth()
            for toggle in panel.toggles:
                row = QtWidgets.QWidget()
                row.setToolTip(toggle.tooltip)
                layout = QtWidgets.QHBoxLayout(row)
                layout.setContentsMargins(4, 1, 4, 1)
                box = QtWidgets.QCheckBox(toggle.label)
                box.setChecked(toggle.checked)
                box.toggled.connect(lambda on, t=toggle: self._toggled(t, on))
                layout.addWidget(box)
                layout.addStretch()
                if toggle.edit:
                    edit = QtWidgets.QToolButton(text="?")
                    edit.setToolTip(toggle.edit.label)
                    edit.clicked.connect(lambda _=False, a=toggle.edit: self._press(a))
                    layout.addWidget(edit)
                item = QtWidgets.QListWidgetItem()
                item.setFlags(QtCore.Qt.ItemFlag.NoItemFlags)  # the checkbox does the clicking
                item.setSizeHint(row.sizeHint())
                checklist.addItem(item)
                checklist.setItemWidget(item, row)
                height += row.sizeHint().height()
            checklist.setFixedHeight(height)  # every row shows, no scroll bar
            self._body.addWidget(checklist)
        for line in panel.info:
            label = QtWidgets.QLabel(line)
            label.setWordWrap(True)
            self._body.addWidget(label)
        for action in panel.actions:
            btn = QtWidgets.QPushButton(action.label)
            btn.clicked.connect(lambda _=False, a=action: self._press(a))
            self._body.addWidget(btn)
        if panel.run_buttons and self._path:
            buttons = QtWidgets.QWidget()  # a widget, so the next rebuild removes it
            layout = QtWidgets.QHBoxLayout(buttons)
            layout.setContentsMargins(0, 8, 0, 0)
            run = QtWidgets.QPushButton("Run")
            run.clicked.connect(self._run)
            layout.addWidget(run)
            show_log = QtWidgets.QPushButton("Show Log")
            show_log.clicked.connect(lambda: self._window._show_log(self._path))
            if not runlog.exists(self._path):
                show_log.setEnabled(False)
                show_log.setToolTip("Not run yet")
            layout.addWidget(show_log)
            self._body.addWidget(buttons)

    def _run(self):
        self._window._run([self._path])
        self._build()  # Show Log is enabled once there is a log

    def _press(self, action):
        self._window._do(action.fn, action.confirm)
        self._window.populate()  # the version column may have changed
        self._build()

    def _toggled(self, toggle, on):
        self._window._do(lambda: toggle.fn(on))
        self._window.populate()
        self._build()  # also puts the box back if the change failed


class _LogDialog(QtWidgets.QDialog):
    """Non-modal window showing the log of an item's last run (see runlog),
    warnings in yellow and errors in red. :meth:`reload` re-reads it."""

    def __init__(self, window, path):
        super().__init__(window)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(f"Log of {os.path.basename(path)}")
        self.resize(640, 400)
        self._path = path
        layout = QtWidgets.QVBoxLayout(self)
        self._text = QtWidgets.QPlainTextEdit(readOnly=True)
        self._text.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self._text.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont))
        layout.addWidget(self._text)
        self.reload()

    def reload(self):
        self._text.clear()
        lines = runlog.read(self._path)
        if not lines:
            self._text.setPlainText("No log: this item hasn't been run yet.")
            return
        cursor = self._text.textCursor()
        default = self._text.palette().color(QtGui.QPalette.ColorRole.Text)
        for i, (level, line) in enumerate(lines):
            fmt = QtGui.QTextCharFormat()
            fmt.setForeground(LOG_COLORS.get(level, default))
            cursor.insertText(line if i == 0 else f"\n{line}", fmt)
        self._text.moveCursor(QtGui.QTextCursor.MoveOperation.Start)


class AssemblerWindow(ToolWindow):
    TITLE = "Kaiju Assembler"

    def build_ui(self):
        style = self.style()

        top = QtWidgets.QHBoxLayout()
        self.search = QtWidgets.QLineEdit(placeholderText="Search...")
        self.search.textChanged.connect(self._apply_filter)
        refresh_btn = QtWidgets.QPushButton()
        refresh_btn.setFixedSize(28, 28)
        refresh_btn.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_BrowserReload))
        refresh_btn.setToolTip("Refresh file list and clear run colors")
        refresh_btn.clicked.connect(self._refresh)
        self.browse_btn = QtWidgets.QPushButton()
        self.browse_btn.setFixedSize(28, 28)
        self.browse_btn.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DirIcon))
        self.browse_btn.clicked.connect(self._browse)
        top.addWidget(self.search)
        top.addWidget(refresh_btn)
        top.addWidget(self.browse_btn)
        self.layout.addLayout(top)
        self._root = ""
        # Path -> status from the latest run; cleared by refresh and by a new run.
        self._status = {}
        # Paths picked by Copy; Paste copies them again from disk.
        self._clipboard = []
        # (kind, path) -> open panel window, so opening it again raises it.
        self._panels = {}
        # Versioned files in the tree, so the Version column updates (e.g. shows
        # "v003*") as soon as one is saved, without a refresh.
        self._watcher = QtCore.QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)

        self.tree = _AssemblerTree(self)
        # Double-clicking a folder opens it in Explorer, so it doesn't also
        # expand or collapse it; the arrow still does that.
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        for keys, fn in (
            (QtGui.QKeySequence.StandardKey.Copy, self._copy),
            (QtGui.QKeySequence.StandardKey.Paste, lambda: self._paste(self.tree.currentItem())),
        ):
            shortcut = QtGui.QShortcut(keys, self.tree)
            shortcut.setContext(QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(fn)
        self.layout.addWidget(self.tree)

        root = settings.get(SETTINGS_KEY, "root_dir", "")
        self._set_root(root if root and os.path.isdir(root) else "")
        if self._root:
            self.populate()
        else:
            self._placeholder("Click the folder button to select a snippets folder")

    # -- tree -------------------------------------------------------------

    def root_dir(self):
        return self._root

    def _set_root(self, root):
        self._root = root
        self.browse_btn.setToolTip(
            f"Change snippets folder\n{root}" if root else "Select snippets folder"
        )

    def populate(self):
        root = self.root_dir()
        if not root or not os.path.isdir(root):
            self._placeholder("Invalid folder selected")
            return
        settings.set(SETTINGS_KEY, "root_dir", root)

        self.tree.clear()
        if self._watcher.files():
            self._watcher.removePaths(self._watcher.files())
        entries = logic.scan(root)
        if not entries:
            self._placeholder(f"No {', '.join(products.extensions())} files found")
            return
        self._add_entries(self.tree.invisibleRootItem(), entries)
        self.tree.expandAll()
        self._apply_filter(self.search.text())

    def _icon(self, name):
        pixmap = getattr(QtWidgets.QStyle.StandardPixmap, name, None) if name else None
        return self.style().standardIcon(pixmap) if pixmap is not None else None

    def _add_entries(self, parent, entries, inside_disabled=False):
        for entry in entries:
            product = entry.product
            item = QtWidgets.QTreeWidgetItem(parent, [entry.label, entry.version_label or "", entry.type_label])
            item.setData(0, PATH_ROLE, entry.path)
            item.setToolTip(2, entry.name)
            if product and product.versioned:
                self._show_version(item)
                if not entry.is_dir:
                    self._watcher.addPath(entry.path)
            icon = self._icon(product.icon) if product else None
            if icon:
                item.setIcon(0, icon)
            disabled = not entry.enabled and product and product.can_disable
            if disabled:
                font = item.font(0)
                font.setStrikeOut(True)
                item.setFont(0, font)
                item.setForeground(0, DISABLED_COLOR)
                item.setToolTip(0, "Disabled: skipped when its folder runs")
            elif inside_disabled:
                item.setForeground(0, DISABLED_COLOR)
                item.setToolTip(0, "In a disabled folder: skipped when its folder runs")
            self._show_status(item)
            if entry.is_dir:
                self._add_entries(item, entry.children, inside_disabled or bool(disabled))

    def _show_version(self, item):
        """Fill the Version column: orange if not the latest, ``*`` if unpublished."""
        version, latest = versions.tree_label(item.data(0, PATH_ROLE))
        item.setText(1, version)
        item.setData(1, QtCore.Qt.ItemDataRole.ForegroundRole, None if latest else OLD_VERSION_COLOR)
        tips = []
        if not latest:
            tips.append("Not the latest version")
        if version.endswith("*"):
            tips.append("Has changes not published yet")
        item.setToolTip(1, "\n".join(tips))

    def _on_file_changed(self, path):
        # Editors may still be writing, or save by replacing the file (which
        # drops it from the watcher): look a moment later, and watch it again.
        QtCore.QTimer.singleShot(200, lambda: self._update_version(path))

    def _update_version(self, path):
        if os.path.isfile(path) and path not in self._watcher.files():
            self._watcher.addPath(path)
        item = self._find_item(path)
        # Folders above it too: their versions depend on their items'.
        while item:
            self._show_version(item)
            item = item.parent()

    def _show_status(self, item):
        status = self._status.get(item.data(0, PATH_ROLE))
        color = STATUS_COLORS.get(status)
        if color:
            item.setForeground(0, color)
        if status in STATUS_TIPS:
            item.setToolTip(0, STATUS_TIPS[status])

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

    def _set_status(self, path, status):
        self._status[path] = status
        item = self._find_item(path)
        if item:
            self._show_status(item)
            # The run blocks the UI thread; paint now so "running" shows.
            # repaint() rather than processEvents() so clicks can't land mid-run.
            self.tree.viewport().repaint()

    def selected_paths(self):
        """Paths of the visible selected items, in tree order."""
        paths = []

        def visit(item):
            for i in range(item.childCount()):
                child = item.child(i)
                if child.isHidden():
                    continue
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

    def _apply_filter(self, text):
        def visit(item):
            child_match = False
            for i in range(item.childCount()):
                child_match = visit(item.child(i)) or child_match
            show = child_match or logic.matches(item.text(0), text)
            item.setHidden(not show)
            if show and child_match and text:
                item.setExpanded(True)
            return show

        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            visit(root.child(i))

    def _browse(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Snippets Folder", self.root_dir() or os.path.expanduser("~")
        )
        if folder:
            self._set_root(os.path.normpath(folder))
            self.populate()

    # -- actions ----------------------------------------------------------

    def _on_double_click(self, item, _column):
        path = item.data(0, PATH_ROLE)
        if not path or not os.path.exists(path):
            return
        product = products.product_for(path)
        if not product:
            return
        if product.utility:
            self._do(lambda: logic.open_utility(product, path))
            return
        if product.panel(path) is None:
            self._do(lambda: product.open(path))
            return
        self._show_info(product, path)

    def _show_info(self, product, path):
        title = os.path.basename(path)
        self._show_panel(
            ("product", path), title, None, lambda: _PanelDialog(self, title, lambda: product.panel(path), path)
        )

    def _show_versions(self, path):
        title = f"Versions of {os.path.basename(path)}"
        self._show_panel(("versions", path), title, lambda: versions.panel(path))

    def _show_log(self, path):
        self._show_panel(("log", path), None, None, lambda: _LogDialog(self, path))

    def _reload_logs(self, paths):
        """Re-read the open Show Log windows of ``paths``, after they ran."""
        for path in paths:
            dialog = self._panels.get(("log", path))
            if dialog is not None:
                dialog.reload()

    def _show_panel(self, key, title, make_panel, make_dialog=None):
        dialog = self._panels.get(key)
        if dialog is None:
            dialog = make_dialog() if make_dialog else _PanelDialog(self, title, make_panel)
            self._panels[key] = dialog
            dialog.destroyed.connect(lambda _=None, k=key: self._panels.pop(k, None))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _do(self, fn, confirm=None):
        """Call a product action; warn on errors, show any message it returns.

        With ``confirm``, ask it as a yes/no question first.
        """
        if confirm:
            Button = QtWidgets.QMessageBox.StandardButton
            answer = QtWidgets.QMessageBox.question(self, "Confirm", confirm, Button.Yes | Button.No, Button.No)
            if answer != Button.Yes:
                return
        try:
            message = fn()
        except Exception as e:
            log.exception("Assembler action failed")
            _warn(str(e))
            return
        if message:
            _notify(message)

    def _on_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        path = item.data(0, PATH_ROLE) if item else None
        if path:
            is_file = os.path.isfile(path)
            directory = os.path.dirname(path) if is_file else path
        else:
            directory = self.root_dir()
            if not directory or not os.path.isdir(directory):
                return
            is_file = False

        steps, toggles = [], []
        for selected in self.selected_paths():
            owner = products.product_for(selected)
            if owner and owner.runnable and os.path.isfile(selected):
                steps.append(selected)
            if owner and owner.can_disable:
                toggles.append(selected)

        menu = QtWidgets.QMenu(self)
        product = products.product_for(path) if path else None
        if product:
            for action in product.actions(path):
                menu.addAction(action.label, lambda a=action: self._do_and_refresh(a))
        if steps:
            label = "Run" if len(steps) == 1 else f"Run {len(steps)} Selected"
            menu.addAction(label, lambda: self._run(steps))
        if product and product.runnable and is_file:
            show_log = menu.addAction("Show Log", lambda: self._show_log(path))
            if not runlog.exists(path):
                show_log.setEnabled(False)
                show_log.setText("Show Log (not run yet)")
        if not is_file:
            if path:
                menu.addAction(f"Run '{os.path.basename(directory)}'", lambda: self._run_folder(directory))
            plan_menu = menu.addMenu("Build")
            # A folder's plan holds the folder itself; the whole tree's, just its contents.
            plan_menu.addAction("Export...", lambda: self._export_plan(directory, include_folder=bool(path)))
            plan_menu.addAction("Import...", lambda: self._import_plan(directory))
        if toggles:
            enabled = [logic.is_enabled(p) for p in toggles]
            if any(enabled):
                menu.addAction("Disable", lambda: self._set_enabled(toggles, False))
            if not all(enabled):
                menu.addAction("Enable", lambda: self._set_enabled(toggles, True))
        if product and product.versioned:
            menu.addSeparator()
            menu.addAction("Publish", lambda: self._publish(path))
            self._add_versions_menu(menu.addMenu("Versions"), path)
        menu.addSeparator()

        new_menu = menu.addMenu("New")
        for entry in products.new_menu():
            if entry is None:
                new_menu.addSeparator()
            else:
                owner, creator = entry
                # "&&" keeps Qt from reading the "&" in "Sets & Layers" as a shortcut key.
                label = creator.label.replace("&", "&&")
                new_menu.addAction(label, lambda o=owner, c=creator: self._create(o, c, directory))

        menu.addSeparator()
        if self.selected_paths():
            menu.addAction("Copy", self._copy)
        if self._clipboard:
            menu.addAction("Paste", lambda: self._paste(item))

        if path:
            menu.addSeparator()
            menu.addAction("Rename", lambda: self._rename(path))
            menu.addAction("Delete", lambda: self._delete(path))

        if product and logic.has_info(product):
            menu.addSeparator()
            menu.addAction("Info", lambda: self._show_info(product, path))

        menu.exec(self.tree.mapToGlobal(pos))

    def _add_versions_menu(self, submenu, path):
        """The newest versions, the current one checked; picking one restores it."""
        status = versions.menu_status(path)
        if status:
            submenu.addAction(status).setEnabled(False)
        items, more = versions.menu(path)
        for entry in items:
            action = submenu.addAction(entry.label)
            if entry.current:
                action.setCheckable(True)
                action.setChecked(True)
                action.setToolTip("Current version")
            else:
                action.triggered.connect(lambda _=False, a=entry.action: self._do_and_refresh(a))
        if more:
            submenu.addSeparator()
            submenu.addAction("Show More...", lambda: self._show_versions(path))
        if versions.can_compare(path):
            entries = versions.compare_menu(path)
            submenu.addSeparator()
            compare_menu = submenu.addMenu("Compare With")
            compare_menu.setEnabled(bool(entries))
            for label, number in entries:
                compare_menu.addAction(label, lambda n=number: self._show_compare(path, n))
        submenu.setToolTipsVisible(True)

    def _show_compare(self, path, number):
        title = f"Compare {os.path.basename(path)}"
        self._show_panel(("compare", path, number), title, lambda: versions.compare_panel(path, number))

    def _do_and_refresh(self, action):
        self._do(action.fn, action.confirm)
        self.populate()

    def _publish(self, path):
        problems = versions.publish_problems(path)
        if problems:
            QtWidgets.QMessageBox.information(self, f"Can't Publish {os.path.basename(path)}", "\n".join(problems))
            return
        warnings = versions.publish_warnings(path)
        if warnings:
            Button = QtWidgets.QMessageBox.StandardButton
            answer = QtWidgets.QMessageBox.question(
                self,
                f"Publish {os.path.basename(path)}?",
                "\n".join(warnings) + "\n\nPublish anyway?",
                Button.Yes | Button.No,
                Button.No,
            )
            if answer != Button.Yes:
                return
        self._do_and_refresh(versions.publish_action(path))

    def _refresh(self):
        self._status.clear()
        self.populate()

    def _run(self, paths, report_title=None):
        """Run ``paths``; with ``report_title``, show a build report after."""
        self._refresh()
        recorder = report.Recorder(paths, forward=self._set_status)
        try:
            logic.run_steps(paths, on_status=recorder)
        except logic.StepError as e:
            log.exception("Step %s failed", e.path)
            done = paths.index(e.path)
            ran = f" ({done} ran before it and stay applied)" if done else ""
            _warn(f"Failed to run {e}{ran}. Right-click it > Show Log for details.")
            return
        finally:
            self._reload_logs(paths)
            if report_title:
                self._show_report(report_title, recorder.results)
        warned = [p for p in paths if self._status.get(p) == logic.WARNING]
        if warned:
            names = ", ".join(os.path.basename(p) for p in warned)
            _warn(f"Ran with warnings: {names}. Right-click > Show Log to see them.")
        elif len(paths) > 1:
            _notify(f"Ran {len(paths)} steps")

    def _run_folder(self, folder):
        paths = logic.collect_steps(folder)
        if not paths:
            _warn("Nothing enabled to run in this folder.")
            return
        self._run(paths, report_title=f"Build Report: {os.path.basename(folder)}")

    def _show_report(self, title, results):
        """Show the build report, replacing the one from the last run."""
        old = getattr(self, "_report", None)
        if old is not None:
            try:
                old.close()
            except RuntimeError:  # already closed and deleted
                pass
        self._report = ReportDialog(self, title, results, self._show_log)
        self._report.show()
        self._report.raise_()

    def _set_enabled(self, paths, enabled):
        try:
            for path in paths:
                logic.set_enabled(path, enabled)
        except Exception as e:
            _warn(f"Failed to update: {e}")
        self.populate()

    def _plan_dir(self):
        saved = settings.get(SETTINGS_KEY, "plan_dir", "")
        return saved if saved and os.path.isdir(saved) else self.root_dir()

    def _export_plan(self, directory, include_folder=False):
        name = os.path.basename(directory) or "build"
        target, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export Build Plan", os.path.join(self._plan_dir(), f"{name}.json"), _PLAN_FILTER
        )
        if not target:
            return
        settings.set(SETTINGS_KEY, "plan_dir", os.path.dirname(target))
        try:
            plan.save_plan(directory, target, include_folder)
        except Exception as e:
            log.exception("Build plan export failed")
            _warn(f"Failed to export the build plan: {e}")
            return
        _notify(f"Exported the build plan of {name} to {os.path.basename(target)}")

    def _import_plan(self, directory):
        source, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Import Build Plan", self._plan_dir(), _PLAN_FILTER)
        if not source:
            return
        settings.set(SETTINGS_KEY, "plan_dir", os.path.dirname(source))
        try:
            created = plan.import_plan(plan.load_plan(source), directory)
        except Exception as e:
            log.exception("Build plan import failed")
            # Problems can be a long list: show them in a box, not the status line.
            QtWidgets.QMessageBox.warning(self, "Can't Import Build Plan", str(e))
            return
        self.populate()
        _notify(f"Imported {len(created)} item{'s' if len(created) != 1 else ''} from {os.path.basename(source)}")

    def _create(self, product, creator, directory):
        title = f"New {creator.label}"

        def create(name, ext):
            path = creator.fn(directory, name, ext)
            self.populate()
            if creator.open_after:
                self._do(lambda: product.open(path))
            elif os.path.isfile(path):
                _notify(f"Added {os.path.basename(path)}")

        if creator.choices:
            _NameDialog(self, title, creator.choices, create).exec()
            return
        name, ok = QtWidgets.QInputDialog.getText(self, title, "Name:")
        if not ok or not name:
            return
        try:
            create(name, None)
        except Exception as e:
            _warn(f"Failed to create: {e}")

    def _copy(self):
        paths = self.selected_paths()
        if paths:
            self._clipboard = paths

    def _paste(self, item):
        """Paste into the folder ``item`` is, or below the file ``item`` is;
        at the end of the snippets folder when ``item`` is ``None``."""
        if not self._clipboard:
            return
        target = item.data(0, PATH_ROLE) if item else None
        if target and os.path.isdir(target):
            directory, index = target, None
        elif target:
            parent = item.parent()
            directory = parent.data(0, PATH_ROLE) if parent else self.root_dir()
            index = (parent or self.tree.invisibleRootItem()).indexOfChild(item) + 1
        else:
            directory, index = self.root_dir(), None
        if not directory or not os.path.isdir(directory):
            return
        try:
            new = logic.paste_paths(self._clipboard, directory, index)
        except Exception as e:
            _warn(f"Failed to paste: {e}")
            return
        finally:
            self.populate()
        _notify(f"Pasted {os.path.basename(new[0])}" if len(new) == 1 else f"Pasted {len(new)} items")

    def _rename(self, path):
        current = os.path.basename(path)
        if os.path.isfile(path):
            current = os.path.splitext(current)[0]
        name, ok = QtWidgets.QInputDialog.getText(self, "Rename", "Name:", text=current)
        if not ok or not name:
            return
        try:
            logic.rename_path(path, name)
        except Exception as e:
            _warn(f"Failed to rename: {e}")
        self.populate()

    def _delete(self, path):
        product = products.product_for(path)
        kind = product.name.lower() if product else "item"
        if os.path.isdir(path):
            kind += " and everything in it"
        answer = QtWidgets.QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete this {kind}?\n\n{os.path.basename(path)}",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            logic.delete_path(path)
        except Exception as e:
            _warn(f"Failed to delete: {e}")
        self.populate()
