import os

from maya import cmds
from PySide6 import QtCore, QtGui, QtWidgets

from kaiju_suite.core import settings
from kaiju_suite.core.log import get_logger
from kaiju_suite.tools.assembler import logic, products
from kaiju_suite.ui.base_window import ToolWindow

log = get_logger(__name__)

SETTINGS_KEY = "assembler"
PATH_ROLE = QtCore.Qt.ItemDataRole.UserRole

DISABLED_COLOR = QtGui.QColor(115, 115, 115)
# Name color for the last run of each step; see logic.run_steps.
STATUS_COLORS = {
    logic.RUNNING: QtGui.QColor(230, 200, 60),
    logic.SUCCESS: QtGui.QColor(95, 190, 95),
    logic.ERROR: QtGui.QColor(225, 85, 85),
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
        self.setHeaderHidden(True)
        # Column 0: name without extension. Column 1: product type.
        self.setColumnCount(2)
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)

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

        self.tree = _AssemblerTree(self)
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
            item = QtWidgets.QTreeWidgetItem(parent, [entry.label, entry.type_label])
            item.setData(0, PATH_ROLE, entry.path)
            item.setToolTip(1, entry.name)
            product = entry.product
            icon = self._icon(product.icon) if product else None
            if icon:
                item.setIcon(0, icon)
            disabled = not entry.enabled and product and product.can_disable
            if disabled:
                font = item.font(0)
                font.setStrikeOut(True)
                item.setFont(0, font)
                item.setForeground(0, DISABLED_COLOR)
                item.setToolTip(0, "Disabled: skipped by Run All")
            elif inside_disabled:
                item.setForeground(0, DISABLED_COLOR)
                item.setToolTip(0, "In a disabled folder: skipped by Run All")
            self._show_status(item)
            if entry.is_dir:
                self._add_entries(item, entry.children, inside_disabled or bool(disabled))

    def _show_status(self, item):
        color = STATUS_COLORS.get(self._status.get(item.data(0, PATH_ROLE)))
        if color:
            item.setForeground(0, color)

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
        if not path or not os.path.isfile(path):
            return
        product = products.product_for(path)
        if product:
            self._do(lambda: product.open(path))

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
                menu.addAction(action.label, lambda a=action: self._do(a.fn, a.confirm))
        if steps:
            label = "Run" if len(steps) == 1 else f"Run {len(steps)} Selected"
            menu.addAction(label, lambda: self._run(steps))
        if not is_file:
            label = f"Run All in '{os.path.basename(directory)}'" if path else "Run All"
            menu.addAction(label, lambda: self._run_folder(directory))
        if toggles:
            enabled = [logic.is_enabled(p) for p in toggles]
            if any(enabled):
                menu.addAction("Disable", lambda: self._set_enabled(toggles, False))
            if not all(enabled):
                menu.addAction("Enable", lambda: self._set_enabled(toggles, True))
        menu.addSeparator()

        new_menu = menu.addMenu("New")
        for owner in products.all_products():
            for creator in owner.creators:
                new_menu.addAction(creator.label, lambda o=owner, c=creator: self._create(o, c, directory))

        menu.addSeparator()
        if self.selected_paths():
            menu.addAction("Copy", self._copy)
        if self._clipboard:
            menu.addAction("Paste", lambda: self._paste(item))

        if path:
            menu.addSeparator()
            menu.addAction("Rename", lambda: self._rename(path))
            menu.addAction("Delete", lambda: self._delete(path))

        menu.exec(self.tree.mapToGlobal(pos))

    def _refresh(self):
        self._status.clear()
        self.populate()

    def _run(self, paths):
        self._refresh()
        try:
            logic.run_steps(paths, on_status=self._set_status)
        except logic.StepError as e:
            log.exception("Step %s failed", e.path)
            done = paths.index(e.path)
            ran = f" ({done} ran before it and stay applied)" if done else ""
            _warn(f"Failed to run {e}{ran}")
            return
        if len(paths) > 1:
            _notify(f"Ran {len(paths)} steps")

    def _run_folder(self, folder):
        paths = logic.collect_steps(folder)
        if not paths:
            _warn("Nothing enabled to run in this folder.")
            return
        self._run(paths)

    def _set_enabled(self, paths, enabled):
        try:
            for path in paths:
                logic.set_enabled(path, enabled)
        except Exception as e:
            _warn(f"Failed to update: {e}")
        self.populate()

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
