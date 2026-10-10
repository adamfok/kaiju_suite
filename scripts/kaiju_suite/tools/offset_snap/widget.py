from maya import cmds
from PySide6 import QtWidgets

from kaiju_suite.core import settings
from kaiju_suite.core.selection import selected
from kaiju_suite.tools.offset_snap import logic
from kaiju_suite.ui.base_window import ToolWindow

SETTINGS_KEY = "offset_snap"
_DEFAULT_PATTERNS = "{name}_zero, {name}_offset"


def _warn(message):
    cmds.warning(f"Kaiju Offset & Snap Tool: {message}")


def _check(name, default):
    box = QtWidgets.QCheckBox(name)
    box.setChecked(bool(settings.get(SETTINGS_KEY, name.lower(), int(default))))
    return box


class OffsetSnapWindow(ToolWindow):
    TITLE = "Kaiju Offset & Snap Tool"

    def build_ui(self):
        self.layout.addWidget(self._offset_box())
        self.layout.addWidget(self._match_box())
        self.layout.addWidget(self._centroid_box())
        self.layout.addWidget(self._zero_box())
        self.layout.addStretch()

    # -- layout ----------------------------------------------------------------

    def _offset_box(self):
        box = QtWidgets.QGroupBox("Offset Groups")
        layout = QtWidgets.QVBoxLayout(box)
        row = QtWidgets.QHBoxLayout()
        self.patterns = QtWidgets.QLineEdit(settings.get(SETTINGS_KEY, "patterns", _DEFAULT_PATTERNS))
        self.patterns.setToolTip(
            "One group per pattern, outermost first, separated by commas. "
            "{name} is the node's name; ## numbers the level (01, 02, ...)."
        )
        row.addWidget(QtWidgets.QLabel("Groups"))
        row.addWidget(self.patterns)
        layout.addLayout(row)
        add = QtWidgets.QPushButton("Add Offset Groups")
        add.setToolTip("Put the groups above each selected node; the node keeps its place and its channels go to zero.")
        add.clicked.connect(self._add_groups)
        layout.addWidget(add)
        return box

    def _match_box(self):
        box = QtWidgets.QGroupBox("Match to Last Selected")
        layout = QtWidgets.QVBoxLayout(box)
        options = QtWidgets.QHBoxLayout()
        self.match_translate = _check("Position", True)
        self.match_rotate = _check("Rotation", True)
        self.match_scale = _check("Scale", False)
        self.match_pivot = _check("Pivot", False)
        self.match_pivot.setToolTip("Move the nodes' pivots onto the target's without moving the nodes.")
        for check in (self.match_translate, self.match_rotate, self.match_scale, self.match_pivot):
            options.addWidget(check)
        options.addStretch()
        layout.addLayout(options)
        match = QtWidgets.QPushButton("Match")
        match.setToolTip("Snap the selected nodes to the last selected one.")
        match.clicked.connect(self._match)
        layout.addWidget(match)
        return box

    def _centroid_box(self):
        box = QtWidgets.QGroupBox("Place at Centroid")
        box.setToolTip("At the middle of the selected vertices, edges, faces or objects.")
        layout = QtWidgets.QHBoxLayout(box)
        locator = QtWidgets.QPushButton("Locator")
        locator.clicked.connect(lambda: self._place("locator"))
        joint = QtWidgets.QPushButton("Joint")
        joint.clicked.connect(lambda: self._place("joint"))
        layout.addWidget(locator)
        layout.addWidget(joint)
        return box

    def _zero_box(self):
        box = QtWidgets.QGroupBox("Controls")
        layout = QtWidgets.QVBoxLayout(box)
        zero = QtWidgets.QPushButton("Zero Out")
        zero.setToolTip(
            "Reset the selected controls' keyable translate, rotate and scale to their defaults "
            "(locked and connected channels are skipped)."
        )
        zero.clicked.connect(self._zero)
        layout.addWidget(zero)
        return box

    # -- actions ---------------------------------------------------------------

    def _add_groups(self):
        nodes = selected(node_type="transform")
        if not nodes:
            _warn("Select the nodes to add offset groups above.")
            return
        text = self.patterns.text()
        settings.set(SETTINGS_KEY, "patterns", text)
        try:
            made = logic.add_offset_groups(nodes, text.split(","))
        except (ValueError, RuntimeError) as e:
            _warn(str(e))
            return
        cmds.select([groups[0] for groups in made])

    def _match(self):
        nodes = selected(node_type="transform")
        if len(nodes) < 2:
            _warn("Select the nodes to move, then the one to match them to.")
            return
        checks = {
            "position": self.match_translate,
            "rotation": self.match_rotate,
            "scale": self.match_scale,
            "pivot": self.match_pivot,
        }
        for name, check in checks.items():
            settings.set(SETTINGS_KEY, name, int(check.isChecked()))
        if not any(check.isChecked() for check in checks.values()):
            _warn("Turn on at least one of Position, Rotation, Scale or Pivot.")
            return
        try:
            logic.match_transforms(
                nodes[:-1],
                nodes[-1],
                translate=self.match_translate.isChecked(),
                rotate=self.match_rotate.isChecked(),
                scale=self.match_scale.isChecked(),
                pivot=self.match_pivot.isChecked(),
            )
        except RuntimeError as e:
            _warn(str(e))

    def _place(self, kind):
        items = cmds.ls(selection=True, long=True) or []
        try:
            node = logic.place_at_centroid(items, kind=kind)
        except ValueError as e:
            _warn(str(e))
            return
        cmds.select(node)

    def _zero(self):
        nodes = selected(node_type="transform")
        if not nodes:
            _warn("Select the controls to zero out.")
            return
        result = logic.zero_out(nodes)
        if result.skipped:
            _warn(f"Skipped: {', '.join(result.skipped)}")
