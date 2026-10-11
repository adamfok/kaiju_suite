import os

from maya import cmds
from PySide6 import QtCore, QtGui, QtWidgets

from kaiju_suite.core import settings
from kaiju_suite.tools.asset_library import logic
from kaiju_suite.ui.base_window import ToolWindow

_ICON = 96
_ALL_TYPES = "All types"
_ALL_TAGS = "All tags"


def _warn(message):
    cmds.warning(f"Kaiju Asset Library: {message}")


def _placeholder(name):
    """An icon with the asset's initial, for assets without a thumbnail."""
    pixmap = QtGui.QPixmap(_ICON, _ICON)
    pixmap.fill(QtGui.QColor(60, 60, 60))
    painter = QtGui.QPainter(pixmap)
    painter.setPen(QtGui.QColor(160, 160, 160))
    font = painter.font()
    font.setPixelSize(_ICON // 2)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), QtCore.Qt.AlignCenter, name[:1].upper())
    painter.end()
    return QtGui.QIcon(pixmap)


def _icon(asset):
    if asset.thumbnail:
        pixmap = QtGui.QPixmap(asset.thumbnail)
        if not pixmap.isNull():
            return QtGui.QIcon(pixmap.scaled(_ICON, _ICON, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
    return _placeholder(asset.name)


class AssetDialog(QtWidgets.QDialog):
    """Name (new assets only), type, tags and notes of an asset."""

    def __init__(self, parent, title, types, asset=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        form = QtWidgets.QFormLayout(self)
        self.name_field = None
        if asset is None:
            self.name_field = QtWidgets.QLineEdit()
            self.name_field.setPlaceholderText("letters, digits, _ and -")
            form.addRow("Name", self.name_field)
        self.type_field = QtWidgets.QComboBox(editable=True)
        self.type_field.addItems(types)
        self.type_field.setCurrentText(asset.type if asset else "")
        form.addRow("Type", self.type_field)
        self.tags_field = QtWidgets.QLineEdit(logic.format_tags(asset.tags) if asset else "")
        self.tags_field.setPlaceholderText("comma separated")
        form.addRow("Tags", self.tags_field)
        self.notes_field = QtWidgets.QPlainTextEdit(asset.notes if asset else "")
        form.addRow("Notes", self.notes_field)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self):
        return {
            "asset_type": self.type_field.currentText().strip(),
            "tags": logic.parse_tags(self.tags_field.text()),
            "notes": self.notes_field.toPlainText(),
        }


class AssetLibraryWindow(ToolWindow):
    TITLE = "Kaiju Asset Library"

    def build_ui(self):
        self._assets = []
        self.layout.addLayout(self._library_row())
        self.current_label = QtWidgets.QLabel()
        self.layout.addWidget(self.current_label)
        self.layout.addLayout(self._filter_row())

        self.asset_list = QtWidgets.QListWidget()
        self.asset_list.setViewMode(QtWidgets.QListView.IconMode)
        self.asset_list.setIconSize(QtCore.QSize(_ICON, _ICON))
        self.asset_list.setGridSize(QtCore.QSize(_ICON + 24, _ICON + 28))
        self.asset_list.setResizeMode(QtWidgets.QListView.Adjust)
        self.asset_list.setMovement(QtWidgets.QListView.Static)
        self.asset_list.itemClicked.connect(lambda *_: self._make_current())
        self.asset_list.currentItemChanged.connect(lambda *_: self._show_details())
        self.layout.addWidget(self.asset_list, 1)

        self.details = QtWidgets.QLabel()
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.layout.addWidget(self.details)
        self.layout.addLayout(self._action_rows())
        self._load_libraries()

    # -- layout ----------------------------------------------------------------

    def _library_row(self):
        row = QtWidgets.QHBoxLayout()
        self.library_label = QtWidgets.QLabel()
        self.library_combo = QtWidgets.QComboBox()
        self.library_combo.currentIndexChanged.connect(lambda *_: self._library_changed())
        add = QtWidgets.QPushButton("Add Library...")
        add.clicked.connect(self._add_library)
        self.remove_library_button = QtWidgets.QPushButton("Remove Library")
        self.remove_library_button.clicked.connect(self._remove_library)
        row.addWidget(self.library_label, 1)
        row.addWidget(self.library_combo, 1)
        row.addWidget(add)
        row.addWidget(self.remove_library_button)
        return row

    def _filter_row(self):
        row = QtWidgets.QHBoxLayout()
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search names, tags and notes")
        self.search.textChanged.connect(lambda *_: self._fill_list())
        self.type_filter = QtWidgets.QComboBox()
        self.type_filter.currentIndexChanged.connect(lambda *_: self._fill_list())
        self.tag_filter = QtWidgets.QComboBox()
        self.tag_filter.currentIndexChanged.connect(lambda *_: self._fill_list())
        row.addWidget(self.search, 1)
        row.addWidget(self.type_filter)
        row.addWidget(self.tag_filter)
        return row

    def _action_rows(self):
        rows = QtWidgets.QVBoxLayout()
        scene = QtWidgets.QHBoxLayout()
        self.import_button = QtWidgets.QPushButton("Import")
        self.import_button.clicked.connect(lambda: self._run(logic.import_asset, "Imported"))
        self.reference_button = QtWidgets.QPushButton("Reference")
        self.reference_button.clicked.connect(lambda: self._run(logic.reference_asset, "Referenced"))
        self.open_button = QtWidgets.QPushButton("Open")
        self.open_button.clicked.connect(self._open)
        for button in (self.import_button, self.reference_button, self.open_button):
            scene.addWidget(button)
        manage = QtWidgets.QHBoxLayout()
        self.new_button = QtWidgets.QPushButton("New Asset...")
        self.new_button.clicked.connect(self._new_asset)
        self.edit_button = QtWidgets.QPushButton("Edit...")
        self.edit_button.clicked.connect(self._edit_asset)
        self.folder_button = QtWidgets.QPushButton("Show in Folder")
        self.folder_button.clicked.connect(self._show_in_folder)
        for button in (self.new_button, self.edit_button, self.folder_button):
            manage.addWidget(button)
        rows.addLayout(scene)
        rows.addLayout(manage)
        return rows

    # -- libraries -------------------------------------------------------------

    def _load_libraries(self, select=None):
        found = logic.libraries()
        select = select or settings.get(logic.SETTINGS_KEY, "library", "")
        self.library_combo.blockSignals(True)
        self.library_combo.clear()
        for path in found:
            self.library_combo.addItem(os.path.basename(os.path.normpath(path)) or path, path)
            self.library_combo.setItemData(self.library_combo.count() - 1, path, QtCore.Qt.ToolTipRole)
        index = next((i for i, path in enumerate(found) if os.path.normcase(path) == os.path.normcase(select or "")), 0)
        self.library_combo.setCurrentIndex(index if found else -1)
        self.library_combo.blockSignals(False)
        # The drop-down only appears once there's more than one library.
        self.library_combo.setVisible(len(found) > 1)
        self.library_label.setVisible(len(found) <= 1)
        self.library_label.setText(found[0] if found else "No library yet: click Add Library... to pick a folder.")
        self.remove_library_button.setEnabled(bool(found))
        self.new_button.setEnabled(bool(found))
        self._library_changed()

    def library(self):
        return self.library_combo.currentData() or ""

    def _library_changed(self):
        if self.library():
            settings.set(logic.SETTINGS_KEY, "library", self.library())
        self._rescan()

    def _add_library(self):
        start = self.library() or cmds.workspace(query=True, rootDirectory=True)
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Add Library Folder", start)
        if folder:
            folder = os.path.normpath(folder)
            logic.add_library(folder)
            self._load_libraries(select=folder)

    def _remove_library(self):
        path = self.library()
        if not path:
            return
        answer = QtWidgets.QMessageBox.question(
            self, "Remove Library", f"Remove {path} from the list?\nNo files are deleted."
        )
        if answer == QtWidgets.QMessageBox.Yes:
            logic.remove_library(path)
            self._load_libraries()

    # -- the list --------------------------------------------------------------

    def _rescan(self, select=None):
        self._assets = logic.scan(self.library()) if self.library() else []
        for combo, everything, values in (
            (self.type_filter, _ALL_TYPES, logic.types_in_use(self._assets)),
            (self.tag_filter, _ALL_TAGS, logic.tags_in_use(self._assets)),
        ):
            kept = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems([everything] + values)
            combo.setCurrentText(kept if kept in values else everything)
            combo.blockSignals(False)
        self._fill_list(select)

    def _fill_list(self, select=None):
        selected = select or (self.selected().path if self.selected() else None)
        current = logic.current()
        selected = selected or (current.path if current else None)
        asset_type = self.type_filter.currentText()
        tag = self.tag_filter.currentText()
        shown = logic.filter_assets(
            self._assets,
            text=self.search.text(),
            asset_type=None if asset_type == _ALL_TYPES else asset_type,
            tag=None if tag == _ALL_TAGS else tag,
        )
        self.asset_list.blockSignals(True)
        self.asset_list.clear()
        for asset in shown:
            item = QtWidgets.QListWidgetItem(_icon(asset), asset.name)
            item.setData(QtCore.Qt.UserRole, asset)
            item.setToolTip(asset.path)
            self.asset_list.addItem(item)
            if selected and os.path.normcase(asset.path) == os.path.normcase(selected):
                self.asset_list.setCurrentItem(item)
        self.asset_list.blockSignals(False)
        self._show_details()

    def selected(self):
        item = self.asset_list.currentItem()
        return item.data(QtCore.Qt.UserRole) if item else None

    def _show_details(self):
        current = logic.current()
        self.current_label.setText(f"Current asset: <b>{current.name}</b>" if current else "No current asset")
        self.current_label.setToolTip(f"ASSET = {current.path}" if current else "ASSET isn't set by the Asset Library")
        asset = self.selected()
        published = logic.latest_publish(asset.path) if asset else None
        for button in (self.import_button, self.reference_button, self.open_button):
            button.setEnabled(bool(published))
        self.edit_button.setEnabled(bool(asset))
        self.folder_button.setEnabled(bool(asset))
        if asset is None:
            self.details.setText("")
            return
        lines = [
            f"<b>{asset.name}</b>" + (f" ({asset.type})" if asset.type else ""),
            f"Tags: {logic.format_tags(asset.tags)}" if asset.tags else "",
            asset.notes.replace("\n", "<br>") if asset.notes else "",
            f"Latest publish: {os.path.basename(published)}" if published else "Nothing published yet",
            "Has an Assembler build" if logic.has_build(asset.path) else "",
        ]
        self.details.setText("<br>".join(line for line in lines if line))

    # -- actions ---------------------------------------------------------------

    def _make_current(self):
        asset = self.selected()
        if asset is None:
            return
        try:
            logic.set_current(asset.path)
        except (OSError, ValueError) as e:
            _warn(str(e))
        self._show_details()

    def _run(self, action, verb):
        asset = self.selected()
        if asset is None:
            return
        try:
            action(asset.path)
        except Exception as e:
            _warn(str(e))
            return
        print(f"Kaiju Asset Library: {verb} {asset.name}.")

    def _open(self):
        if cmds.file(query=True, modified=True):
            answer = QtWidgets.QMessageBox.question(
                self, "Open Asset", "The current scene has unsaved changes. Open anyway and lose them?"
            )
            if answer != QtWidgets.QMessageBox.Yes:
                return
        self._run(logic.open_asset, "Opened")

    def _new_asset(self):
        dialog = AssetDialog(self, "New Asset", logic.types_in_use(self._assets))
        if not dialog.exec():
            return
        try:
            asset = logic.create_asset(self.library(), dialog.name_field.text().strip(), **dialog.values())
        except (OSError, ValueError) as e:
            _warn(str(e))
            return
        logic.set_current(asset.path)
        self._rescan(select=asset.path)

    def _edit_asset(self):
        asset = self.selected()
        if asset is None:
            return
        dialog = AssetDialog(self, f"Edit {asset.name}", logic.types_in_use(self._assets), asset)
        if not dialog.exec():
            return
        try:
            logic.update_asset(asset.path, **dialog.values())
        except (OSError, ValueError) as e:
            _warn(str(e))
            return
        self._rescan(select=asset.path)

    def _show_in_folder(self):
        asset = self.selected()
        if asset is not None:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(asset.path))
