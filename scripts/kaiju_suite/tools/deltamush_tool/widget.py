from maya import cmds, mel
from PySide6 import QtWidgets

from kaiju_suite.core import settings
from kaiju_suite.core.selection import selected, short_name
from kaiju_suite.tools.deltamush_tool import logic
from kaiju_suite.ui.base_window import ToolWindow

SETTINGS_KEY = "deltamush_tool"


def _warn(message):
    cmds.warning(f"Kaiju DeltaMush Tool: {message}")


class DeltaMushToolWindow(ToolWindow):
    TITLE = "Kaiju DeltaMush Tool"

    def build_ui(self):
        self.mesh = None

        # Add
        add_box = QtWidgets.QGroupBox("Add")
        add = QtWidgets.QHBoxLayout(add_box)
        self.start = QtWidgets.QComboBox()
        self.start.addItem("Start at 0 (paint it in)", 0.0)
        self.start.addItem("Start at 1 (paint it out)", 1.0)
        self.start.setCurrentIndex(1 if settings.get(SETTINGS_KEY, "start", 0) else 0)
        add_button = QtWidgets.QPushButton("Add DeltaMush")
        add_button.setToolTip("Add a deltaMush on top of the selected meshes' deformers.")
        add_button.clicked.connect(self._add)
        add.addWidget(self.start)
        add.addWidget(add_button)

        # Which deltaMush
        target_box = QtWidgets.QGroupBox("DeltaMush")
        target = QtWidgets.QGridLayout(target_box)
        self.mesh_label = QtWidgets.QLabel("No mesh loaded.")
        load = QtWidgets.QPushButton("Load Selected")
        load.setToolTip("Edit the deltaMush of the selected mesh.")
        load.clicked.connect(self._load_selected)
        self.nodes = QtWidgets.QComboBox()
        paint = QtWidgets.QPushButton("Paint")
        paint.setToolTip("Open Maya's Paint Attributes tool on this deltaMush's weights.")
        paint.clicked.connect(self._paint)
        target.addWidget(self.mesh_label, 0, 0)
        target.addWidget(load, 0, 1)
        target.addWidget(self.nodes, 1, 0)
        target.addWidget(paint, 1, 1)

        # Weights
        weights_box = QtWidgets.QGroupBox("Weights")
        weights = QtWidgets.QGridLayout(weights_box)
        self.value = QtWidgets.QDoubleSpinBox(minimum=0.0, maximum=1.0, decimals=3, singleStep=0.1, value=1.0)
        set_button = QtWidgets.QPushButton("Set Selected")
        set_button.setToolTip("Set the selected vertices (or faces, edges) to this weight.")
        set_button.clicked.connect(self._set_selected)
        flood = QtWidgets.QPushButton("Flood")
        flood.setToolTip("Set every vertex to this weight.")
        flood.clicked.connect(self._flood)
        invert = QtWidgets.QPushButton("Invert")
        invert.setToolTip("Each weight w becomes 1 - w.")
        invert.clicked.connect(lambda: self._edit(logic.invert))
        mirror_pos = QtWidgets.QPushButton("Mirror +X to -X")
        mirror_pos.clicked.connect(lambda: self._edit(logic.mirror_weights, True))
        mirror_neg = QtWidgets.QPushButton("Mirror -X to +X")
        mirror_neg.clicked.connect(lambda: self._edit(logic.mirror_weights, False))
        affected = QtWidgets.QPushButton("Select Affected")
        affected.setToolTip("Select the vertices this deltaMush acts on (weight above 0).")
        affected.clicked.connect(self._select_affected)
        weights.addWidget(QtWidgets.QLabel("Value"), 0, 0)
        weights.addWidget(self.value, 0, 1)
        weights.addWidget(set_button, 0, 2)
        weights.addWidget(flood, 1, 0)
        weights.addWidget(invert, 1, 1)
        weights.addWidget(affected, 1, 2)
        weights.addWidget(mirror_pos, 2, 0, 1, 2)
        weights.addWidget(mirror_neg, 2, 2)

        for box in (add_box, target_box, weights_box):
            self.layout.addWidget(box)
        self.layout.addStretch()

    # -- which deltaMush -----------------------------------------------------

    def _load(self, mesh, node=None):
        self.mesh = mesh
        self.nodes.clear()
        self.nodes.addItems(logic.delta_mushes(mesh))
        if node:
            self.nodes.setCurrentText(node)
        self.mesh_label.setText(f"Mesh: {short_name(mesh)}")

    def _load_selected(self):
        meshes = logic.meshes(selected())
        if not meshes:
            _warn("No mesh selected.")
            return
        self._load(meshes[0])
        if not self.nodes.count():
            _warn(f"{short_name(meshes[0])} has no deltaMush. Click Add DeltaMush first.")

    def _target(self):
        """``(node, mesh)`` being edited, or ``None`` after warning why not."""
        node = self.nodes.currentText()
        if not self.mesh or not cmds.objExists(self.mesh) or not node or not cmds.objExists(node):
            _warn("Load a mesh with a deltaMush first (select it, then Load Selected).")
            return None
        return node, self.mesh

    # -- actions --------------------------------------------------------------

    def _add(self):
        meshes = logic.meshes(selected())
        if not meshes:
            _warn("No meshes selected.")
            return
        start = self.start.currentData()
        settings.set(SETTINGS_KEY, "start", int(start))
        nodes = logic.add(meshes, start)
        self._load(meshes[0], nodes[0])
        cmds.select(meshes)

    def _paint(self):
        target = self._target()
        if target:
            node, mesh = target
            cmds.select(mesh)
            mel.eval(f'artSetToolAndSelectAttr("artAttrCtx", "{logic.paint_attribute(node)}");')

    def _edit(self, fn, *args):
        target = self._target()
        if target:
            fn(*target, *args)

    def _set_selected(self):
        target = self._target()
        if not target:
            return
        node, mesh = target
        components = logic.components_of(mesh, cmds.ls(selection=True))
        if not components:
            _warn(f"Select vertices, edges or faces of {short_name(mesh)}.")
            return
        logic.set_weights(node, components, self.value.value())

    def _flood(self):
        self._edit(logic.flood, self.value.value())

    def _select_affected(self):
        target = self._target()
        if target:
            found = logic.affected(*target)
            if found:
                cmds.select(found)
            else:
                _warn("This deltaMush acts on no vertices.")
