import os

from maya import cmds
from PySide6 import QtCore, QtGui, QtWidgets

from kaiju_suite.core.log import get_logger
from kaiju_suite.tools.rig_module_editor import logic
from kaiju_suite.ui.base_window import ToolWindow

log = get_logger(__name__)

_EMPTY = "Double-click a Rig Module item in the Assembler to edit it here."


def _warn(message):
    cmds.warning(f"Kaiju Rig Module Editor: {message}")


class RigModuleEditorWindow(ToolWindow):
    """Edits one rig module file at a time. The form is built from the
    module's parameters, so every rig module gets an editor."""

    TITLE = "Kaiju Rig Module Editor"

    def build_ui(self):
        self.path = None
        self.module = None
        self._loaded = {}  # params as last loaded or saved; unknown ones kept
        self._fields = {}  # param key -> (get, set)

        self.header = QtWidgets.QLabel(_EMPTY)
        self.header.setWordWrap(True)
        self.layout.addWidget(self.header)

        self.form_box = QtWidgets.QGroupBox("Parameters")
        self.form = QtWidgets.QFormLayout(self.form_box)
        self.form_box.setVisible(False)
        self.layout.addWidget(self.form_box)

        self.problems = QtWidgets.QLabel()
        self.problems.setWordWrap(True)
        self.layout.addWidget(self.problems)

        buttons = QtWidgets.QHBoxLayout()
        self.save_button = QtWidgets.QPushButton("Save")
        self.save_button.clicked.connect(self._save)
        self.revert_button = QtWidgets.QPushButton("Revert")
        self.revert_button.setToolTip("Throw away unsaved edits and reload the file.")
        self.revert_button.clicked.connect(self._revert)
        self.check_button = QtWidgets.QPushButton("Check")
        self.check_button.setToolTip("Check the parameters against the current scene.")
        self.check_button.clicked.connect(self._update_status)
        for button in (self.save_button, self.revert_button, self.check_button):
            button.setEnabled(False)
            buttons.addWidget(button)
        self.layout.addLayout(buttons)
        self.layout.addStretch()

        self._watcher = QtCore.QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)

    # -- opening ------------------------------------------------------------

    def open_file(self, path):
        path = os.path.normpath(path)
        if self.path and path != self.path and self._dirty() and not self._settle_unsaved():
            return
        self._load(path)

    def _load(self, path):
        try:
            module, params = logic.load(path)
        except (OSError, ValueError, LookupError) as e:
            _warn(str(e))
            return
        if self._watcher.files():
            self._watcher.removePaths(self._watcher.files())
        self.path, self.module, self._loaded = path, module, dict(params)
        self._watcher.addPath(path)
        self._build_form()
        self._set_values(params)
        for button in (self.save_button, self.revert_button, self.check_button):
            button.setEnabled(True)
        self._update_status()

    def _settle_unsaved(self):
        """Ask what to do with unsaved edits before leaving them. ``False`` to stay."""
        Button = QtWidgets.QMessageBox.StandardButton
        answer = QtWidgets.QMessageBox.question(
            self,
            "Unsaved Edits",
            f"{os.path.basename(self.path)} has unsaved edits. Save them first?",
            Button.Save | Button.Discard | Button.Cancel,
            Button.Save,
        )
        if answer == Button.Save:
            return self._save()
        return answer == Button.Discard

    # -- the form -----------------------------------------------------------

    def _build_form(self):
        while self.form.rowCount():
            self.form.removeRow(0)
        self._fields = {}
        for param in self.module.params:
            widget, get, set_ = self._field(param)
            widget.setToolTip(param.tooltip)
            label = f"{param.label} *" if param.required else param.label
            self.form.addRow(label, widget)
            self._fields[param.key] = (get, set_)
        self.form_box.setVisible(True)

    def _field(self, param):
        """``(widget, get, set)`` for one parameter."""
        if param.kind == "bool":
            box = QtWidgets.QCheckBox()
            box.toggled.connect(self._on_edited)
            return box, box.isChecked, lambda v: box.setChecked(bool(v))
        if param.kind == "float":
            spin = QtWidgets.QDoubleSpinBox(minimum=-1e6, maximum=1e6, decimals=3, singleStep=0.5)
            spin.valueChanged.connect(self._on_edited)
            return spin, spin.value, lambda v: spin.setValue(float(v) if isinstance(v, (int, float)) else 0.0)
        if param.kind == "choice":
            combo = QtWidgets.QComboBox()
            combo.addItems([str(c) for c in param.choices])

            def set_choice(value):
                if combo.findText(str(value)) < 0:
                    combo.addItem(str(value))  # an unknown value stays visible, and is reported
                combo.setCurrentText(str(value))

            combo.currentTextChanged.connect(self._on_edited)
            return combo, combo.currentText, set_choice
        if param.kind == "color":
            return self._color_field()
        line = QtWidgets.QLineEdit()
        line.textChanged.connect(self._on_edited)
        if param.kind != "node":
            return line, line.text, lambda v: line.setText(str(v))
        row = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(line)
        pick = QtWidgets.QToolButton(text="<<")
        pick.setToolTip("Use the selected node.")
        pick.clicked.connect(lambda: self._pick_into(line))
        layout.addWidget(pick)
        return row, line.text, lambda v: line.setText(str(v))

    def _color_field(self):
        """A drop-down of Maya's index colors, each with its swatch."""
        combo = QtWidgets.QComboBox()
        for index in logic.COLORS:
            if index == 0:
                combo.addItem("0  None (Maya default)", 0)
                continue
            swatch = QtGui.QPixmap(16, 16)
            swatch.fill(QtGui.QColor.fromRgbF(*logic.color_rgb(index)))
            combo.addItem(QtGui.QIcon(swatch), str(index), index)

        def set_color(value):
            found = combo.findData(value)
            if found < 0:  # an unknown value stays visible, and is reported
                combo.addItem(str(value), value)
                found = combo.count() - 1
            combo.setCurrentIndex(found)

        combo.currentIndexChanged.connect(self._on_edited)
        return combo, combo.currentData, set_color

    def _pick_into(self, line):
        try:
            line.setText(logic.pick_selection())
        except ValueError as e:
            _warn(str(e))

    def _set_values(self, params):
        for key, (_get, set_) in self._fields.items():
            set_(params[key])

    def _values(self):
        values = dict(self._loaded)
        values.update({key: get() for key, (get, _set) in self._fields.items()})
        return values

    def _dirty(self):
        return self.module is not None and self._values() != self._loaded

    def _on_edited(self, *_):
        self._update_status()

    def _update_status(self):
        if self.module is None:
            return
        name = os.path.basename(self.path)
        marker = "  (unsaved)" if self._dirty() else ""
        self.header.setText(f"<b>{name}</b> — {self.module.name}{marker}")
        problems = logic.problems(self.module, self._values())
        if problems:
            self.problems.setText("Won't build yet:\n" + "\n".join(f"• {p}" for p in problems))
            self.problems.setStyleSheet("color: #e0a040;")
        else:
            self.problems.setText("Ready to build.")
            self.problems.setStyleSheet("color: #70c070;")

    # -- saving -------------------------------------------------------------

    def _save(self):
        values = self._values()
        try:
            logic.save(self.path, self.module, values)
        except OSError as e:
            _warn(f"Couldn't save {os.path.basename(self.path)}: {e}")
            return False
        self._loaded = values
        self._update_status()
        log.info("Saved %s", self.path)
        return True

    def _revert(self):
        if self.path:
            self._load(self.path)

    def _on_file_changed(self, path):
        # Saves may replace the file, which drops it from the watcher: look a
        # moment later, and watch it again.
        QtCore.QTimer.singleShot(200, lambda: self._reload_changed(path))

    def _reload_changed(self, path):
        if path != self.path or not os.path.isfile(path):
            return
        if path not in self._watcher.files():
            self._watcher.addPath(path)
        if logic.matches_file(path, self.module, self._values()):
            return  # our own save, or nothing that matters changed
        if self._dirty():
            Button = QtWidgets.QMessageBox.StandardButton
            answer = QtWidgets.QMessageBox.question(
                self,
                "Changed on Disk",
                f"{os.path.basename(path)} changed on disk (e.g. a version was restored).\n"
                "Reload it and lose your unsaved edits?",
                Button.Yes | Button.No,
                Button.No,
            )
            if answer != Button.Yes:
                return
        self._load(path)
