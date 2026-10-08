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
        refresh_btn.setToolTip("Refresh file list")
        refresh_btn.clicked.connect(self.populate)
        self.browse_btn = QtWidgets.QPushButton()
        self.browse_btn.setFixedSize(28, 28)
        self.browse_btn.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DirIcon))
        self.browse_btn.clicked.connect(self._browse)
        top.addWidget(self.search)
        top.addWidget(refresh_btn)
        top.addWidget(self.browse_btn)
        self.layout.addLayout(top)
        self._root = ""

        self.tree = _AssemblerTree(self)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
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

    def _add_entries(self, parent, entries):
        for entry in entries:
            item = QtWidgets.QTreeWidgetItem(parent, [entry.name])
            item.setData(0, PATH_ROLE, entry.path)
            product = entry.product
            icon = self._icon(product.icon) if product else None
            if icon:
                item.setIcon(0, icon)
            if entry.is_dir:
                self._add_entries(item, entry.children)
            elif not entry.enabled and product and product.runnable:
                font = item.font(0)
                font.setStrikeOut(True)
                item.setFont(0, font)
                item.setForeground(0, DISABLED_COLOR)
                item.setToolTip(0, "Disabled: skipped by Run All")
            elif product and product.color_for(entry.path):
                item.setForeground(0, QtGui.QColor(*product.color_for(entry.path)))

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

        steps = []
        for selected in self.selected_paths():
            owner = products.product_for(selected)
            if owner and owner.runnable and os.path.isfile(selected):
                steps.append(selected)

        menu = QtWidgets.QMenu(self)
        product = products.product_for(path) if path else None
        if product:
            for action in product.actions(path):
                menu.addAction(action.label, lambda a=action: self._do(a.fn, a.confirm))
        if steps:
            label = "Run" if len(steps) == 1 else f"Run {len(steps)} Selected"
            menu.addAction(label, lambda: self._run(steps))
            enabled = [logic.is_enabled(p) for p in steps]
            if any(enabled):
                menu.addAction("Disable", lambda: self._set_enabled(steps, False))
            if not all(enabled):
                menu.addAction("Enable", lambda: self._set_enabled(steps, True))
        if not is_file:
            label = f"Run All in '{os.path.basename(directory)}'" if path else "Run All"
            menu.addAction(label, lambda: self._run_folder(directory))
        menu.addSeparator()

        new_menu = menu.addMenu("New")
        for owner in products.all_products():
            for creator in owner.creators:
                new_menu.addAction(creator.label, lambda o=owner, c=creator: self._create(o, c, directory))

        if path:
            menu.addSeparator()
            menu.addAction("Remove", lambda: self._remove(path))

        menu.exec(self.tree.mapToGlobal(pos))

    def _run(self, paths):
        try:
            logic.run_steps(paths)
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

    def _remove(self, path):
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
