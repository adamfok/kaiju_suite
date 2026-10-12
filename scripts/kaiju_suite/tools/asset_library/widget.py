import os

from maya import cmds
from PySide6 import QtCore, QtGui, QtWidgets

from kaiju_suite.tools.asset_library import logic
from kaiju_suite.ui.base_window import ToolWindow

_ICON = 96


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


class AssetLibraryWindow(ToolWindow):
    TITLE = "Kaiju Asset Library"

    def build_ui(self):
        self._assets = []
        self.layout.addLayout(self._library_row())
        self.current_label = QtWidgets.QLabel()
        self.layout.addWidget(self.current_label)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search names")
        self.search.textChanged.connect(lambda *_: self._fill_list())
        self.layout.addWidget(self.search)

        self.asset_list = QtWidgets.QListWidget()
        self.asset_list.setViewMode(QtWidgets.QListView.IconMode)
        self.asset_list.setIconSize(QtCore.QSize(_ICON, _ICON))
        self.asset_list.setGridSize(QtCore.QSize(_ICON + 24, _ICON + 28))
        self.asset_list.setResizeMode(QtWidgets.QListView.Adjust)
        self.asset_list.setMovement(QtWidgets.QListView.Static)
        self.asset_list.itemClicked.connect(lambda *_: self._make_current())
        self.asset_list.currentItemChanged.connect(lambda *_: self._show_details())
        self.asset_list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.asset_list.customContextMenuRequested.connect(self._context_menu)
        self.layout.addWidget(self.asset_list, 1)

        self.details = QtWidgets.QLabel()
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.layout.addWidget(self.details)

        update = QtWidgets.QPushButton("Update References to Latest...")
        update.setToolTip(
            "Point rigs referenced in this scene at their latest published version. "
            "References keep the version they were made with until you do."
        )
        update.clicked.connect(self._update_references)
        self.layout.addWidget(update)
        self._library_changed()

    # -- layout ----------------------------------------------------------------

    def _library_row(self):
        row = QtWidgets.QHBoxLayout()
        self.library_label = QtWidgets.QLabel()
        self.library_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        change = QtWidgets.QPushButton()
        change.setFixedSize(28, 28)
        change.setIcon(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DirIcon))
        change.setToolTip("Change Library")
        change.clicked.connect(self._change_library)
        row.addWidget(self.library_label, 1)
        row.addWidget(change)
        return row

    def _context_menu(self, pos):
        """Right-click an asset for its actions, or empty space for New Asset."""
        self.asset_list.setCurrentItem(self.asset_list.itemAt(pos))
        asset = self.selected()
        menu = QtWidgets.QMenu(self)
        if asset is not None:
            rigs = self._rigs(asset)
            published = {rig for rig in rigs if logic.latest_publish(asset.path, rig)}
            for label, slot in (
                ("Import", lambda rig, version=None: self._run(logic.import_asset, rig, "Imported", version)),
                ("Reference", lambda rig, version=None: self._run(logic.reference_asset, rig, "Referenced", version)),
                ("Open", self._open),
            ):
                self._rig_menu(menu, label, rigs, slot, published, pick_version=asset)
            menu.addSeparator()
            self._rig_menu(menu, "Open in Assembler", rigs, self._open_in_assembler)
            menu.addAction("New Rig...", self._new_rig).setToolTip(
                "Make this the Asset and add a rig (e.g. skeleton, puppet, proxy) with its own build/ and publish/ "
                "folders, its build started with a build folder holding an Output saving to publish/<rig>/"
            )
            menu.addAction("Show in Explorer", self._show_in_explorer)
            menu.addSeparator()
            menu.addAction("Thumbnail from Viewport", lambda: self._set_thumbnail(logic.capture_thumbnail)).setToolTip(
                "Save the active viewport at the current frame as the thumbnail"
            )
            menu.addAction("Thumbnail from File...", self._thumbnail_from_file)
        elif self.library():
            menu.addAction("New Asset...", self._new_asset)
        else:
            return
        menu.setToolTipsVisible(True)
        menu.exec(self.asset_list.viewport().mapToGlobal(pos))

    def _rig_menu(self, menu, label, rigs, slot, enabled=None, pick_version=None):
        """A submenu listing ``rigs``; picking one calls ``slot(rig)``. Rigs
        not in ``enabled`` (when given) are greyed out. With ``pick_version``
        (the asset), a rig with numbered versions gets its own submenu:
        Latest, then each version, calling ``slot(rig, number)``."""
        sub = menu.addMenu(label)
        if not rigs:
            sub.addAction("No rigs yet: use New Rig...").setEnabled(False)
        for rig in rigs:
            found = logic.publish_versions(pick_version.path, rig) if pick_version is not None else []
            if found:
                self._version_menu(sub, rig, found, slot)
                continue
            action = sub.addAction(rig, lambda rig=rig: slot(rig))
            if enabled is not None and rig not in enabled:
                action.setEnabled(False)
                action.setToolTip(f"Nothing published in publish/{rig}/ yet")
        sub.setToolTipsVisible(True)
        return sub

    def _version_menu(self, menu, rig, found, slot):
        sub = menu.addMenu(rig)
        latest = logic.latest_publish(self.selected().path, rig)
        pointed = next((v for v in found if latest and os.path.normcase(v.path) == os.path.normcase(latest)), None)
        sub.addAction(f"Latest ({pointed.tag})" if pointed else "Latest", lambda: slot(rig))
        sub.addSeparator()
        for version in found:
            sub.addAction(logic.version_label(version), lambda number=version.number: slot(rig, number))

    def _rigs(self, asset):
        try:
            return logic.rigs(asset.path)
        except (OSError, ValueError) as e:
            _warn(str(e))
            return []

    # -- libraries -------------------------------------------------------------

    def library(self):
        return logic.library()

    def _library_changed(self):
        path = self.library()
        self.library_label.setText(f"Library: {path}" if path else "No library yet: click the folder button to pick one.")
        self._rescan()

    def _change_library(self):
        start = self.library() or cmds.workspace(query=True, rootDirectory=True)
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Change Library", start)
        if not folder:
            return
        try:
            logic.set_library(folder)
        except OSError as e:
            _warn(str(e))
            return
        self._library_changed()

    # -- the list --------------------------------------------------------------

    def _rescan(self, select=None):
        self._assets = logic.scan(self.library()) if self.library() else []
        self._fill_list(select)

    def _fill_list(self, select=None):
        selected = select or (self.selected().path if self.selected() else None)
        current = logic.current()
        selected = selected or (current.path if current else None)
        shown = logic.filter_assets(self._assets, self.search.text())
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
        self.current_label.setText(f"Asset: <b>{current.name}</b>" if current else "Asset: none")
        self.current_label.setToolTip(f"ASSET = {current.path}" if current else "ASSET isn't set by the Asset Library")
        asset = self.selected()
        if asset is None:
            self.details.setText("")
            return
        lines = [f"<b>{asset.name}</b>"]
        rigs = self._rigs(asset)
        for rig in rigs:
            lines.append(f"{rig}: {self._published_text(asset, rig)}")
        if not rigs:
            lines.append("No rigs yet: right-click ▸ New Rig...")
        self.details.setText("<br>".join(lines))

    def _published_text(self, asset, rig):
        published = logic.latest_publish(asset.path, rig)
        if not published:
            return "nothing published"
        version = next(
            (v for v in logic.publish_versions(asset.path, rig) if os.path.normcase(v.path) == os.path.normcase(published)),
            None,
        )
        return logic.version_label(version) if version else os.path.basename(published)

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

    def _run(self, action, rig, verb, version=None):
        asset = self.selected()
        if asset is None:
            return
        try:
            action(asset.path, rig, version=version)
        except Exception as e:
            _warn(str(e))
            return
        which = f" v{version:03d}" if version is not None else ""
        print(f"Kaiju Asset Library: {verb} {asset.name} {rig}{which}.")

    def _open(self, rig, version=None):
        if cmds.file(query=True, modified=True):
            answer = QtWidgets.QMessageBox.question(
                self, "Open Asset", "The current scene has unsaved changes. Open anyway and lose them?"
            )
            if answer != QtWidgets.QMessageBox.Yes:
                return
        self._run(logic.open_asset, rig, "Opened", version)

    def _new_asset(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "New Asset", "Name (letters, digits, _ and -):")
        if not ok:
            return
        try:
            asset = logic.create_asset(self.library(), name.strip())
        except (OSError, ValueError) as e:
            _warn(str(e))
            return
        logic.set_current(asset.path)
        self._rescan(select=asset.path)

    def _new_rig(self):
        asset = self.selected()
        if asset is None:
            return
        name, ok = QtWidgets.QInputDialog.getText(
            self, "New Rig", f"Rig name for {asset.name} (letters, digits, _ and -):"
        )
        if not ok:
            return
        try:
            # Current first, so the new Output stores a $ASSET/... path.
            logic.set_current(asset.path)
            logic.add_rig(asset.path, name.strip())
        except (OSError, ValueError) as e:
            _warn(str(e))
        self._show_details()

    def _set_thumbnail(self, action, *args):
        asset = self.selected()
        if asset is None:
            return
        try:
            action(asset.path, *args)
        except Exception as e:
            _warn(str(e))
            return
        self._rescan(select=asset.path)

    def _thumbnail_from_file(self):
        asset = self.selected()
        if asset is None:
            return
        picked, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Thumbnail Image", asset.path, "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp)"
        )
        if picked:
            self._set_thumbnail(logic.set_thumbnail_from_file, picked)

    def _open_in_assembler(self, rig):
        asset = self.selected()
        if asset is None:
            return
        try:
            logic.open_in_assembler(asset.path, rig)
        except Exception as e:
            _warn(str(e))
        self._show_details()

    def _update_references(self):
        try:
            stale = [ref for ref in logic.rig_references() if ref.out_of_date]
        except Exception as e:
            _warn(str(e))
            return
        if not stale:
            QtWidgets.QMessageBox.information(self, "Update References", "Every referenced rig is at its latest version.")
            return
        listed = "\n".join(ref.label for ref in stale)
        answer = QtWidgets.QMessageBox.question(
            self, "Update References", f"Update these references to their latest version?\n\n{listed}"
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return
        try:
            updated = logic.update_all_to_latest()
        except Exception as e:
            _warn(str(e))
            return
        print(f"Kaiju Asset Library: Updated {', '.join(ref.label for ref in updated)}.")

    def _show_in_explorer(self):
        asset = self.selected()
        if asset is not None:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(asset.path))
