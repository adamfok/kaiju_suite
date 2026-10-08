import os

from maya import cmds
from PySide6 import QtCore, QtGui, QtWidgets

from kaiju_suite.core import settings
from kaiju_suite.core.log import get_logger
from kaiju_suite.tools.assembler import logic
from kaiju_suite.ui.base_window import ToolWindow

log = get_logger(__name__)

SETTINGS_KEY = "assembler"
PATH_ROLE = QtCore.Qt.ItemDataRole.UserRole

COLORS = {
    ".py": QtGui.QColor(128, 200, 255),
    ".mel": QtGui.QColor(255, 200, 128),
    ".ma": QtGui.QColor(255, 230, 100),
    ".mb": QtGui.QColor(255, 230, 100),
}
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
        self.search = QtWidgets.QLineEdit(placeholderText="Search scripts...")
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
            self._placeholder("No .py, .mel, .ma, or .mb files found")
            return
        self._add_entries(self.tree.invisibleRootItem(), entries)
        self.tree.expandAll()
        self._apply_filter(self.search.text())

    def _add_entries(self, parent, entries):
        dir_icon = self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DirIcon)
        for entry in entries:
            item = QtWidgets.QTreeWidgetItem(parent, [entry.name])
            item.setData(0, PATH_ROLE, entry.path)
            if entry.is_dir:
                item.setIcon(0, dir_icon)
                self._add_entries(item, entry.children)
            elif not entry.enabled and entry.ext in logic.SCRIPT_EXTS:
                font = item.font(0)
                font.setStrikeOut(True)
                item.setFont(0, font)
                item.setForeground(0, DISABLED_COLOR)
                item.setToolTip(0, "Disabled: skipped by Run All")
            elif entry.ext in COLORS:
                item.setForeground(0, COLORS[entry.ext])

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
        if logic.ext_of(path) in logic.SCENE_EXTS:
            self._import_scene(path)
        else:
            self._open_script(path)

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

        scripts = [p for p in self.selected_paths() if logic.ext_of(p) in logic.SCRIPT_EXTS and os.path.isfile(p)]

        menu = QtWidgets.QMenu(self)
        if is_file:
            ext = logic.ext_of(path)
            if ext in logic.SCRIPT_EXTS:
                menu.addAction("Open in Script Editor", lambda: self._open_script(path))
            else:
                menu.addAction("Import Scene", lambda: self._import_scene(path))
        if scripts:
            label = "Run Script" if len(scripts) == 1 else f"Run {len(scripts)} Selected Scripts"
            menu.addAction(label, lambda: self._run(scripts))
            enabled = [logic.is_enabled(p) for p in scripts]
            if any(enabled):
                menu.addAction("Disable", lambda: self._set_enabled(scripts, False))
            if not all(enabled):
                menu.addAction("Enable", lambda: self._set_enabled(scripts, True))
        if not is_file:
            label = f"Run All in '{os.path.basename(directory)}'" if path else "Run All Scripts"
            menu.addAction(label, lambda: self._run_folder(directory))
        menu.addSeparator()

        menu.addAction("Add Script...", lambda: self._add_script(directory))
        menu.addAction("Export Selected...", lambda: self._export_selected(directory))
        menu.addSeparator()
        menu.addAction("Add Folder...", lambda: self._add_folder(directory))

        if path:
            menu.addSeparator()
            menu.addAction("Remove", lambda: self._remove(path))

        menu.exec(self.tree.mapToGlobal(pos))

    def _open_script(self, path):
        try:
            logic.open_in_script_editor(path)
        except Exception as e:
            _warn(f"Failed to open script: {e}")

    def _run(self, paths):
        try:
            logic.run_scripts(paths)
        except logic.ScriptRunError as e:
            log.exception("Script %s failed", e.path)
            done = paths.index(e.path)
            ran = f" ({done} ran before it; one undo reverts them)" if done else ""
            _warn(f"Failed to run {e}{ran}")
            return
        if len(paths) > 1:
            _notify(f"Ran {len(paths)} scripts")

    def _run_folder(self, folder):
        paths = logic.collect_scripts(folder)
        if not paths:
            _warn("No enabled scripts to run in this folder.")
            return
        self._run(paths)

    def _set_enabled(self, paths, enabled):
        try:
            for path in paths:
                logic.set_enabled(path, enabled)
        except Exception as e:
            _warn(f"Failed to update: {e}")
        self.populate()

    def _import_scene(self, path):
        try:
            logic.import_scene(path)
        except Exception as e:
            _warn(f"Failed to import scene: {e}")
            return
        _notify(f"Imported {os.path.basename(path)}")

    def _add_script(self, directory):
        def create(name, ext):
            path = logic.create_script(directory, name, ext)
            self.populate()
            self._open_script(path)

        _NameDialog(self, "Add New Script", [("Python (.py)", ".py"), ("MEL (.mel)", ".mel")], create).exec()

    def _export_selected(self, directory):
        def create(name, ext):
            path = logic.create_scene(directory, name, ext)
            self.populate()
            _notify(f"Added selection as {os.path.basename(path)}")

        choices = [("Maya Binary (.mb)", ".mb"), ("Maya Ascii (.ma)", ".ma")]
        _NameDialog(self, "Export Selected", choices, create).exec()

    def _add_folder(self, directory):
        name, ok = QtWidgets.QInputDialog.getText(self, "New Folder", "Folder Name:")
        if not ok or not name:
            return
        try:
            logic.create_folder(directory, name)
        except Exception as e:
            _warn(f"Failed to create folder: {e}")
            return
        self.populate()

    def _remove(self, path):
        if os.path.isdir(path):
            kind = "folder and everything in it"
        elif logic.ext_of(path) in logic.SCENE_EXTS:
            kind = "scene"
        else:
            kind = "script"
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
