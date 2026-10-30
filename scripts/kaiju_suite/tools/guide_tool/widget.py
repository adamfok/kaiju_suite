from maya import cmds
from PySide6 import QtCore, QtWidgets

from kaiju_suite.core import settings
from kaiju_suite.core.selection import selected
from kaiju_suite.core.undo import undoable
from kaiju_suite.tools.guide_tool import logic, templates
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
        # Two tabs: Chain (one chain at a time) and Templates (a whole body).
        chain_page = QtWidgets.QWidget()
        chain = QtWidgets.QVBoxLayout(chain_page)
        # The Chain tab's four rows: preset; name, middle guides and end joint; axes and mirror;
        # Build and Delete.
        self._filling = False  # True while a preset fills the fields
        self.name = QtWidgets.QLineEdit(settings.get(SETTINGS_KEY, "name", "chain"))
        self.name.setToolTip("The chain's name: guides are <name>_start_guide..., joints <name>_01_jnt...")
        self.name.textChanged.connect(lambda text: settings.set(SETTINGS_KEY, "name", text))
        self.count = QtWidgets.QSpinBox()
        self.count.setRange(0, 100)
        self.count.setValue(int(settings.get(SETTINGS_KEY, "count", 1)))
        self.count.setToolTip("How many guides go between the start and end guides.")
        self.count.valueChanged.connect(lambda value: settings.set(SETTINGS_KEY, "count", int(value)))
        self.end_joint = QtWidgets.QCheckBox("End")
        self.end_joint.setChecked(bool(int(settings.get(SETTINGS_KEY, "end_joint", 1))))
        self.end_joint.setToolTip(
            "Build a joint on the end guide too, named <name>_<N>_jnt_end.\n"
            "Off: no joint there; the end guide still aims the last joint."
        )
        self.end_joint.toggled.connect(lambda on: settings.set(SETTINGS_KEY, "end_joint", int(on)))
        self.aim = self._combo("aim", "x", "The axis that points at the next joint.")
        self.up = self._combo("up", "y", "The axis that points towards the up guide's side, in the chain's plane.")
        self.mirror = QtWidgets.QCheckBox("Mirror")
        self.mirror.setChecked(bool(int(settings.get(SETTINGS_KEY, "mirror", 0))))
        self.mirror.setToolTip(
            "Build also makes a joint chain mirrored across X with behavior, following the guided\n"
            "joints live (no guides of its own). Its names swap the side (l/r, L/R, left/right...),\n"
            "or get _mirrored with no side. Building again with Mirror off removes it."
        )
        self.mirror.toggled.connect(lambda on: settings.set(SETTINGS_KEY, "mirror", int(on)))

        self.preset = QtWidgets.QComboBox()
        self.preset.setToolTip(
            "Custom: build from 0 to 10 along X.\n"
            "A preset fills the fields below, and Build places its guides from the origin, going\n"
            "the way that chain goes on a ~180 cm body (Y up, facing +Z, left at +X)."
        )
        self.preset.addItem("Custom", "")
        for preset in logic.PRESETS:
            self.preset.addItem(preset, preset)
        self.preset.setCurrentIndex(max(self.preset.findData(settings.get(SETTINGS_KEY, "preset", "")), 0))
        self.preset.currentIndexChanged.connect(self._fill_preset)

        preset_row = QtWidgets.QHBoxLayout()
        preset_row.addWidget(QtWidgets.QLabel("Preset"))
        preset_row.addWidget(self.preset, 1)
        chain.addLayout(preset_row)

        name_row = QtWidgets.QHBoxLayout()
        name_row.addWidget(QtWidgets.QLabel("Name"))
        name_row.addWidget(self.name, 1)
        name_row.addWidget(QtWidgets.QLabel("# Mid"))
        name_row.addWidget(self.count)
        name_row.addWidget(self.end_joint)
        chain.addLayout(name_row)

        settings_row = QtWidgets.QHBoxLayout()
        for label, field in (("Aim", self.aim), ("Up", self.up)):
            settings_row.addWidget(QtWidgets.QLabel(label))
            settings_row.addWidget(field, 1)
        settings_row.addWidget(self.mirror)
        chain.addLayout(settings_row)

        buttons = QtWidgets.QHBoxLayout()
        for name, tip, action in (
            (
                "Build",
                "Build Guides: guides named after Name, with a joint chain that follows them live.\n"
                "If guides with this name exist, their start, end and up guides stay and the middle\n"
                "guides are reset to # Mid. With a joint selected that follows no guides (e.g. after\n"
                "Delete Guides), build guides on its chain, and the same joints follow them again.",
                self._build,
            ),
            (
                "Delete",
                "Delete Guides: delete the selected chain's guides (or the only guides in the scene).\n"
                "Their joints (and mirrored joints) stay where they are, cut loose, with plain translate\n"
                "and joint orient values.",
                self._delete,
            ),
        ):
            # A push button keeps its icon and label centered as it stretches.
            button = QtWidgets.QPushButton(icons.icon(f"guide_tool_{name.lower()}.svg"), name)
            button.setIconSize(QtCore.QSize(20, 20))
            button.setToolTip(tip)
            button.clicked.connect(action)
            buttons.addWidget(button)
        chain.addLayout(buttons)
        chain.addStretch()

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(chain_page, "Chain")
        tabs.addTab(self._templates_page(), "Templates")
        tabs.setCurrentIndex(int(settings.get(SETTINGS_KEY, "tab", 0)))
        tabs.currentChanged.connect(lambda index: settings.set(SETTINGS_KEY, "tab", index))
        self.layout.addWidget(tabs)

    def _templates_page(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        self.template = QtWidgets.QComboBox()
        self.template.setToolTip("The body to build: every chain at once, the left ones mirrored.")
        for name in templates.TEMPLATES:
            self.template.addItem(name.capitalize(), name)
        self.template.setCurrentIndex(max(self.template.findData(settings.get(SETTINGS_KEY, "template", "")), 0))
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Template"))
        row.addWidget(self.template, 1)
        layout.addLayout(row)

        self.skeleton = QtWidgets.QComboBox()
        self.skeleton.setToolTip("The skeleton to align to; Auto picks the one the selected hierarchy matches best.")
        self._fill_skeletons()
        self.skeleton.currentIndexChanged.connect(
            lambda *_: settings.set(SETTINGS_KEY, "skeleton", self.skeleton.currentData())
        )
        self.template.currentIndexChanged.connect(self._template_changed)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Align to"))
        row.addWidget(self.skeleton, 1)
        layout.addLayout(row)

        # The buttons in the order they're used: build, align, delete.
        buttons = QtWidgets.QHBoxLayout()
        for icon, label, tip, action in (
            (
                "build",
                "Build Template",
                "Build every chain of the template on a body (Y up, facing +Z, left at +X), each one\n"
                "starting where the one it hangs off ends. Chains already built are built again in place.\n"
                "Use the Chain tab's Build and Delete on any one of them.",
                self._build_template,
            ),
            (
                None,
                "Align",
                "Select a joint of the skeleton to align to, then Align: each built chain's start and end\n"
                "guides go on two of its joints (not joint for joint), middle guides on its elbow, knee,\n"
                "ball and knuckles when the counts match (else evenly), and arm, leg and finger up guides\n"
                "where they bend. Your joints follow, keeping their own count. Chains it can't place are\n"
                "skipped and listed.",
                self._align,
            ),
            (
                "delete",
                "Delete Template",
                "Delete the guides of every chain of the template that's built. Their joints (and\n"
                "mirrored joints) stay where they are, cut loose, as the Chain tab's Delete leaves them.",
                self._delete_template,
            ),
        ):
            button = QtWidgets.QPushButton(label)
            if icon:
                button.setIcon(icons.icon(f"guide_tool_{icon}.svg"))
                button.setIconSize(QtCore.QSize(20, 20))
            button.setToolTip(tip)
            button.clicked.connect(action)
            buttons.addWidget(button, 1)
        layout.addLayout(buttons)
        layout.addStretch()
        return page

    def _fill_skeletons(self):
        """List Auto and the skeletons that fit the current template, keeping
        the saved one if it fits."""
        self.skeleton.blockSignals(True)
        self.skeleton.clear()
        self.skeleton.addItem("Auto", "")
        for key, skeleton in templates.SKELETONS.items():
            if skeleton["template"] == self.template.currentData():
                self.skeleton.addItem(skeleton["label"], key)
        self.skeleton.setCurrentIndex(max(self.skeleton.findData(settings.get(SETTINGS_KEY, "skeleton", "")), 0))
        self.skeleton.blockSignals(False)

    def _template_changed(self, *_):
        settings.set(SETTINGS_KEY, "template", self.template.currentData())
        self._fill_skeletons()

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

    def _fill_preset(self, *_):
        """Fill the fields from the chosen preset (Custom leaves them)."""
        key = self.preset.currentData()
        settings.set(SETTINGS_KEY, "preset", key)
        preset = logic.PRESETS.get(key)
        if preset is None:
            return
        self._filling = True
        try:
            self.name.setText(preset["name"])
            self.count.setValue(preset["count"])
            self.end_joint.setChecked(preset["end_joint"])
            self.mirror.setChecked(preset["mirror"])
            self.aim.setCurrentIndex(self.aim.findData(preset["aim"]))
            self.up.setCurrentIndex(self.up.findData(preset["up"]))
        finally:
            self._filling = False

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

    # Build and Delete also select what they made: one undo step with it.
    @undoable
    def _build(self, *_):
        name = self.name.text().strip()
        axes = {"aim": self.aim.currentData(), "up": self.up.currentData(), "mirror": self.mirror.isChecked()}
        joint = logic.free_joint(selected())
        if joint is not None:
            group = self._run(logic.guides_from_joints, joint, name=name, **axes)
            if group is not None:
                _say(f"Guides built on the joints of {cmds.ls(group)[0]}.")
            return
        preset = logic.PRESETS.get(self.preset.currentData())
        place = {k: preset[k] for k in ("start", "end", "up_side")} if preset else {}
        group = self._run(
            logic.build_guides, name, self.count.value(), end_joint=self.end_joint.isChecked(), **axes, **place
        )
        if group is not None:
            cmds.select(logic.guides(group)["chain"][1:-1] or logic.guides(group)["chain"])
            _say(f"Guides built for {name}.")

    def _preview_axes(self, *_):
        """Turn the selected chain to the chosen axes. Quiet when no guides
        are selected, or while the two combos share an axis."""
        if not hasattr(self, "up") or self._filling:
            return  # still building the window, or a preset is filling the fields
        try:
            logic.set_axes(logic.find_group(selected()), aim=self.aim.currentData(), up=self.up.currentData())
        except ValueError:
            return

    @undoable
    def _build_template(self, *_):
        groups = self._run(templates.build_template, self.template.currentData())
        if groups is not None:
            cmds.select(clear=True)
            _say(f"{self.template.currentText()} template built: {len(groups)} chains.")

    @undoable
    def _delete_template(self, *_):
        joints = self._run(templates.delete_template, self.template.currentData())
        if joints is not None:
            cmds.select(clear=True)
            _say(f"{self.template.currentText()} template guides deleted; {len(joints)} joints extracted.")

    def _align(self, *_):
        report = self._run(
            templates.align, self.template.currentData(), selected(), self.skeleton.currentData() or None
        )
        if report is None:
            return
        label = templates.SKELETONS[report["skeleton"]]["label"]
        _say(f"{len(report['aligned'])} chains aligned to {label}.")
        if report["skipped"]:
            _warn("Not aligned: " + "; ".join(f"{name} ({why})" for name, why in report["skipped"]))

    @undoable
    def _delete(self, *_):
        group = self._group()
        if group is None:
            return
        joints = self._run(logic.delete_guides, group)
        if joints is not None:
            if joints:
                cmds.select(joints[0])
            _say(f"Guides deleted; {len(joints)} joints extracted.")
