import os

from maya import cmds
from PySide6 import QtCore, QtWidgets

from kaiju_suite.core.log import get_logger
from kaiju_suite.core.selection import selected, short_name
from kaiju_suite.tools.guide_module_editor import logic
from kaiju_suite.ui import icons
from kaiju_suite.ui.base_window import ToolWindow

log = get_logger(__name__)

_EMPTY = "Double-click a Guide item in the Assembler to edit it here."
_SIGNED = [("+X", "x"), ("+Y", "y"), ("+Z", "z"), ("-X", "-x"), ("-Y", "-y"), ("-Z", "-z")]
# Moving guides in Maya tells the window nothing: look at them this often.
_REFRESH_MS = 1000


def _warn(message):
    cmds.warning(f"Kaiju Guide Module Editor: {message}")


def _say(message):
    cmds.inViewMessage(assistMessage=message, position="topCenter", fade=True)


class GuideModuleEditorWindow(ToolWindow):
    """Edits one guide module file at a time, through its guides in the
    scene: the guides are the unsaved edits, Save writes their layout to the
    file and Revert puts them back as the file has them."""

    TITLE = "Kaiju Guide Module Editor"

    def build_ui(self):
        self.path = None
        self.guide_module = None
        self._loaded = None  # the layout as last loaded or saved
        self._tracked = None  # UUID of the top group of the guides being edited

        self.header = QtWidgets.QLabel(_EMPTY)
        self.header.setWordWrap(True)
        self.layout.addWidget(self.header)

        guides_box = QtWidgets.QGroupBox("Guides in the Scene")
        guides_row = QtWidgets.QHBoxLayout(guides_box)
        self.guides_line = QtWidgets.QLineEdit(readOnly=True)
        self.guides_line.setPlaceholderText("Not in the scene")
        self.guides_line.setToolTip("The guides this file is edited through. Save reads them; Revert moves them.")
        guides_row.addWidget(self.guides_line, 1)
        self.pick_button = QtWidgets.QToolButton(text="<<")
        self.pick_button.setToolTip("Edit the selected guides (any guide, guide group or joint of them).")
        self.pick_button.clicked.connect(self._pick)
        self.pick_button.setEnabled(False)
        guides_row.addWidget(self.pick_button)
        self.layout.addWidget(guides_box)

        self.form_box = QtWidgets.QGroupBox("Layout")
        self.form = form = QtWidgets.QFormLayout(self.form_box)
        self.name_label = QtWidgets.QLabel()
        self.name_label.setToolTip("The guides' name: their guides and joints are named after it (<name>_01_jnt...).")
        self.count = QtWidgets.QSpinBox(minimum=0, maximum=100, keyboardTracking=False)
        self.count.setToolTip(
            "How many guides go between the start and end guides.\n"
            "Changing it makes the middle guides again, evenly between start and end."
        )
        self.count.valueChanged.connect(self._on_count)
        form.addRow("Name", self.name_label)
        form.addRow("# Mid", self.count)
        # One Aim and Up row pair per part of the guide module (see logic.fields):
        # [(part, label, aim combo, up combo)], made again when the parts change.
        self._axis_rows = []
        self.form_box.setVisible(False)
        self.layout.addWidget(self.form_box)

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.layout.addWidget(self.status)

        scene_row = QtWidgets.QHBoxLayout()
        self.build_button = self._button(
            "Build",
            "Build the file's guides, with joints that follow them live. If Delete left\n"
            "their joints, the guides go back on those joints, where they are now.",
            self._build,
            "build",
        )
        self.delete_button = self._button(
            "Delete",
            "Delete the guides. Their joints stay where they are, cut loose, with plain\n"
            "translate and joint orient values; Build puts guides back on them.",
            self._delete,
            "delete",
        )
        scene_row.addWidget(self.build_button)
        scene_row.addWidget(self.delete_button)
        self.layout.addLayout(scene_row)

        file_row = QtWidgets.QHBoxLayout()
        self.save_button = self._button("Save", "Write the guides' layout, as they are, to the file.", self._save)
        self.revert_button = self._button(
            "Revert", "Throw away unsaved edits: put the guides back as the file has them.", self._revert
        )
        file_row.addWidget(self.save_button)
        file_row.addWidget(self.revert_button)
        self.layout.addLayout(file_row)
        self.layout.addStretch()

        self._watcher = QtCore.QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._timer = QtCore.QTimer(self, interval=_REFRESH_MS)
        self._timer.timeout.connect(self._refresh)
        self._refresh()

    def _combo(self, part, tip):
        combo = QtWidgets.QComboBox()
        combo.setToolTip(tip)
        for label, value in _SIGNED:
            combo.addItem(label, value)
        combo.currentIndexChanged.connect(lambda *_: self._on_axes(part))
        return combo

    def _set_axis_rows(self, axes):
        """Make the Aim and Up rows for ``axes`` (see logic.fields), unless
        the form already has them."""
        if [(a, b) for a, b, _, _ in self._axis_rows] == [(e["part"], e["label"]) for e in axes]:
            return
        for _, _, aim, up in self._axis_rows:
            self.form.removeRow(aim)
            self.form.removeRow(up)
        self._axis_rows = []
        for entry in axes:
            part, label = entry["part"], entry["label"]
            whose = f"of the {label.lower()}'s joints " if label else ""
            aim = self._combo(part, f"The axis {whose}that points at the next joint.")
            up = self._combo(
                part, f"The axis {whose}that points towards the up guide's side, in the {label.lower() or 'chain'}'s plane."
            )
            prefix = f"{label} " if label else ""
            self.form.addRow(f"{prefix}Aim", aim)
            self.form.addRow(f"{prefix}Up", up)
            self._axis_rows.append((part, label, aim, up))

    def _button(self, name, tip, action, icon=None):
        button = QtWidgets.QPushButton(name)
        if icon:
            # A push button keeps its icon and label centered as it stretches.
            button.setIcon(icons.icon(f"guide_module_editor_{icon}.svg"))
            button.setIconSize(QtCore.QSize(20, 20))
        button.setToolTip(tip)
        button.clicked.connect(action)
        button.setEnabled(False)
        return button

    # -- opening ------------------------------------------------------------

    def open_file(self, path):
        path = os.path.normpath(path)
        if self.path and path != self.path and self._dirty() and not self._settle_unsaved():
            return
        self._load(path)

    def _load(self, path):
        try:
            guide_module, layout = logic.load(path)
        except (OSError, ValueError, LookupError) as e:
            _warn(str(e))
            return
        if self._watcher.files():
            self._watcher.removePaths(self._watcher.files())
        self.path, self.guide_module, self._loaded, self._tracked = path, guide_module, layout, None
        self._watcher.addPath(path)
        self.form_box.setVisible(logic.fields(guide_module, layout) is not None)
        self._refresh()
        self._timer.start()

    def _settle_unsaved(self):
        """Ask what to do with unsaved edits before leaving them. ``False`` to stay."""
        Button = QtWidgets.QMessageBox.StandardButton
        answer = QtWidgets.QMessageBox.question(
            self,
            "Unsaved Edits",
            f"The guides of {os.path.basename(self.path)} differ from the file. Save them first?",
            Button.Save | Button.Discard | Button.Cancel,
            Button.Save,
        )
        if answer == Button.Save:
            return self._save()
        return answer == Button.Discard

    # -- the guides in the scene -------------------------------------------

    def _group(self):
        """The top group of the guides being edited, or ``None``."""
        return logic.node_of(self._tracked)

    def _track(self, group):
        self._tracked = logic.uuid_of(group) if group else None
        self._refresh()

    def _scene_layout(self, group):
        try:
            return self.guide_module.layout(group)
        except ValueError:
            return None  # e.g. guides deleted by hand

    def _dirty(self):
        group = self._group() if self.guide_module else None
        layout = self._scene_layout(group) if group else None
        return layout is not None and layout != self._loaded

    def _refresh(self):
        """Show the file and its guides as they are now."""
        if self.guide_module is None or not self.isVisible():
            return
        group = self._group()
        if group is None:
            group = logic.find_guides(self.guide_module, self._loaded)
            self._tracked = logic.uuid_of(group) if group else None
        scene = self._scene_layout(group) if group else None
        if scene is None:
            group = None
        dirty = scene is not None and scene != self._loaded

        name = os.path.basename(self.path)
        marker = "  (unsaved)" if dirty else ""
        self.header.setText(f"<b>{name}</b> — {self.guide_module.name}{marker}")
        self.guides_line.setText(short_name(group) if group else "")
        self._show_fields(scene or self._loaded, editable=group is not None)
        for button, enabled in (
            (self.pick_button, True),
            (self.build_button, group is None),
            (self.delete_button, group is not None),
            (self.save_button, group is not None),
            (self.revert_button, dirty),
        ):
            button.setEnabled(enabled)

        if group is None:
            self.status.setText(
                "The guides aren't in the scene. Build makes them from the file, or select them and click <<."
            )
            self.status.setStyleSheet("")
        elif dirty:
            text = "The guides differ from the file: Save writes them to it, Revert puts them back."
            if scene["name"] != self._loaded.get("name"):
                text += f"\nThese guides are {scene['name']}; the file's are {self._loaded.get('name')}."
            self.status.setText(text)
            self.status.setStyleSheet("color: #e0a040;")
        else:
            self.status.setText("The guides match the file.")
            self.status.setStyleSheet("color: #70c070;")

    def _show_fields(self, layout, editable):
        shown = logic.fields(self.guide_module, layout)
        if shown is None:
            return
        self.name_label.setText(shown["name"])
        has_count = "count" in shown
        self.form.setRowVisible(self.count, has_count)
        if has_count and not self.count.hasFocus():  # don't overwrite a number being typed
            self.count.blockSignals(True)
            self.count.setValue(shown["count"])
            self.count.blockSignals(False)
        self._set_axis_rows(shown["axes"])
        combos = []
        for (_, _, aim, up), entry in zip(self._axis_rows, shown["axes"]):
            for key, combo in (("aim", aim), ("up", up)):
                combo.blockSignals(True)  # filling in mustn't turn the guides
                combo.setCurrentIndex(max(combo.findData(entry[key]), 0))
                combo.blockSignals(False)
                combos.append(combo)
        for field in [self.count] + combos:
            field.setEnabled(editable)

    # -- editing ------------------------------------------------------------

    def _on_count(self, value):
        group = self._group()
        if group is None:
            return
        try:
            self._track(logic.set_count(group, int(value)))
        except ValueError as e:
            _warn(str(e))
            self._refresh()

    def _on_axes(self, part):
        """Turn ``part``'s joints to its chosen axes. Quiet while its two
        combos share an axis."""
        group = self._group()
        if group is None:
            return
        aim, up = next((a, u) for p, _, a, u in self._axis_rows if p == part)
        try:
            logic.set_guide_axes(self.guide_module, group, part, aim.currentData(), up.currentData())
        except ValueError:
            return
        self._refresh()

    def _pick(self):
        try:
            self._track(logic.pick_guides(self.guide_module, selected()))
        except ValueError as e:
            _warn(str(e))

    def _build(self):
        try:
            group = logic.build(self.guide_module, self._loaded)
        except ValueError as e:
            _warn(str(e))
            return
        self._track(group)
        _say(f"Guides built for {short_name(group)}.")

    def _delete(self):
        group = self._group()
        if group is None:
            return
        try:
            joints = logic.delete_guides(group)
        except ValueError as e:
            _warn(str(e))
            return
        self._track(None)
        if joints:
            cmds.select(joints[0])
        _say(f"Guides deleted; {len(joints)} joints extracted.")

    # -- saving -------------------------------------------------------------

    def _save(self):
        group = self._group()
        if group is None:
            _warn("No guides to save. Build them, or select them and click <<.")
            return False
        try:
            self._loaded = logic.save(self.path, self.guide_module, group)
        except (OSError, ValueError) as e:
            _warn(f"Couldn't save {os.path.basename(self.path)}: {e}")
            return False
        self._refresh()
        log.info("Saved %s", self.path)
        return True

    def _revert(self):
        group = self._group()
        if group is None:
            return
        try:
            self._track(logic.revert(self.guide_module, group, self._loaded))
        except ValueError as e:
            _warn(str(e))

    def _on_file_changed(self, path):
        # Saves may replace the file, which drops it from the watcher: look a
        # moment later, and watch it again.
        QtCore.QTimer.singleShot(200, lambda: self._reload_changed(path))

    def _reload_changed(self, path):
        """Take the file's new layout (e.g. a version was restored). The
        guides in the scene stay as they are, so no edit is lost: if they now
        differ, Revert puts them back as the file has them."""
        if path != self.path or not os.path.isfile(path):
            return
        if path not in self._watcher.files():
            self._watcher.addPath(path)
        try:
            guide_module, layout = logic.load(path)
        except (OSError, ValueError, LookupError):
            return
        if guide_module is self.guide_module and layout == self._loaded:
            return  # our own save, or nothing that matters changed
        if guide_module is not self.guide_module:
            self._tracked = None
        self.guide_module, self._loaded = guide_module, layout
        self.form_box.setVisible(logic.fields(guide_module, layout) is not None)
        self._refresh()
