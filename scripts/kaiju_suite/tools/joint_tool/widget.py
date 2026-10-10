from maya import cmds
from PySide6 import QtWidgets

from kaiju_suite.core import settings
from kaiju_suite.core.selection import selected
from kaiju_suite.tools.joint_tool import logic
from kaiju_suite.ui.base_window import ToolWindow

SETTINGS_KEY = "joint_tool"
_SIGNED = [("+X", "x"), ("+Y", "y"), ("+Z", "z"), ("-X", "-x"), ("-Y", "-y"), ("-Z", "-z")]


def _warn(message):
    cmds.warning(f"Kaiju Joint Tool: {message}")


def _plural(count, word="joint"):
    return f"{count} {word}{'s' if count != 1 else ''}"


class JointToolWindow(ToolWindow):
    TITLE = "Kaiju Joint Tool"

    def build_ui(self):
        self.layout.addWidget(self._orient_box())
        self.layout.addWidget(self._mirror_box())
        self.layout.addWidget(self._insert_box())
        self.layout.addWidget(self._display_box())
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.layout.addWidget(self.status)
        self.layout.addStretch()

    # -- layout ----------------------------------------------------------------

    def _combo(self, name, default, tip):
        combo = QtWidgets.QComboBox()
        combo.setToolTip(tip)
        for label, value in _SIGNED:
            combo.addItem(label, value)
        combo.setCurrentIndex(max(combo.findData(settings.get(SETTINGS_KEY, name, default)), 0))
        combo.currentIndexChanged.connect(lambda *_: settings.set(SETTINGS_KEY, name, combo.currentData()))
        return combo

    def _check(self, label, name, default, tip):
        box = QtWidgets.QCheckBox(label)
        box.setToolTip(tip)
        box.setChecked(bool(settings.get(SETTINGS_KEY, name, int(default))))
        box.toggled.connect(lambda on: settings.set(SETTINGS_KEY, name, bool(on)))
        return box

    def _orient_box(self):
        box = QtWidgets.QGroupBox("Orient")
        layout = QtWidgets.QVBoxLayout(box)
        self.aim = self._combo("aim", "x", "The axis that points at the child joint.")
        self.up = self._combo("up", "y", "The axis that points as close to the world up as it can.")
        self.world_up = self._combo("world_up", "y", "The world direction the up axis points towards.")
        axes = QtWidgets.QGridLayout()
        for column, (label, combo) in enumerate((("Aim", self.aim), ("Up", self.up), ("World Up", self.world_up))):
            axes.addWidget(QtWidgets.QLabel(label), 0, column)
            axes.addWidget(combo, 1, column)
        layout.addLayout(axes)

        options = QtWidgets.QHBoxLayout()
        self.children_check = self._check("Children", "children", True, "Orient every joint below the selected ones too.")
        self.zero_end = self._check(
            "Zero end joints", "zero_end", True, "End joints get a zero joint orient, lining up with their parent."
        )
        options.addWidget(self.children_check)
        options.addWidget(self.zero_end)
        options.addStretch()
        layout.addLayout(options)

        buttons = QtWidgets.QHBoxLayout()
        orient = QtWidgets.QPushButton("Orient")
        orient.setToolTip("Orient the selected joints. Nothing moves in the world.")
        orient.clicked.connect(self._orient)
        zero = QtWidgets.QPushButton("Zero End Orients")
        zero.setToolTip("Zero the joint orient of every end joint in or below the selection.")
        zero.clicked.connect(self._zero_end)
        buttons.addWidget(orient)
        buttons.addWidget(zero)
        layout.addLayout(buttons)
        return box

    def _mirror_box(self):
        box = QtWidgets.QGroupBox("Mirror Across X")
        layout = QtWidgets.QHBoxLayout(box)
        self.behavior = QtWidgets.QRadioButton("Behavior")
        self.behavior.setToolTip("The copies rotate the opposite way, as for arms and legs.")
        orientation = QtWidgets.QRadioButton("Orientation")
        orientation.setToolTip("The copies keep the source joints' world orientation.")
        on = bool(settings.get(SETTINGS_KEY, "behavior", 1))
        self.behavior.setChecked(on)
        orientation.setChecked(not on)
        self.behavior.toggled.connect(lambda state: settings.set(SETTINGS_KEY, "behavior", bool(state)))
        mirror = QtWidgets.QPushButton("Mirror")
        mirror.setToolTip(
            "Mirror the selected joints and the joints below them, naming the copies after the other side "
            "(L_ / R_, _l / _r, left / right, ...)."
        )
        mirror.clicked.connect(self._mirror)
        layout.addWidget(self.behavior)
        layout.addWidget(orientation)
        layout.addStretch()
        layout.addWidget(mirror)
        return box

    def _insert_box(self):
        box = QtWidgets.QGroupBox("Insert Joints")
        layout = QtWidgets.QHBoxLayout(box)
        self.count = QtWidgets.QSpinBox()
        self.count.setRange(1, 100)
        self.count.setValue(int(settings.get(SETTINGS_KEY, "count", 1)))
        self.count.valueChanged.connect(lambda value: settings.set(SETTINGS_KEY, "count", int(value)))
        insert = QtWidgets.QPushButton("Insert")
        insert.setToolTip("Insert this many evenly spaced joints between each selected joint and its child joint.")
        insert.clicked.connect(self._insert)
        layout.addWidget(QtWidgets.QLabel("Count"))
        layout.addWidget(self.count)
        layout.addStretch()
        layout.addWidget(insert)
        return box

    def _display_box(self):
        box = QtWidgets.QGroupBox("Display")
        grid = QtWidgets.QGridLayout(box)
        self.hierarchy = self._check("Hierarchy", "hierarchy", False, "Also change everything below the selection.")
        axes = QtWidgets.QPushButton("Toggle Local Axes")
        axes.setToolTip("Show the selected nodes' local axes, or hide them if they're all shown.")
        axes.clicked.connect(self._toggle_axes)
        self.radius = QtWidgets.QDoubleSpinBox()
        self.radius.setRange(0.01, 1000)
        self.radius.setSingleStep(0.1)
        self.radius.setValue(float(settings.get(SETTINGS_KEY, "radius", 1.0)))
        self.radius.valueChanged.connect(lambda value: settings.set(SETTINGS_KEY, "radius", float(value)))
        radius = QtWidgets.QPushButton("Set Radius")
        radius.setToolTip("Set the selected joints' radius.")
        radius.clicked.connect(self._set_radius)
        grid.addWidget(self.hierarchy, 0, 0)
        grid.addWidget(axes, 0, 1, 1, 2)
        grid.addWidget(QtWidgets.QLabel("Radius"), 1, 0)
        grid.addWidget(self.radius, 1, 1)
        grid.addWidget(radius, 1, 2)
        return box

    # -- actions ---------------------------------------------------------------

    def _run(self, func, *args, node_type="joint", **kwargs):
        """``func(selection, *args, **kwargs)``, or ``None`` after a warning
        if nothing fitting is selected or ``func`` refuses."""
        nodes = selected(node_type)
        if not nodes:
            _warn(f"Nothing selected. Select the {'joints' if node_type == 'joint' else 'joints or nodes'} first.")
            return None
        try:
            return func(nodes, *args, **kwargs)
        except ValueError as e:
            _warn(str(e))
            return None

    def _orient(self):
        done = self._run(
            logic.orient,
            aim=self.aim.currentData(),
            up=self.up.currentData(),
            world_up=self.world_up.currentData(),
            children=self.children_check.isChecked(),
            zero_end=self.zero_end.isChecked(),
        )
        if done is not None:
            self.status.setText(f"Oriented {_plural(len(done))}.")

    def _zero_end(self):
        done = self._run(logic.zero_end_orients)
        if done is not None:
            self.status.setText(f"Zeroed {_plural(len(done), 'end joint')}.")

    def _mirror(self):
        done = self._run(logic.mirror, behavior=self.behavior.isChecked())
        if done is not None:
            self.status.setText(f"Mirrored {_plural(len(done), 'chain')}.")
            cmds.select(done)

    def _insert(self):
        done = self._run(logic.insert_below, self.count.value())
        if done is not None:
            self.status.setText(f"Inserted {_plural(len(done))}.")
            cmds.select(done)

    def _toggle_axes(self):
        shown = self._run(logic.toggle_local_axis, node_type="transform", hierarchy=self.hierarchy.isChecked())
        if shown is not None:
            self.status.setText("Local axes shown." if shown else "Local axes hidden.")

    def _set_radius(self):
        done = self._run(logic.set_radius, self.radius.value(), hierarchy=self.hierarchy.isChecked())
        if done is not None:
            self.status.setText(f"Set the radius of {_plural(len(done))}.")
