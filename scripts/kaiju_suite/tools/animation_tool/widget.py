from maya import cmds
from PySide6 import QtWidgets

from kaiju_suite.core import settings
from kaiju_suite.core.selection import selected
from kaiju_suite.tools.animation_tool import logic
from kaiju_suite.ui.base_window import ToolWindow

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

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)

        self.layout.addWidget(mirror_box)
        self.layout.addWidget(self.status)
        self.layout.addStretch()

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
