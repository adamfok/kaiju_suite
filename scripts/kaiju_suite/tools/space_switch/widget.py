from maya import cmds
from PySide6 import QtWidgets

from kaiju_suite.core import settings
from kaiju_suite.core.selection import selected
from kaiju_suite.tools.space_switch import logic
from kaiju_suite.ui.base_window import ToolWindow

TOOL = "space_switch"


def _warn(message):
    cmds.warning(f"Kaiju Space Switch Tool: {message}")


class SpaceSwitchWindow(ToolWindow):
    TITLE = "Kaiju Space Switch Tool"

    def build_ui(self):
        note = QtWidgets.QLabel(
            "Select controls with a space attribute (built by the Space Switch rig module), "
            "click Load Selected, pick a space and Switch. The controls stay where they are."
        )
        note.setWordWrap(True)

        load = QtWidgets.QPushButton("Load Selected")
        load.setToolTip("List the spaces the selected controls share.")
        load.clicked.connect(self._load)

        self.spaces = QtWidgets.QListWidget()
        self.spaces.setToolTip("Double-click a space to switch to it.")
        self.spaces.itemDoubleClicked.connect(lambda _item: self._switch())

        self.key = QtWidgets.QCheckBox("Key both frames")
        self.key.setToolTip("Key the frame before (old space) and this frame (new space), so the switch is animated.")
        self.key.setChecked(bool(settings.get(TOOL, "key", False)))
        self.key.toggled.connect(lambda on: settings.set(TOOL, "key", bool(on)))

        switch = QtWidgets.QPushButton("Switch")
        switch.setToolTip("Switch the selected controls to the picked space without moving them.")
        switch.clicked.connect(self._switch)

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)

        for widget in (note, load, self.spaces, self.key, switch, self.status):
            self.layout.addWidget(widget)

    def _controls(self):
        controls = logic.space_controls(selected())
        if not controls:
            _warn("No control with a space attribute is selected.")
        return controls

    def _load(self):
        self.spaces.clear()
        controls = self._controls()
        if not controls:
            self.status.setText("")
            return
        labels = logic.common_spaces(controls)
        if not labels:
            _warn("The selected controls share no space.")
        self.spaces.addItems(labels)
        current = logic.current_space(controls[0])
        if current in labels:
            self.spaces.setCurrentRow(labels.index(current))
        self.status.setText(f"{len(controls)} control{'s' if len(controls) != 1 else ''}; first is in {current}.")

    def _switch(self):
        item = self.spaces.currentItem()
        if item is None:
            _warn("Pick a space first (Load Selected lists them).")
            return
        controls = self._controls()
        if not controls:
            return
        result = logic.switch(controls, item.text(), key=self.key.isChecked())
        count = len(result.changed)
        self.status.setText(f"Switched {count} control{'s' if count != 1 else ''} to {item.text()}.")
        if result.skipped:
            _warn(f"No {item.text()} space, skipped: {', '.join(cmds.ls(result.skipped))}")
