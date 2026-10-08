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


def _warn(message):
    cmds.warning(f"Kaiju Assembler: {message}")


def _notify(message):
    log.info(message)
    cmds.inViewMessage(assistMessage=message, position="topCenter", fade=True)


class _AssemblerTree(QtWidgets.QTreeWidget):
    """Tree whose drag/drop moves files on disk, then refreshes."""

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDropMode.InternalMove)

    def dropEvent(self, event):
        # Don't call super: the tree is rebuilt from disk instead.
        source = self.currentItem()
        src = source.data(0, PATH_ROLE) if source else None
        if not src:
            return
        target_item = self.itemAt(event.position().toPoint())
        target = target_item.data(0, PATH_ROLE) if target_item else self.window.root_dir()
        if not target:
            return
        try:
            logic.move_path(src, target)
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
        folder_btn = QtWidgets.QPushButton()
        folder_btn.setFixedSize(28, 28)
        folder_btn.setIcon(style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DirIcon))
        folder_btn.setToolTip("Show or hide the folder setting")
        folder_btn.clicked.connect(lambda: self.dir_row.setVisible(not self.dir_row.isVisible()))
        top.addWidget(self.search)
        top.addWidget(refresh_btn)
        top.addWidget(folder_btn)
        self.layout.addLayout(top)

        self.dir_row = QtWidgets.QWidget()
        dir_layout = QtWidgets.QHBoxLayout(self.dir_row)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        self.dir_edit = QtWidgets.QLineEdit(placeholderText="Select snippets folder...")
        self.dir_edit.editingFinished.connect(self.populate)
        browse_btn = QtWidgets.QPushButton("Browse")
        browse_btn.clicked.connect(self._browse)
        dir_layout.addWidget(self.dir_edit)
        dir_layout.addWidget(browse_btn)
        self.dir_row.setVisible(False)
        self.layout.addWidget(self.dir_row)

        self.tree = _AssemblerTree(self)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.layout.addWidget(self.tree)

        root = settings.get(SETTINGS_KEY, "root_dir", "")
        if root and os.path.isdir(root):
            self.dir_edit.setText(root)
            self.populate()
        else:
            self.dir_row.setVisible(True)
            self._placeholder("Click 'Browse' to select a folder")

    # -- tree -------------------------------------------------------------

    def root_dir(self):
        return self.dir_edit.text().strip()

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
            elif entry.ext in COLORS:
                item.setForeground(0, COLORS[entry.ext])

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
            self.dir_edit.setText(os.path.normpath(folder))
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

        menu = QtWidgets.QMenu(self)
        if is_file:
            ext = logic.ext_of(path)
            if ext in logic.SCRIPT_EXTS:
                menu.addAction("Open in Script Editor", lambda: self._open_script(path))
                menu.addAction("Run Script", lambda: self._run_script(path))
            else:
                menu.addAction("Import Scene", lambda: self._import_scene(path))
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

    def _run_script(self, path):
        try:
            logic.run_script(path)
        except Exception as e:
            log.exception("Script %s failed", path)
            _warn(f"Failed to run {os.path.basename(path)}: {e}")

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
