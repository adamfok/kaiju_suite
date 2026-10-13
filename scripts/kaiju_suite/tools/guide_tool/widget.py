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
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.layout.addWidget(self.status)
        self.layout.addStretch()

    # -- layout ----------------------------------------------------------------

    def _buttons(self, *buttons):
        """A row of ``(label, tooltip, slot)`` buttons side by side."""
        row = QtWidgets.QHBoxLayout()
        for label, tip, slot in buttons:
            button = QtWidgets.QPushButton(label)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            row.addWidget(button)
        return row

    def _combo(self, name, default, tip):
        combo = QtWidgets.QComboBox()
        combo.setToolTip(tip)
        for label, value in _SIGNED:
            combo.addItem(label, value)
        combo.setCurrentIndex(max(combo.findData(settings.get(SETTINGS_KEY, name, default)), 0))
        combo.currentIndexChanged.connect(lambda *_: settings.set(SETTINGS_KEY, name, combo.currentData()))
        combo.currentIndexChanged.connect(self._preview_axes)
        return combo

    def _create_box(self):
        box = QtWidgets.QGroupBox("Guides")
        grid = QtWidgets.QGridLayout(box)
        self.name = QtWidgets.QLineEdit(settings.get(SETTINGS_KEY, "name", "chain"))
        self.name.setToolTip("The chain's name: guides are <name>_start_guide..., joints <name>_01_jnt...")
        self.name.textChanged.connect(lambda text: settings.set(SETTINGS_KEY, "name", text))
        self.count = QtWidgets.QSpinBox()
        self.count.setRange(0, 100)
        self.count.setValue(int(settings.get(SETTINGS_KEY, "count", 1)))
        self.count.setToolTip("How many guides go between the start and end guides.")
        self.count.valueChanged.connect(lambda value: settings.set(SETTINGS_KEY, "count", int(value)))
        grid.addWidget(QtWidgets.QLabel("Name"), 0, 0)
        grid.addWidget(self.name, 0, 1)
        grid.addWidget(QtWidgets.QLabel("Middle guides"), 1, 0)
        grid.addWidget(self.count, 1, 1)
        buttons = self._buttons(
            (
                "Build Guides",
                "Make guides named after Name, with a joint chain that follows them live: start, middle and end "
                "guides along X, and a yellow up guide to the side. Guides can only be moved. If guides with this "
                "name exist, their start, end and up guides stay and the middle guides are reset to this number. "
                "With a joint selected that follows no guides (e.g. after Delete Guides), build guides on its "
                "chain instead, and the same joints follow them again.",
                self._build,
            ),
            (
                "Delete Guides",
                "Delete the selected chain's guides (or the only guides in the scene). Their joints stay where "
                "they are, cut loose, with plain translate and joint orient values.",
                self._delete,
            ),
        )
        grid.addLayout(buttons, 2, 0, 1, 2)
        return box

    def _build_box(self):
        box = QtWidgets.QGroupBox("Joints")
        layout = QtWidgets.QVBoxLayout(box)
        self.aim = self._combo("aim", "x", "The axis that points at the next joint.")
        self.up = self._combo("up", "y", "The axis that points towards the up guide's side, in the chain's plane.")
        axes = QtWidgets.QGridLayout()
        for column, (label, combo) in enumerate((("Aim", self.aim), ("Up", self.up))):
            axes.addWidget(QtWidgets.QLabel(label), 0, column)
            axes.addWidget(combo, 1, column)
        layout.addLayout(axes)
        layout.addLayout(
            self._buttons(
                (
                    "Hide Joints",
                    "Hide the selected chain's joints, to see the preview; click again to show them. "
                    "Only the joints are hidden, not what's parented under them.",
                    self._toggle_joints,
                ),
            )
        )
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

    def _build(self):
        name = self.name.text().strip()
        axes = {"aim": self.aim.currentData(), "up": self.up.currentData()}
        joint = logic.free_joint(selected())
        if joint is not None:
            group = self._run(logic.guides_from_joints, joint, name=name, **axes)
            if group is not None:
                self.status.setText(f"Built guides from the joints of {cmds.ls(group)[0]}; they follow them again.")
            return
        group = self._run(logic.build_guides, name, self.count.value(), **axes)
        if group is not None:
            cmds.select(logic.guides(group)["chain"][1:-1] or logic.guides(group)["chain"])
            self.status.setText(f"Built guides for {name} with {self.count.value()} middle guides. Move them around.")

    def _preview_axes(self, *_):
        """Turn the selected chain to the chosen axes. Quiet when no guides
        are selected, or while the two combos share an axis."""
        if not hasattr(self, "up"):
            return  # still building the window
        try:
            logic.set_axes(logic.find_group(selected()), aim=self.aim.currentData(), up=self.up.currentData())
        except ValueError:
            return
        self.status.setText("Joints turned to the new axes.")

    def _toggle_joints(self):
        group = self._group()
        if group is None:
            return
        shown = self._run(logic.toggle_joints, group)
        if shown is not None:
            self.status.setText("Joints shown." if shown else "Joints hidden. Click Hide Joints again to show them.")

    def _delete(self):
        group = self._group()
        if group is None:
            return
        joints = self._run(logic.delete_guides, group)
        if joints is not None:
            if joints:
                cmds.select(joints[0])
            self.status.setText(f"Deleted the guides; {len(joints)} joints extracted.")
