from maya import cmds
from PySide6 import QtWidgets

from kaiju_suite.core import settings
from kaiju_suite.core.selection import selected, short_name
from kaiju_suite.tools.blendshape_tool import logic
from kaiju_suite.ui.base_window import ToolWindow

SETTINGS_KEY = "blendshape_tool"


def _warn(message):
    cmds.warning(f"Kaiju BlendShape Tool: {message}")


class BlendShapeToolWindow(ToolWindow):
    TITLE = "Kaiju BlendShape Tool"

    def build_ui(self):
        self.mesh = None

        # Corrective
        sculpt_box = QtWidgets.QGroupBox("Corrective")
        sculpt = QtWidgets.QGridLayout(sculpt_box)
        start = QtWidgets.QPushButton("Start Sculpt")
        start.setToolTip("Pose the rig, select the skinned mesh, then click: makes a copy of the posed mesh to sculpt on.")
        start.clicked.connect(self._start_sculpt)
        self.name = QtWidgets.QLineEdit()
        self.name.setPlaceholderText("target name (optional)")
        self.keep = QtWidgets.QCheckBox("Keep sculpt")
        self.keep.setToolTip("Hide the sculpt mesh instead of deleting it.")
        self.keep.setChecked(bool(settings.get(SETTINGS_KEY, "keep_sculpt", 0)))
        create = QtWidgets.QPushButton("Create Corrective")
        create.setToolTip(
            "Select the sculpt (or the skinned mesh, then the sculpt) and click, in the same pose: "
            "adds the sculpt as a target before the skin."
        )
        create.clicked.connect(self._create_corrective)
        sculpt.addWidget(start, 0, 0, 1, 2)
        sculpt.addWidget(self.name, 1, 0)
        sculpt.addWidget(self.keep, 1, 1)
        sculpt.addWidget(create, 2, 0, 1, 2)

        # Targets
        targets_box = QtWidgets.QGroupBox("Targets")
        targets = QtWidgets.QGridLayout(targets_box)
        self.mesh_label = QtWidgets.QLabel("No mesh loaded.")
        load = QtWidgets.QPushButton("Load Selected")
        load.setToolTip("List the blendShape targets of the selected mesh.")
        load.clicked.connect(self._load_selected)
        self.nodes = QtWidgets.QComboBox()
        self.nodes.currentTextChanged.connect(self._refresh_targets)
        self.list = QtWidgets.QTreeWidget()
        self.list.setHeaderLabels(["Target", "Weight", "Driven by"])
        self.list.setRootIsDecorated(False)
        self.list.currentItemChanged.connect(self._target_picked)
        self.weight = QtWidgets.QDoubleSpinBox(minimum=0.0, maximum=1.0, decimals=3, singleStep=0.1)
        set_weight = QtWidgets.QPushButton("Set Weight")
        set_weight.clicked.connect(self._set_weight)
        rename = QtWidgets.QPushButton("Rename...")
        rename.clicked.connect(self._rename)
        delete = QtWidgets.QPushButton("Delete")
        delete.clicked.connect(self._delete)
        undrive = QtWidgets.QPushButton("Disconnect")
        undrive.setToolTip("Stop the pose reader driving this target's weight.")
        undrive.clicked.connect(self._undrive)
        targets.addWidget(self.mesh_label, 0, 0, 1, 2)
        targets.addWidget(load, 0, 2)
        targets.addWidget(self.nodes, 1, 0, 1, 3)
        targets.addWidget(self.list, 2, 0, 1, 3)
        targets.addWidget(self.weight, 3, 0)
        targets.addWidget(set_weight, 3, 1)
        targets.addWidget(undrive, 3, 2)
        targets.addWidget(rename, 4, 0, 1, 2)
        targets.addWidget(delete, 4, 2)

        # Pose reader
        reader_box = QtWidgets.QGroupBox("Pose Reader")
        reader = QtWidgets.QGridLayout(reader_box)
        self.axis = QtWidgets.QComboBox()
        self.axis.addItems(["x", "y", "z", "-x", "-y", "-z"])
        self.axis.setCurrentText(settings.get(SETTINGS_KEY, "axis", "x"))
        self.axis.setToolTip("The joint axis to follow, usually the one pointing down the bone.")
        self.cone = QtWidgets.QDoubleSpinBox(minimum=1.0, maximum=180.0, decimals=1, singleStep=5.0)
        self.cone.setValue(float(settings.get(SETTINGS_KEY, "cone_angle", 90.0)))
        self.cone.setToolTip("Degrees away from the pose at which the reader reaches 0.")
        create_reader = QtWidgets.QPushButton("Create on Selected Joint")
        create_reader.setToolTip("In the corrective's pose, select the joint: the reader is 1 in this pose.")
        create_reader.clicked.connect(self._create_reader)
        self.readers = QtWidgets.QComboBox()
        set_cone = QtWidgets.QPushButton("Set Cone Angle")
        set_cone.clicked.connect(self._set_cone)
        drive = QtWidgets.QPushButton("Drive Target")
        drive.setToolTip("Connect this reader to the target picked in the list.")
        drive.clicked.connect(self._drive)
        reader.addWidget(QtWidgets.QLabel("Axis"), 0, 0)
        reader.addWidget(self.axis, 0, 1)
        reader.addWidget(QtWidgets.QLabel("Cone angle"), 0, 2)
        reader.addWidget(self.cone, 0, 3)
        reader.addWidget(create_reader, 1, 0, 1, 4)
        reader.addWidget(self.readers, 2, 0, 1, 4)
        reader.addWidget(set_cone, 3, 0, 1, 2)
        reader.addWidget(drive, 3, 2, 1, 2)

        for box in (sculpt_box, targets_box, reader_box):
            self.layout.addWidget(box)
        self._refresh_readers()

    # -- loading --------------------------------------------------------------

    def _load(self, mesh, node=None):
        self.mesh = mesh
        self.mesh_label.setText(f"Mesh: {short_name(mesh)}")
        self.nodes.blockSignals(True)
        self.nodes.clear()
        self.nodes.addItems(logic.blend_shapes(mesh))
        if node:
            self.nodes.setCurrentText(node)
        self.nodes.blockSignals(False)
        self._refresh_targets()

    def _load_selected(self):
        found = logic.meshes(selected())
        if not found:
            _warn("No mesh selected.")
            return
        mesh = logic.sculpt_base(found[0]) or found[0]
        self._load(mesh)
        if not self.nodes.count():
            _warn(f"{short_name(mesh)} has no blendShape.")

    def _node(self):
        node = self.nodes.currentText()
        if not node or not cmds.objExists(node):
            _warn("Load a mesh with a blendShape first (select it, then Load Selected).")
            return None
        return node

    def _refresh_targets(self, *_):
        current = self._picked_name()
        self.list.clear()
        node = self.nodes.currentText()
        if not node or not cmds.objExists(node):
            return
        for _, name in logic.targets(node):
            driver = logic.target_driver(node, name) or ""
            item = QtWidgets.QTreeWidgetItem([name, f"{logic.weight(node, name):.3f}", driver])
            self.list.addTopLevelItem(item)
            if name == current:
                self.list.setCurrentItem(item)

    def _refresh_readers(self, select=None):
        self.readers.clear()
        self.readers.addItems(logic.pose_readers())
        if select:
            self.readers.setCurrentText(select)

    def _picked_name(self):
        item = self.list.currentItem()
        return item.text(0) if item else None

    def _picked(self):
        """``(node, target)`` picked in the list, or ``None`` after warning."""
        node = self._node()
        if not node:
            return None
        name = self._picked_name()
        if not name:
            _warn("Pick a target in the list first.")
            return None
        return node, name

    def _target_picked(self, item, _previous=None):
        if item:
            self.weight.setValue(float(item.text(1)))

    # -- corrective -----------------------------------------------------------

    def _start_sculpt(self):
        found = logic.meshes(selected())
        if not found:
            _warn("Select the posed, skinned mesh.")
            return
        if not logic.skin_cluster(found[0]):
            _warn(f"{short_name(found[0])} has no skinCluster; the corrective will still go before its deformers.")
        sculpt = logic.start_sculpt(found[0])
        cmds.select(sculpt)

    def _create_corrective(self):
        found = logic.meshes(selected())
        if len(found) >= 2:
            mesh, sculpt = found[0], found[1]
        elif len(found) == 1 and logic.sculpt_base(found[0]):
            mesh, sculpt = logic.sculpt_base(found[0]), found[0]
        else:
            _warn("Select the sculpt made by Start Sculpt, or the skinned mesh then the sculpt.")
            return
        settings.set(SETTINGS_KEY, "keep_sculpt", self.keep.isChecked())
        name = self.name.text().strip() or None
        try:
            node, target = logic.create_corrective(mesh, sculpt, name=name, keep_sculpt=self.keep.isChecked())
        except ValueError as error:
            _warn(str(error))
            return
        self.name.clear()
        self._load(mesh, node)
        for i in range(self.list.topLevelItemCount()):
            if self.list.topLevelItem(i).text(0) == target:
                self.list.setCurrentItem(self.list.topLevelItem(i))
        cmds.select(mesh)

    # -- targets --------------------------------------------------------------

    def _run(self, fn, *args):
        try:
            fn(*args)
        except ValueError as error:
            _warn(str(error))
        self._refresh_targets()

    def _set_weight(self):
        picked = self._picked()
        if picked:
            self._run(logic.set_weight, *picked, self.weight.value())

    def _rename(self):
        picked = self._picked()
        if not picked:
            return
        new, ok = QtWidgets.QInputDialog.getText(self, "Rename Target", "New name:", text=picked[1])
        if ok and new.strip() and new.strip() != picked[1]:
            self._run(logic.rename_target, *picked, new.strip())

    def _delete(self):
        picked = self._picked()
        if picked:
            self._run(logic.delete_target, *picked)

    def _undrive(self):
        picked = self._picked()
        if picked:
            self._run(logic.undrive_target, *picked)

    # -- pose readers ---------------------------------------------------------

    def _create_reader(self):
        joints = selected(node_type="joint")
        if not joints:
            _warn("Select a joint, posed the way the corrective is sculpted.")
            return
        settings.set(SETTINGS_KEY, "axis", self.axis.currentText())
        settings.set(SETTINGS_KEY, "cone_angle", float(self.cone.value()))
        reader = logic.create_pose_reader(joints[0], self.axis.currentText(), self.cone.value())
        self._refresh_readers(reader)

    def _reader(self):
        reader = self.readers.currentText()
        if not reader or not cmds.objExists(reader):
            _warn("Create or pick a pose reader first.")
            self._refresh_readers()
            return None
        return reader

    def _set_cone(self):
        reader = self._reader()
        if reader:
            logic.set_cone_angle(reader, self.cone.value())
            self._refresh_targets()

    def _drive(self):
        reader = self._reader()
        picked = self._picked()
        if reader and picked:
            self._run(logic.drive_target, *picked, reader)
