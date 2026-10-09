from maya import cmds
from PySide6 import QtWidgets

from kaiju_suite.core.selection import selected
from kaiju_suite.tools.pose_tool import logic
from kaiju_suite.ui.base_window import ToolWindow


def _warn(message):
    cmds.warning(f"Kaiju Pose Tool: {message}")


class PoseToolWindow(ToolWindow):
    TITLE = "Kaiju Pose Tool"

    def build_ui(self):
        mirror_box = QtWidgets.QGroupBox("Mirror")
        mirror = QtWidgets.QVBoxLayout(mirror_box)
        note = QtWidgets.QLabel(
            "Sides are found by name (L_/R_, _l/_r, left/right). "
            "Controls with no side mirror onto themselves. Mirrors across X."
        )
        note.setWordWrap(True)
        mirror.addWidget(note)
        row = QtWidgets.QHBoxLayout()
        for label, tip, slot in (
            ("Mirror", "Pose each selected control's opposite as its mirror image.", self._mirror),
            ("Flip", "Swap the poses of the selected controls and their opposites, mirrored.", self._flip),
        ):
            button = QtWidgets.QPushButton(label)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            row.addWidget(button)
        mirror.addLayout(row)

        select_box = QtWidgets.QGroupBox("Select")
        select = QtWidgets.QHBoxLayout(select_box)
        opposite = QtWidgets.QPushButton("Opposite")
        opposite.setToolTip("Select the opposites of the selected controls.")
        opposite.clicked.connect(lambda: self._select_opposite(add=False))
        both = QtWidgets.QPushButton("Add Opposite")
        both.setToolTip("Add the opposites of the selected controls to the selection.")
        both.clicked.connect(lambda: self._select_opposite(add=True))
        select.addWidget(opposite)
        select.addWidget(both)

        reset_box = QtWidgets.QGroupBox("Reset")
        reset = QtWidgets.QHBoxLayout(reset_box)
        reset_button = QtWidgets.QPushButton("Reset to Default")
        reset_button.setToolTip("Set every keyable attribute of the selected controls to its default value.")
        reset_button.clicked.connect(self._reset)
        reset.addWidget(reset_button)

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)

        for box in (mirror_box, select_box, reset_box):
            self.layout.addWidget(box)
        self.layout.addWidget(self.status)
        self.layout.addStretch()

    def _nodes(self):
        nodes = selected()
        if not nodes:
            _warn("Nothing selected. Select the controls first.")
        return nodes

    def _report(self, verb, result):
        count = len(result.changed)
        self.status.setText(f"{verb} {count} node{'s' if count != 1 else ''}.")
        if result.skipped:
            _warn(f"Skipped: {', '.join(result.skipped)}")

    def _mirror(self):
        nodes = self._nodes()
        if not nodes:
            return
        try:
            self._report("Mirrored onto", logic.mirror(nodes))
        except ValueError as e:
            _warn(str(e))

    def _flip(self):
        nodes = self._nodes()
        if nodes:
            self._report("Flipped", logic.flip(nodes))

    def _select_opposite(self, add):
        nodes = self._nodes()
        if not nodes:
            return
        found = logic.opposites(nodes)
        if not found:
            _warn("None of the selected nodes has an opposite in the scene.")
            return
        cmds.select(found, add=add)

    def _reset(self):
        nodes = self._nodes()
        if nodes:
            self._report("Reset", logic.reset(nodes))
