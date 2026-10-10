from maya import cmds
from PySide6 import QtCore, QtWidgets

from kaiju_suite.core import settings
from kaiju_suite.core.selection import selected, short_name
from kaiju_suite.tools.attribute_manager import logic
from kaiju_suite.ui.base_window import ToolWindow

SETTINGS_KEY = "attribute_manager"


def _warn(message):
    cmds.warning(f"Kaiju Attribute Manager: {message}")


def _report(result):
    if result.skipped:
        _warn("Skipped: " + "; ".join(result.skipped))


class AttributeManagerWindow(ToolWindow):
    TITLE = "Kaiju Attribute Manager"

    def build_ui(self):
        self._job = None
        self.layout.addWidget(self._list_box(), 1)
        self.layout.addWidget(self._add_box())
        self.layout.addWidget(self._presets_box())
        self._refresh()

    # -- selection tracking ---------------------------------------------------

    def showEvent(self, event):
        super().showEvent(event)
        if self._job is None:
            self._job = cmds.scriptJob(event=["SelectionChanged", self._on_selection_changed])
        self._refresh()

    def hideEvent(self, event):
        self._kill_job()
        super().hideEvent(event)

    def closeEvent(self, event):
        self._kill_job()
        super().closeEvent(event)

    def _kill_job(self):
        if self._job is not None and cmds.scriptJob(exists=self._job):
            cmds.scriptJob(kill=self._job, force=True)
        self._job = None

    def _on_selection_changed(self):
        try:
            self._refresh()
        except RuntimeError:  # The window was deleted under the job.
            self._kill_job()

    # -- layout ---------------------------------------------------------------

    def _list_box(self):
        box = QtWidgets.QGroupBox("Custom Attributes")
        layout = QtWidgets.QVBoxLayout(box)
        self.node_label = QtWidgets.QLabel()
        layout.addWidget(self.node_label)

        self.attrs = QtWidgets.QListWidget()
        self.attrs.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.attrs.setToolTip(
            "The first selected node's custom attributes, in channel box order. "
            "Buttons act on the highlighted ones, on every selected node that has them."
        )
        layout.addWidget(self.attrs)

        grid = QtWidgets.QGridLayout()
        buttons = [
            ("Move Up", "Move the highlighted attributes up one place.", lambda: self._move(-1)),
            ("Move Down", "Move the highlighted attributes down one place.", lambda: self._move(1)),
            ("Rename...", "Rename the highlighted attribute.", self._rename),
            ("Delete", "Delete the highlighted attributes, locked or connected ones too.", self._delete),
            ("Lock", "Lock the highlighted attributes.", lambda: self._lock(True)),
            ("Unlock", "Unlock the highlighted attributes.", lambda: self._lock(False)),
            ("Hide", "Hide the highlighted attributes from the channel box.", lambda: self._hide(True)),
            ("Show", "Show the highlighted attributes in the channel box, keyable.", lambda: self._hide(False)),
        ]
        for i, (label, tip, slot) in enumerate(buttons):
            button = QtWidgets.QPushButton(label)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            grid.addWidget(button, i // 4, i % 4)
        layout.addLayout(grid)
        return box

    def _add_box(self):
        box = QtWidgets.QGroupBox("Add")
        form = QtWidgets.QFormLayout(box)

        self.name = QtWidgets.QLineEdit()
        self.name.setPlaceholderText("attributeName")
        form.addRow("Name", self.name)

        self.kind = QtWidgets.QComboBox()
        self.kind.addItems(logic.KINDS)
        self.kind.setCurrentText(settings.get(SETTINGS_KEY, "kind", "float"))
        self.kind.currentTextChanged.connect(lambda *_: self._update_fields())
        form.addRow("Type", self.kind)

        range_row = QtWidgets.QHBoxLayout()
        self.use_min = QtWidgets.QCheckBox("Min")
        self.minimum = QtWidgets.QDoubleSpinBox(minimum=-1e9, maximum=1e9, decimals=3)
        self.use_max = QtWidgets.QCheckBox("Max")
        self.maximum = QtWidgets.QDoubleSpinBox(minimum=-1e9, maximum=1e9, decimals=3, value=1)
        for widget in (self.use_min, self.minimum, self.use_max, self.maximum):
            range_row.addWidget(widget)
        form.addRow("Range", range_row)

        self.default = QtWidgets.QLineEdit()
        self.default.setPlaceholderText("Default value (optional; an index for enum)")
        form.addRow("Default", self.default)

        self.enum_names = QtWidgets.QLineEdit()
        self.enum_names.setPlaceholderText("world:root:chest")
        form.addRow("Enum names", self.enum_names)

        self.keyable = QtWidgets.QCheckBox("Keyable")
        self.keyable.setToolTip("Off: shown in the channel box but not keyable.")
        self.keyable.setChecked(bool(settings.get(SETTINGS_KEY, "keyable", 1)))
        add = QtWidgets.QPushButton("Add Attribute")
        add.setToolTip("Add the attribute to every selected node.")
        add.clicked.connect(self._add)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.keyable)
        row.addStretch()
        row.addWidget(add)
        form.addRow(row)

        separator_row = QtWidgets.QHBoxLayout()
        self.separator_label = QtWidgets.QLineEdit()
        self.separator_label.setPlaceholderText("Label, e.g. IK")
        add_separator = QtWidgets.QPushButton("Add Separator")
        add_separator.setToolTip("Add a locked divider with this label to every selected node's channel box.")
        add_separator.clicked.connect(self._add_separator)
        separator_row.addWidget(self.separator_label)
        separator_row.addWidget(add_separator)
        form.addRow("Separator", separator_row)

        self._update_fields()
        return box

    def _presets_box(self):
        box = QtWidgets.QGroupBox("Presets")
        grid = QtWidgets.QGridLayout(box)
        for i, name in enumerate(logic.PRESETS):
            button = QtWidgets.QPushButton(name)
            button.setToolTip(f"{name} on every selected node.")
            button.clicked.connect(lambda _=False, name=name: self._preset(name))
            grid.addWidget(button, i // 2, i % 2)
        return box

    def _update_fields(self):
        kind = self.kind.currentText()
        numeric = kind in ("float", "int")
        for widget in (self.use_min, self.minimum, self.use_max, self.maximum):
            widget.setEnabled(numeric)
        self.enum_names.setEnabled(kind == "enum")
        self.keyable.setEnabled(kind != "string")

    # -- helpers --------------------------------------------------------------

    def _nodes(self):
        nodes = selected()
        if not nodes:
            _warn("Select the nodes first.")
        return nodes

    def _highlighted(self):
        attrs = [item.data(QtCore.Qt.UserRole) for item in self.attrs.selectedItems()]
        if not attrs:
            _warn("Highlight attributes in the list first.")
        return attrs

    def _refresh(self, keep=None):
        keep = set(keep if keep is not None else (i.data(QtCore.Qt.UserRole) for i in self.attrs.selectedItems()))
        self.attrs.clear()
        nodes = selected()
        if not nodes:
            self.node_label.setText("Nothing selected.")
            return
        extra = f" (+{len(nodes) - 1} more)" if len(nodes) > 1 else ""
        self.node_label.setText(f"{short_name(nodes[0])}{extra}")
        for attr in logic.custom_attributes(nodes[0]):
            item = QtWidgets.QListWidgetItem(f"{attr}    [{logic.describe(nodes[0], attr)}]")
            item.setData(QtCore.Qt.UserRole, attr)
            self.attrs.addItem(item)
            item.setSelected(attr in keep)

    def _run(self, func, *args, keep=None):
        try:
            result = func(*args)
        except ValueError as e:
            _warn(str(e))
            return
        _report(result)
        self._refresh(keep)

    # -- actions --------------------------------------------------------------

    def _add(self):
        nodes = self._nodes()
        if not nodes:
            return
        kind = self.kind.currentText()
        default = self.default.text().strip() or None
        if default is not None and kind != "string":
            try:
                default = {"float": float, "int": int, "enum": int}.get(kind, float)(default)
                if kind == "bool":
                    default = bool(default)
            except ValueError:
                _warn(f"The default {default!r} isn't a number.")
                return
        numeric = kind in ("float", "int")
        settings.set(SETTINGS_KEY, "kind", kind)
        settings.set(SETTINGS_KEY, "keyable", int(self.keyable.isChecked()))
        self._run(
            lambda: logic.add_attribute(
                nodes,
                self.name.text().strip(),
                kind,
                minimum=self.minimum.value() if numeric and self.use_min.isChecked() else None,
                maximum=self.maximum.value() if numeric and self.use_max.isChecked() else None,
                default=default,
                keyable=self.keyable.isChecked(),
                enum_names=self.enum_names.text().split(":") if kind == "enum" else None,
            )
        )

    def _add_separator(self):
        nodes = self._nodes()
        if nodes:
            self._run(logic.add_separator, nodes, self.separator_label.text())

    def _move(self, direction):
        nodes, attrs = self._nodes(), self._highlighted()
        if nodes and attrs:
            self._run(logic.move_attributes, nodes, attrs, direction, keep=attrs)

    def _rename(self):
        nodes, attrs = self._nodes(), self._highlighted()
        if not nodes or not attrs:
            return
        new, ok = QtWidgets.QInputDialog.getText(self, "Rename Attribute", f"New name for {attrs[0]}:", text=attrs[0])
        if ok and new.strip() and new.strip() != attrs[0]:
            self._run(logic.rename_attribute, nodes, attrs[0], new.strip(), keep=[new.strip()])

    def _delete(self):
        nodes, attrs = self._nodes(), self._highlighted()
        if not nodes or not attrs:
            return
        answer = QtWidgets.QMessageBox.question(
            self, "Delete Attributes", f"Delete {', '.join(attrs)} from {len(nodes)} node(s)?"
        )
        if answer == QtWidgets.QMessageBox.Yes:
            self._run(logic.delete_attributes, nodes, attrs)

    def _lock(self, locked):
        nodes, attrs = self._nodes(), self._highlighted()
        if nodes and attrs:
            self._run(logic.set_locked, nodes, attrs, locked)

    def _hide(self, hidden):
        nodes, attrs = self._nodes(), self._highlighted()
        if nodes and attrs:
            self._run(logic.set_hidden, nodes, attrs, hidden)

    def _preset(self, name):
        nodes = self._nodes()
        if nodes:
            self._run(logic.apply_preset, nodes, name)
