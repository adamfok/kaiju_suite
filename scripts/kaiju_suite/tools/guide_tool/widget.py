from maya import cmds
from PySide6 import QtCore, QtWidgets

from kaiju_suite.core import settings
from kaiju_suite.core.selection import selected
from kaiju_suite.tools.guide_tool import logic
from kaiju_suite.ui import icons
from kaiju_suite.ui.base_window import ToolWindow

SETTINGS_KEY = "guide_tool"
_SIGNED = [("+X", "x"), ("+Y", "y"), ("+Z", "z"), ("-X", "-x"), ("-Y", "-y"), ("-Z", "-z")]


def _warn(message):
    cmds.warning(f"Kaiju Guide Tool: {message}")


def _say(message):
    cmds.inViewMessage(assistMessage=message, position="topCenter", fade=True)


class GuideToolWindow(ToolWindow):
    TITLE = "Kaiju Guide Tool"

    def build_ui(self):
        # Three rows: the name; middle guides and axes; the buttons.
        self.name = QtWidgets.QLineEdit(settings.get(SETTINGS_KEY, "name", "chain"))
        self.name.setToolTip("The chain's name: guides are <name>_start_guide..., joints <name>_01_jnt...")
        self.name.textChanged.connect(lambda text: settings.set(SETTINGS_KEY, "name", text))
        self.count = QtWidgets.QSpinBox()
        self.count.setRange(0, 100)
        self.count.setValue(int(settings.get(SETTINGS_KEY, "count", 1)))
        self.count.setToolTip("How many guides go between the start and end guides.")
        self.count.valueChanged.connect(lambda value: settings.set(SETTINGS_KEY, "count", int(value)))
        self.aim = self._combo("aim", "x", "The axis that points at the next joint.")
        self.up = self._combo("up", "y", "The axis that points towards the up guide's side, in the chain's plane.")

        name_row = QtWidgets.QHBoxLayout()
        name_row.addWidget(QtWidgets.QLabel("Name"))
        name_row.addWidget(self.name, 1)
        self.layout.addLayout(name_row)

        settings_row = QtWidgets.QHBoxLayout()
        for label, field in (("Mid", self.count), ("Aim", self.aim), ("Up", self.up)):
            settings_row.addWidget(QtWidgets.QLabel(label))
            settings_row.addWidget(field, 1)
        self.layout.addLayout(settings_row)

        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(2)
        for name, tip, action in (
            (
                "build",
                "Build Guides: guides named after Name, with a joint chain that follows them live.\n"
                "If guides with this name exist, their start, end and up guides stay and the middle\n"
                "guides are reset to Mid. With a joint selected that follows no guides (e.g. after\n"
                "Delete Guides), build guides on its chain, and the same joints follow them again.",
                self._build,
            ),
            (
                "delete",
                "Delete Guides: delete the selected chain's guides (or the only guides in the scene).\n"
                "Their joints stay where they are, cut loose, with plain translate and joint orient values.",
                self._delete,
            ),
            (
                "joints",
                "Show/Hide Joints: hide the selected chain's joints, or show them again.\n"
                "Only the joints are hidden, not what's parented under them.",
                self._toggle_joints,
            ),
            (
                "displays",
                "Show/Hide Displays: hide the selected chain's discs, plane and guide lines,\n"
                "or show them again. The guides and joints stay.",
                self._toggle_displays,
            ),
        ):
            button = QtWidgets.QToolButton()
            button.setIcon(icons.icon(f"guide_tool_{name}.svg"))
            button.setIconSize(QtCore.QSize(20, 20))
            button.setToolTip(tip)
            button.clicked.connect(action)
            buttons.addWidget(button)
        buttons.addStretch()
        self.layout.addLayout(buttons)
        self.layout.addStretch()

    # -- layout ----------------------------------------------------------------

    def _combo(self, name, default, tip):
        combo = QtWidgets.QComboBox()
        combo.setToolTip(tip)
        for label, value in _SIGNED:
            combo.addItem(label, value)
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

    def _build(self):
        name = self.name.text().strip()
        axes = {"aim": self.aim.currentData(), "up": self.up.currentData()}
        joint = logic.free_joint(selected())
        if joint is not None:
            group = self._run(logic.guides_from_joints, joint, name=name, **axes)
            if group is not None:
                _say(f"Guides built on the joints of {cmds.ls(group)[0]}.")
            return
        group = self._run(logic.build_guides, name, self.count.value(), **axes)
        if group is not None:
            cmds.select(logic.guides(group)["chain"][1:-1] or logic.guides(group)["chain"])
            _say(f"Guides built for {name}.")

    def _preview_axes(self, *_):
        """Turn the selected chain to the chosen axes. Quiet when no guides
        are selected, or while the two combos share an axis."""
        if not hasattr(self, "up"):
            return  # still building the window
        try:
            logic.set_axes(logic.find_group(selected()), aim=self.aim.currentData(), up=self.up.currentData())
        except ValueError:
            return

    def _toggle_joints(self):
        group = self._group()
        if group is not None:
            self._run(logic.toggle_joints, group)

    def _toggle_displays(self):
        group = self._group()
        if group is not None:
            self._run(logic.toggle_displays, group)

    def _delete(self):
        group = self._group()
        if group is None:
            return
        joints = self._run(logic.delete_guides, group)
        if joints is not None:
            if joints:
                cmds.select(joints[0])
            _say(f"Guides deleted; {len(joints)} joints extracted.")
