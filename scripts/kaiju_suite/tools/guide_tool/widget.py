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
        # Two rows: create guides, then build joints. Fields name themselves
        # (placeholder, prefix, "Aim +X"), so there are no labels or boxes.
        self.name = QtWidgets.QLineEdit(settings.get(SETTINGS_KEY, "name", "chain"))
        self.name.setPlaceholderText("Chain name")
        self.name.setToolTip("The chain's name: guides are <name>_start_guide..., joints <name>_01_jnt...")
        self.name.textChanged.connect(lambda text: settings.set(SETTINGS_KEY, "name", text))
        self.count = QtWidgets.QSpinBox()
        self.count.setRange(0, 100)
        self.count.setPrefix("Mid: ")
        self.count.setValue(int(settings.get(SETTINGS_KEY, "count", 1)))
        self.count.setToolTip("How many guides go between the start and end guides.")
        self.count.valueChanged.connect(lambda value: settings.set(SETTINGS_KEY, "count", int(value)))
        self.aim = self._combo("aim", "Aim", "x", "The axis that points at the next joint.")
        self.up = self._combo(
            "up", "Up", "y", "The axis that points towards the up guide's side, in the chain's plane."
        )

        grid = QtWidgets.QGridLayout()
        rows = (
            (
                self.name,
                self.count,
                (
                    "Create Guides",
                    "Make start, middle and end guides along X, and a yellow up guide to the side. "
                    "Guides can only be moved. A disc and local axis show where each joint will land, "
                    "and a see-through surface shows the chain's plane.",
                    self._create,
                ),
                (
                    "Delete Guides",
                    "Delete the selected chain's guides (or the only guides in the scene). "
                    "Joints built from them stay.",
                    self._delete,
                ),
            ),
            (
                self.aim,
                self.up,
                (
                    "Build Joints",
                    "Build a joint chain on the plane through the start, end and up guides of the selected guides "
                    "(or the only guides in the scene). If it was built already, move and re-orient those joints.",
                    self._build,
                ),
                (
                    "Hide Joints",
                    "Hide the joints built from the selected guides, to see the preview; click again to show them. "
                    "Only the joints are hidden, not what's parented under them.",
                    self._toggle_joints,
                ),
            ),
        )
        for row, items in enumerate(rows):
            for column, item in enumerate(items):
                grid.addWidget(item if isinstance(item, QtWidgets.QWidget) else self._button(*item), row, column)
        self.layout.addLayout(grid)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        self.layout.addWidget(self.status)
        self.layout.addStretch()

    # -- layout ----------------------------------------------------------------

    def _button(self, label, tip, slot):
        button = QtWidgets.QPushButton(label)
        button.setToolTip(tip)
        button.clicked.connect(slot)
        return button

    def _combo(self, name, prefix, default, tip):
        combo = QtWidgets.QComboBox()
        combo.setToolTip(tip)
        for label, value in _SIGNED:
            combo.addItem(f"{prefix} {label}", value)
        combo.setCurrentIndex(max(combo.findData(settings.get(SETTINGS_KEY, name, default)), 0))
        combo.currentIndexChanged.connect(lambda *_: settings.set(SETTINGS_KEY, name, combo.currentData()))
        combo.currentIndexChanged.connect(self._preview_axes)
        return combo

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
        group = self._run(
            logic.create_guides,
            self.name.text().strip(),
            self.count.value(),
            aim=self.aim.currentData(),
            up=self.up.currentData(),
        )
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

    def _preview_axes(self, *_):
        """Turn the selected guides' preview to the chosen axes. Quiet when
        no guides are selected, or while the two combos share an axis."""
        if not hasattr(self, "up"):
            return  # still building the window
        try:
            logic.set_axes(logic.find_group(selected()), aim=self.aim.currentData(), up=self.up.currentData())
        except ValueError:
            return
        self.status.setText("Preview turned to the new axes.")

    def _toggle_joints(self):
        group = self._group()
        if group is None:
            return
        shown = self._run(logic.toggle_joints, group)
        if shown is not None:
            self.status.setText("Joints shown." if shown else "Joints hidden. Click Hide Joints again to show them.")

    def _delete(self):
        group = self._group()
        if group is not None:
            logic.delete_guides(group)
            self.status.setText("Deleted the guides.")
