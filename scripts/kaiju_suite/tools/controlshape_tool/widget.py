import math

from maya import cmds
from PySide6 import QtCore, QtGui, QtWidgets

from kaiju_suite.core import settings
from kaiju_suite.core.colors import COLORS, color_rgb
from kaiju_suite.core.selection import selected, short_name
from kaiju_suite.tools.controlshape_tool import logic, presets
from kaiju_suite.ui.base_window import ToolWindow

SETTINGS_KEY = "controlshape_tool"
_ICON = 56
# The preview's view: turned about Y, then tilted about X, so flat shapes
# and 3D ones both read.
_TURN, _TILT = math.radians(35), math.radians(30)


def _warn(message):
    cmds.warning(f"Kaiju ControlShape Tool: {message}")


def _preview(records):
    """An icon of ``records`` drawn in a three-quarter view."""
    lines = []
    for line in presets.outline(records):
        projected = []
        for x, y, z in line:
            depth = x * math.sin(_TURN) + z * math.cos(_TURN)
            across = x * math.cos(_TURN) - z * math.sin(_TURN)
            projected.append((across, -(y * math.cos(_TILT) - depth * math.sin(_TILT))))
        lines.append(projected)
    points = [p for line in lines for p in line]
    reach = max((max(abs(a), abs(b)) for a, b in points), default=1) or 1
    scale = (_ICON / 2 - 4) / reach

    pixmap = QtGui.QPixmap(_ICON, _ICON)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setPen(QtGui.QPen(QtGui.QColor(120, 200, 255), 1.5))
    for line in lines:
        polyline = QtGui.QPolygonF([QtCore.QPointF(_ICON / 2 + a * scale, _ICON / 2 + b * scale) for a, b in line])
        painter.drawPolyline(polyline)
    painter.end()
    return QtGui.QIcon(pixmap)


def _spin(value, minimum, maximum, step, decimals=2):
    spin = QtWidgets.QDoubleSpinBox(minimum=minimum, maximum=maximum, decimals=decimals, singleStep=step)
    spin.setValue(value)
    return spin


class ControlShapeToolWindow(ToolWindow):
    TITLE = "Kaiju ControlShape Tool"

    def build_ui(self):
        self.layout.addWidget(self._library_box(), 1)
        self.layout.addWidget(self._edit_box())
        self.layout.addWidget(self._display_box())
        self._refresh()

    # -- layout ----------------------------------------------------------------

    def _library_box(self):
        box = QtWidgets.QGroupBox("Library")
        layout = QtWidgets.QVBoxLayout(box)
        self.presets = QtWidgets.QListWidget()
        self.presets.setViewMode(QtWidgets.QListView.IconMode)
        self.presets.setIconSize(QtCore.QSize(_ICON, _ICON))
        self.presets.setGridSize(QtCore.QSize(_ICON + 24, _ICON + 22))
        self.presets.setResizeMode(QtWidgets.QListView.Adjust)
        self.presets.setMovement(QtWidgets.QListView.Static)
        self.presets.setMinimumHeight(2 * (_ICON + 22) + 8)
        self.presets.itemDoubleClicked.connect(lambda *_: self._create())
        self.presets.currentItemChanged.connect(lambda *_: self._update_buttons())
        layout.addWidget(self.presets)

        options = QtWidgets.QHBoxLayout()
        self.size = _spin(settings.get(SETTINGS_KEY, "size", 1.0), 0.01, 1000, 0.5)
        self.keep_size = QtWidgets.QCheckBox("Keep size")
        self.keep_size.setToolTip("Replace scales the preset to the size of the shapes it replaces.")
        self.keep_size.setChecked(bool(settings.get(SETTINGS_KEY, "keep_size", 1)))
        options.addWidget(QtWidgets.QLabel("Size"))
        options.addWidget(self.size)
        options.addWidget(self.keep_size)
        options.addStretch()
        layout.addLayout(options)

        buttons = QtWidgets.QGridLayout()
        create = QtWidgets.QPushButton("Create")
        create.setToolTip(
            "Create a control with this shape at each selected node, or at the origin (double-click does the same)."
        )
        create.clicked.connect(self._create)
        replace = QtWidgets.QPushButton("Replace")
        replace.setToolTip("Swap the selected controls' shapes for this one, keeping their color (and size).")
        replace.clicked.connect(self._replace)
        save = QtWidgets.QPushButton("Save Selected...")
        save.setToolTip("Save the selected control's shapes as a new preset.")
        save.clicked.connect(self._save)
        self.delete_button = QtWidgets.QPushButton("Delete")
        self.delete_button.setToolTip("Delete this saved preset (built-in presets can't be deleted).")
        self.delete_button.clicked.connect(self._delete)
        buttons.addWidget(create, 0, 0)
        buttons.addWidget(replace, 0, 1)
        buttons.addWidget(save, 1, 0)
        buttons.addWidget(self.delete_button, 1, 1)
        layout.addLayout(buttons)
        return box

    def _edit_box(self):
        box = QtWidgets.QGroupBox("Edit Shapes")
        box.setToolTip("Moves the selected controls' CVs around their pivots; the controls stay where they are.")
        grid = QtWidgets.QGridLayout(box)

        self.angle = _spin(settings.get(SETTINGS_KEY, "angle", 90.0), -360, 360, 15, decimals=1)
        grid.addWidget(QtWidgets.QLabel("Rotate"), 0, 0)
        grid.addWidget(self.angle, 0, 1)
        for i, axis in enumerate("XYZ"):
            button = QtWidgets.QPushButton(axis)
            button.clicked.connect(lambda _=False, i=i: self._rotate(i))
            grid.addWidget(button, 0, 2 + i)

        self.factor = _spin(settings.get(SETTINGS_KEY, "factor", 1.25), 1.01, 10, 0.05)
        grid.addWidget(QtWidgets.QLabel("Scale"), 1, 0)
        grid.addWidget(self.factor, 1, 1)
        bigger = QtWidgets.QPushButton("Bigger")
        bigger.clicked.connect(lambda: self._scale(self.factor.value()))
        smaller = QtWidgets.QPushButton("Smaller")
        smaller.clicked.connect(lambda: self._scale(1 / self.factor.value()))
        grid.addWidget(bigger, 1, 2)
        grid.addWidget(smaller, 1, 3, 1, 2)

        self.step = _spin(settings.get(SETTINGS_KEY, "step", 0.5), 0.001, 1000, 0.1, decimals=3)
        grid.addWidget(QtWidgets.QLabel("Move"), 2, 0)
        grid.addWidget(self.step, 2, 1)
        for i, axis in enumerate("XYZ"):
            pair = QtWidgets.QHBoxLayout()
            for sign, label in ((1, f"+{axis}"), (-1, f"-{axis}")):
                button = QtWidgets.QPushButton(label)
                button.setMinimumWidth(10)
                button.clicked.connect(lambda _=False, i=i, sign=sign: self._move(i, sign))
                pair.addWidget(button)
            grid.addLayout(pair, 2, 2 + i)

        mirror = QtWidgets.QPushButton("Mirror to Opposite")
        mirror.setToolTip("Give each selected control's opposite (L_ / R_, ...) its shapes, mirrored across X.")
        mirror.clicked.connect(self._mirror)
        copy = QtWidgets.QPushButton("Copy from First")
        copy.setToolTip("Give the other selected controls the first selected control's shapes.")
        copy.clicked.connect(self._copy)
        grid.addWidget(mirror, 3, 0, 1, 2)
        grid.addWidget(copy, 3, 2, 1, 3)
        return box

    def _display_box(self):
        box = QtWidgets.QGroupBox("Color && Line Width")
        layout = QtWidgets.QVBoxLayout(box)
        swatches = QtWidgets.QGridLayout()
        swatches.setSpacing(2)
        for index in COLORS:
            button = QtWidgets.QPushButton()
            button.setFixedSize(20, 20)
            if index == 0:
                button.setText("x")
                button.setToolTip("No color override (Maya's default).")
            else:
                r, g, b = (int(c * 255) for c in color_rgb(index))
                button.setStyleSheet(f"background-color: rgb({r}, {g}, {b}); border: 1px solid #222;")
                button.setToolTip(f"Color {index}")
            button.clicked.connect(lambda _=False, index=index: self._color(index))
            swatches.addWidget(button, index // 16, index % 16)
        layout.addLayout(swatches)

        width_row = QtWidgets.QHBoxLayout()
        self.width = _spin(settings.get(SETTINGS_KEY, "width", 2.0), -1, 20, 0.5, decimals=1)
        self.width.setToolTip("-1 uses Maya's default line width.")
        set_width = QtWidgets.QPushButton("Set Line Width")
        set_width.clicked.connect(self._line_width)
        width_row.addWidget(QtWidgets.QLabel("Line width"))
        width_row.addWidget(self.width)
        width_row.addWidget(set_width)
        layout.addLayout(width_row)
        return box

    # -- library ---------------------------------------------------------------

    def _refresh(self, current=None):
        self.presets.clear()
        for name in logic.preset_names():
            try:
                records = logic.load_preset(name)
            except (OSError, ValueError, LookupError) as e:
                _warn(f"Can't read preset {name}: {e}")
                continue
            item = QtWidgets.QListWidgetItem(_preview(records), name)
            item.setToolTip(name if logic.is_built_in(name) else f"{name} (saved preset)")
            self.presets.addItem(item)
            if name == current:
                self.presets.setCurrentItem(item)
        if self.presets.currentItem() is None and self.presets.count():
            self.presets.setCurrentRow(0)
        self._update_buttons()

    def _preset(self):
        item = self.presets.currentItem()
        if item is None:
            _warn("Pick a preset in the library first.")
            return None
        return logic.load_preset(item.text())

    def _update_buttons(self):
        item = self.presets.currentItem()
        self.delete_button.setEnabled(bool(item) and not logic.is_built_in(item.text()))

    def _create(self):
        records = self._preset()
        if records is None:
            return
        settings.set(SETTINGS_KEY, "size", self.size.value())
        name = self.presets.currentItem().text()
        nodes = logic.transforms(selected())
        made = [
            logic.create_control(f"{short_name(node) if node else name}_ctrl", records, self.size.value(), at=node)
            for node in nodes or [None]
        ]
        cmds.select(made)

    def _replace(self):
        records = self._preset()
        nodes = self._transforms()
        if records is not None and nodes:
            settings.set(SETTINGS_KEY, "keep_size", int(self.keep_size.isChecked()))
            logic.replace_shapes(nodes, records, keep_size=self.keep_size.isChecked())

    def _save(self):
        nodes = logic.controls(selected())
        if not nodes:
            _warn("Select the control whose shapes to save.")
            return
        name, ok = QtWidgets.QInputDialog.getText(self, "Save Control Shape", "Preset name:")
        if not ok:
            return
        try:
            logic.save_preset(nodes[0], name.strip())
        except ValueError as e:
            if not str(e).startswith("There's already"):
                _warn(str(e))
                return
            answer = QtWidgets.QMessageBox.question(self, "Save Control Shape", f"Replace the preset {name.strip()}?")
            if answer != QtWidgets.QMessageBox.Yes:
                return
            logic.save_preset(nodes[0], name.strip(), overwrite=True)
        self._refresh(current=name.strip())

    def _delete(self):
        item = self.presets.currentItem()
        if item is None or logic.is_built_in(item.text()):
            return
        answer = QtWidgets.QMessageBox.question(self, "Delete Control Shape", f"Delete the preset {item.text()}?")
        if answer == QtWidgets.QMessageBox.Yes:
            logic.delete_preset(item.text())
            self._refresh()

    # -- editing ---------------------------------------------------------------

    def _transforms(self):
        nodes = logic.transforms(selected())
        if not nodes:
            _warn("Select the controls first.")
        return nodes

    def _controls(self):
        nodes = logic.controls(selected())
        if not nodes:
            _warn("Select controls with curve shapes first.")
        return nodes

    def _rotate(self, axis):
        nodes = self._controls()
        if nodes:
            settings.set(SETTINGS_KEY, "angle", self.angle.value())
            degrees = [0.0, 0.0, 0.0]
            degrees[axis] = self.angle.value()
            logic.rotate_shapes(nodes, degrees)

    def _scale(self, factor):
        nodes = self._controls()
        if nodes:
            settings.set(SETTINGS_KEY, "factor", self.factor.value())
            logic.scale_shapes(nodes, factor)

    def _move(self, axis, sign):
        nodes = self._controls()
        if nodes:
            settings.set(SETTINGS_KEY, "step", self.step.value())
            offset = [0.0, 0.0, 0.0]
            offset[axis] = sign * self.step.value()
            logic.translate_shapes(nodes, offset)

    def _mirror(self):
        nodes = self._controls()
        if nodes:
            result = logic.mirror_shapes(nodes)
            if result.skipped:
                _warn(f"Skipped: {', '.join(result.skipped)}")

    def _copy(self):
        nodes = logic.transforms(selected())
        if len(nodes) < 2 or not logic.controls(nodes[:1]):
            _warn("Select the control to copy from first, then the controls to copy onto.")
            return
        logic.copy_shapes(nodes[0], nodes[1:])

    def _color(self, index):
        nodes = self._controls()
        if nodes:
            logic.set_color(nodes, index)

    def _line_width(self):
        nodes = self._controls()
        if nodes:
            settings.set(SETTINGS_KEY, "width", self.width.value())
            logic.set_line_width(nodes, self.width.value())
