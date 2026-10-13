from maya import cmds
from PySide6 import QtWidgets

from kaiju_suite.core import settings
from kaiju_suite.core.selection import selected
from kaiju_suite.tools.guide_tool import logic
from kaiju_suite.ui.base_window import ToolWindow

SETTINGS_KEY = "guide_tool"
_SIGNED = [("+X", "x"), ("+Y", "y"), ("+Z", "z"), ("-X", "-x"), ("-Y", "-y"), ("-Z", "-z")]


def _warn(message):
    cmds.warning(f"Kaiju Guide Tool: {message}")


class GuideToolWindow(ToolWindow):
    TITLE = "Kaiju Guide Tool"

    def build_ui(self):
        self.layout.addWidget(self._create_box())
        self.layout.addWidget(self._build_box())
        self.layout.addWidget(self._guides_box())
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

    def _create_box(self):
        box = QtWidgets.QGroupBox("Create Guides")
        grid = QtWidgets.QGridLayout(box)
        self.name = QtWidgets.QLineEdit(settings.get(SETTINGS_KEY, "name", "chain"))
        self.name.setToolTip("The chain's name: guides are <name>_start_guide..., joints <name>_01_jnt...")
        self.name.textChanged.connect(lambda text: settings.set(SETTINGS_KEY, "name", text))
        self.count = QtWidgets.QSpinBox()
        self.count.setRange(0, 100)
        self.count.setValue(int(settings.get(SETTINGS_KEY, "count", 1)))
        self.count.setToolTip("How many guides go between the start and end guides.")
        self.count.valueChanged.connect(lambda value: settings.set(SETTINGS_KEY, "count", int(value)))
        create = QtWidgets.QPushButton("Create Guides")
        create.setToolTip(
            "Make start, middle and end guides along X, and a yellow up guide to the side. "
            "Guides can only be moved."
        )
        create.clicked.connect(self._create)
        grid.addWidget(QtWidgets.QLabel("Name"), 0, 0)
        grid.addWidget(self.name, 0, 1, 1, 2)
        grid.addWidget(QtWidgets.QLabel("Middle guides"), 1, 0)
        grid.addWidget(self.count, 1, 1)
        grid.addWidget(create, 1, 2)
        return box

    def _build_box(self):
        box = QtWidgets.QGroupBox("Build Joints")
        layout = QtWidgets.QVBoxLayout(box)
        self.aim = self._combo("aim", "x", "The axis that points at the next joint.")
        self.up = self._combo("up", "y", "The axis that points towards the up guide's side, in the chain's plane.")
        axes = QtWidgets.QGridLayout()
        for column, (label, combo) in enumerate((("Aim", self.aim), ("Up", self.up))):
            axes.addWidget(QtWidgets.QLabel(label), 0, column)
            axes.addWidget(combo, 1, column)
        layout.addLayout(axes)
        build = QtWidgets.QPushButton("Build Joints")
        build.setToolTip(
            "Build a joint chain on the plane through the start, end and up guides of the selected guides "
            "(or the only guides in the scene). If it was built already, move and re-orient those joints."
        )
        build.clicked.connect(self._build)
        layout.addWidget(build)
        return box

    def _guides_box(self):
        box = QtWidgets.QGroupBox("Guides")
        layout = QtWidgets.QHBoxLayout(box)
        for label, tip, slot in (
            ("Select Guides", "Select the guides of the selected chain.", self._select_guides),
            ("Select Joints", "Select the joints built from the selected guides.", self._select_joints),
            ("Delete Guides", "Delete the selected chain's guides. Joints built from them stay.", self._delete),
        ):
            button = QtWidgets.QPushButton(label)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            layout.addWidget(button)
        return box

    # -- actions ---------------------------------------------------------------

    def _run(self, func, *args, **kwargs):
        """``func(*args, **kwargs)``, or ``None`` after a warning if it refuses."""
        try:
            return func(*args, **kwargs)
        except ValueError as e:
            _warn(str(e))
            return None

    def _group(self):
        return self._run(logic.find_group, selected())

    def _create(self):
        group = self._run(logic.create_guides, self.name.text().strip(), self.count.value())
        if group is not None:
            cmds.select(logic.guides(group)["chain"])
            self.status.setText(f"Created guides for {self.name.text().strip()}. Move them, then Build Joints.")

    def _build(self):
        group = self._group()
        if group is None:
            return
        done = self._run(logic.build_joints, group, aim=self.aim.currentData(), up=self.up.currentData())
        if done is not None:
            self.status.setText(f"Placed {len(done)} joints.")

    def _select_guides(self):
        group = self._group()
        if group is not None:
            found = logic.guides(group)
            cmds.select(found["chain"] + [found["up"]])

    def _select_joints(self):
        group = self._group()
        if group is None:
            return
        found = logic.joints(group)
        if not found:
            _warn("No joints built from these guides yet.")
            return
        cmds.select(found)

    def _delete(self):
        group = self._group()
        if group is not None:
            logic.delete_guides(group)
            self.status.setText("Deleted the guides.")
