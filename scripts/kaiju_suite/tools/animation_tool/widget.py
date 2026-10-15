from maya import cmds
from PySide6 import QtWidgets

from kaiju_suite.core import settings
from kaiju_suite.core.selection import selected
from kaiju_suite.tools.animation_tool import logic
from kaiju_suite.ui.base_window import ToolWindow
from kaiju_suite.ui.qc_tab import QCTab

SETTINGS_KEY = "animation_tool"


def _warn(message):
    cmds.warning(f"Kaiju Animation Tool: {message}")


class AnimationToolWindow(ToolWindow):
    TITLE = "Kaiju Animation Tool"

    def build_ui(self):
        mirror_box = QtWidgets.QGroupBox("Mirror Animation")
        mirror = QtWidgets.QVBoxLayout(mirror_box)
        note = QtWidgets.QLabel(
            "Sides are found by name (L_/R_, _l/_r, left/right). "
            "Controls with no side mirror onto themselves. Mirrors across X; "
            "keys, tangents and timing are kept."
        )
        note.setWordWrap(True)
        mirror.addWidget(note)

        offset_row = QtWidgets.QHBoxLayout()
        offset_row.addWidget(QtWidgets.QLabel("Frame offset:"))
        self.offset = QtWidgets.QDoubleSpinBox()
        self.offset.setRange(-100000, 100000)
        self.offset.setDecimals(2)
        self.offset.setToolTip("Move the mirrored keys by this many frames, e.g. half a cycle for a walk.")
        self.offset.setValue(float(settings.get(SETTINGS_KEY, "offset", 0.0) or 0.0))
        self.offset.valueChanged.connect(lambda value: settings.set(SETTINGS_KEY, "offset", float(value)))
        offset_row.addWidget(self.offset)
        offset_row.addStretch()
        mirror.addLayout(offset_row)

        row = QtWidgets.QHBoxLayout()
        for label, tip, slot in (
            ("Mirror", "Replace each selected control's opposite's keys with its keys, mirrored.", self._mirror),
            ("Flip", "Swap the keys of the selected controls and their opposites, mirrored.", self._flip),
        ):
            button = QtWidgets.QPushButton(label)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            row.addWidget(button)
        mirror.addLayout(row)

        switch_box = QtWidgets.QGroupBox("IK/FK Switch")
        switch = QtWidgets.QVBoxLayout(switch_box)
        note = QtWidgets.QLabel(
            "Select an IK/FK limb's switch control, or any of its controls. "
            "Switches to the other side, matched to the current pose, so the limb doesn't pop."
        )
        note.setWordWrap(True)
        switch.addWidget(note)
        switch_row = QtWidgets.QHBoxLayout()
        self.key_switch = QtWidgets.QCheckBox("Key")
        self.key_switch.setToolTip(
            "Key the switch and the matched controls on the frame before (as they were) and on this frame."
        )
        self.key_switch.setChecked(bool(settings.get(SETTINGS_KEY, "key_switch", False)))
        self.key_switch.toggled.connect(lambda on: settings.set(SETTINGS_KEY, "key_switch", bool(on)))
        switch_row.addWidget(self.key_switch)
        button = QtWidgets.QPushButton("Switch IK/FK")
        button.setToolTip("From IK to FK, or from FK to IK, matching the other side first.")
        button.clicked.connect(self._switch_ik_fk)
        switch_row.addWidget(button, 1)
        switch.addLayout(switch_row)

        reset_box = QtWidgets.QGroupBox("Reset Controls")
        reset = QtWidgets.QVBoxLayout(reset_box)
        note = QtWidgets.QLabel(
            "Puts the selected rig controls, or every one if nothing is selected, "
            "back to the values they were built with."
        )
        note.setWordWrap(True)
        reset.addWidget(note)
        button = QtWidgets.QPushButton("Reset Controls")
        button.setToolTip("Attributes locked or connected since the build are left alone.")
        button.clicked.connect(self._reset_controls)
        reset.addWidget(button)

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)

        tabs = QtWidgets.QTabWidget()
        qc = QCTab(logic.QC_CHECKS, logic.qc_settings(), logic.save_qc_setting, self._run_qc, logic.select_problem)
        tabs.addTab(qc, "QC")
        utilities = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(utilities)
        layout.addWidget(mirror_box)
        layout.addWidget(switch_box)
        layout.addWidget(reset_box)
        layout.addWidget(self.status)
        layout.addStretch()
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setWidget(utilities)
        tabs.addTab(scroll, "Utilities")
        tabs.setCurrentIndex(settings.get(SETTINGS_KEY, "tab", 0))
        tabs.currentChanged.connect(lambda index: settings.set(SETTINGS_KEY, "tab", index))
        self.layout.addWidget(tabs)

    def _run_qc(self):
        """The QC results for the selection, or ``None`` after warning why not."""
        try:
            return logic.run_qc(selected())
        except ValueError as e:
            _warn(str(e))
            return None

    def _nodes(self):
        nodes = selected()
        if not nodes:
            _warn("Nothing selected. Select the controls first.")
        return nodes

    def _report(self, verb, result):
        count = len(result.changed)
        self.status.setText(f"{verb} {count} control{'s' if count != 1 else ''}.")
        if result.skipped:
            _warn(f"Skipped: {', '.join(result.skipped)}")

    def _mirror(self):
        nodes = self._nodes()
        if not nodes:
            return
        try:
            self._report("Mirrored animation onto", logic.mirror(nodes, offset=self.offset.value()))
        except ValueError as e:
            _warn(str(e))

    def _flip(self):
        nodes = self._nodes()
        if nodes:
            self._report("Flipped animation of", logic.flip(nodes, offset=self.offset.value()))

    def _switch_ik_fk(self):
        nodes = self._nodes()
        if not nodes:
            return
        try:
            result = logic.switch_ik_fk(nodes, key=self.key_switch.isChecked())
        except ValueError as e:
            _warn(str(e))
            return
        if not result.changed:
            _warn("Nothing selected is part of an IK/FK limb. Select its switch control.")
            return
        self._report("Switched IK/FK on", result)

    def _reset_controls(self):
        done, message = logic.reset_controls()
        self.status.setText(message)
        if not done:
            _warn(message)
