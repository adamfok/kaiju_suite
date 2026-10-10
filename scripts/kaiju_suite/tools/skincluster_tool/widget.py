from maya import cmds
from PySide6 import QtWidgets

from kaiju_suite.core import settings
from kaiju_suite.core.selection import selected
from kaiju_suite.tools.skincluster_tool import logic
from kaiju_suite.ui.base_window import ToolWindow

SETTINGS_KEY = "skincluster_tool"
_FAILED = object()


def _warn(message):
    cmds.warning(f"Kaiju SkinCluster Tool: {message}")


class SkinClusterToolWindow(ToolWindow):
    TITLE = "Kaiju SkinCluster Tool"

    def build_ui(self):
        # Copy
        copy_box = QtWidgets.QGroupBox("Copy Skin")
        copy = QtWidgets.QVBoxLayout(copy_box)
        note = QtWidgets.QLabel("Select the source mesh first, then the meshes to copy onto.")
        note.setWordWrap(True)
        copy.addWidget(note)
        modes = QtWidgets.QHBoxLayout()
        self.modes = QtWidgets.QButtonGroup(self)
        saved = settings.get(SETTINGS_KEY, "mode", "closest_point")
        tips = {
            "closest_point": "Each target vertex gets the weights at the closest point on the source.",
            "uv": "Each target vertex gets the weights at the same UV on the source (current UV sets).",
            "topology": "Each target vertex gets the weights of the source vertex with the same ID.",
        }
        for i, mode in enumerate(logic.MODES):
            button = QtWidgets.QRadioButton(logic.MODE_LABELS[mode])
            button.setToolTip(tips[mode])
            button.setChecked(mode == saved)
            self.modes.addButton(button, i)
            modes.addWidget(button)
        if self.modes.checkedButton() is None:
            self.modes.button(0).setChecked(True)
        copy.addLayout(modes)
        copy_button = QtWidgets.QPushButton("Copy Skin")
        copy_button.setToolTip(
            "Unskinned targets are bound to the source's influences; skinned ones get the missing ones."
        )
        copy_button.clicked.connect(self._copy)
        copy.addWidget(copy_button)

        # Mirror
        mirror_box = QtWidgets.QGroupBox("Mirror Skin")
        mirror = QtWidgets.QHBoxLayout(mirror_box)
        self.direction = QtWidgets.QComboBox()
        self.direction.addItem("+X to -X", True)
        self.direction.addItem("-X to +X", False)
        self.direction.setCurrentIndex(0 if settings.get(SETTINGS_KEY, "positive_to_negative", 1) else 1)
        mirror_button = QtWidgets.QPushButton("Mirror")
        mirror_button.setToolTip("Mirror the selected meshes' weights across X; joints are matched by position.")
        mirror_button.clicked.connect(self._mirror)
        mirror.addWidget(self.direction)
        mirror.addWidget(mirror_button)

        # Clean up
        clean_box = QtWidgets.QGroupBox("Clean Up")
        clean = QtWidgets.QGridLayout(clean_box)
        self.threshold = QtWidgets.QDoubleSpinBox(minimum=0.0001, maximum=0.5, decimals=4, singleStep=0.005)
        self.threshold.setValue(settings.get(SETTINGS_KEY, "prune", 0.01))
        prune = QtWidgets.QPushButton("Prune Weights")
        prune.setToolTip("Zero the weights below the threshold on the selected meshes, then normalize.")
        prune.clicked.connect(self._prune)
        unused = QtWidgets.QPushButton("Remove Unused Influences")
        unused.setToolTip("Remove influences that have no weight on any vertex of the selected meshes.")
        unused.clicked.connect(self._remove_unused)
        influences = QtWidgets.QPushButton("Select Influences")
        influences.setToolTip("Select the influences of the selected meshes' skinClusters.")
        influences.clicked.connect(self._select_influences)
        clean.addWidget(QtWidgets.QLabel("Threshold"), 0, 0)
        clean.addWidget(self.threshold, 0, 1)
        clean.addWidget(prune, 0, 2)
        clean.addWidget(unused, 1, 0, 1, 3)
        clean.addWidget(influences, 2, 0, 1, 3)

        # Weights
        weights_box = QtWidgets.QGroupBox("Weights")
        weights = QtWidgets.QGridLayout(weights_box)
        self.max_influences = QtWidgets.QSpinBox(minimum=1, maximum=16)
        self.max_influences.setValue(settings.get(SETTINGS_KEY, "max_influences", 4))
        limit = QtWidgets.QPushButton("Limit Influences")
        limit.setToolTip("Keep only the largest weights on each vertex of the selected meshes, then normalize.")
        limit.clicked.connect(self._limit)
        normalize = QtWidgets.QPushButton("Normalize Weights")
        normalize.setToolTip("Scale each vertex's weights on the selected meshes to sum to 1.")
        normalize.clicked.connect(self._normalize)
        hammer = QtWidgets.QPushButton("Weight Hammer")
        hammer.setToolTip("Give each selected vertex the average weights of its neighbors.")
        hammer.clicked.connect(self._hammer)
        copy_weights = QtWidgets.QPushButton("Copy Vertex Weights")
        copy_weights.setToolTip("Remember the weights of the one selected vertex.")
        copy_weights.clicked.connect(self._copy_weights)
        paste_weights = QtWidgets.QPushButton("Paste Vertex Weights")
        paste_weights.setToolTip("Give the selected vertices (or edges, faces) the copied weights.")
        paste_weights.clicked.connect(self._paste_weights)
        weights.addWidget(QtWidgets.QLabel("Max influences"), 0, 0)
        weights.addWidget(self.max_influences, 0, 1)
        weights.addWidget(limit, 0, 2)
        weights.addWidget(normalize, 1, 0, 1, 3)
        weights.addWidget(hammer, 2, 0, 1, 3)
        weights.addWidget(copy_weights, 3, 0, 1, 2)
        weights.addWidget(paste_weights, 3, 2)
        self._copied = None

        # Influences
        influences_box = QtWidgets.QGroupBox("Influences")
        influences_layout = QtWidgets.QHBoxLayout(influences_box)
        add = QtWidgets.QPushButton("Add Joints")
        add.setToolTip("Add the selected joints to the selected mesh's skinCluster, at zero weight.")
        add.clicked.connect(self._add_influences)
        remove = QtWidgets.QPushButton("Remove Joints")
        remove.setToolTip(
            "Remove the selected joints from the selected mesh's skinCluster; their weight goes to the other "
            "influences, so weights stay normalized."
        )
        remove.clicked.connect(self._remove_influences)
        influences_layout.addWidget(add)
        influences_layout.addWidget(remove)

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)

        for box in (copy_box, mirror_box, clean_box, weights_box, influences_box):
            self.layout.addWidget(box)
        self.layout.addWidget(self.status)
        self.layout.addStretch()

    def _meshes(self):
        meshes = logic.meshes(selected())
        if not meshes:
            _warn("No meshes selected.")
        return meshes

    def _run(self, fn, *args):
        """``fn(*args)``, or ``_FAILED`` after warning why it couldn't run."""
        try:
            return fn(*args)
        except ValueError as e:
            _warn(str(e))
            return _FAILED

    def _copy(self):
        mode = logic.MODES[self.modes.checkedId()]
        settings.set(SETTINGS_KEY, "mode", mode)
        meshes = self._meshes()
        if len(meshes) < 2:
            if meshes:
                _warn("Select the source mesh first, then at least one target mesh.")
            return
        clusters = self._run(logic.copy_skin, meshes[0], meshes[1:], mode)
        if clusters is not _FAILED:
            self.status.setText(f"Copied by {logic.MODE_LABELS[mode].lower()} onto: {', '.join(clusters)}.")

    def _mirror(self):
        positive = self.direction.currentData()
        settings.set(SETTINGS_KEY, "positive_to_negative", bool(positive))
        meshes = self._meshes()
        if meshes and self._run(logic.mirror_skin, meshes, positive) is not _FAILED:
            self.status.setText(f"Mirrored {self.direction.currentText()}.")

    def _prune(self):
        settings.set(SETTINGS_KEY, "prune", self.threshold.value())
        meshes = self._meshes()
        if meshes and self._run(logic.prune, meshes, self.threshold.value()) is not _FAILED:
            self.status.setText(f"Pruned weights below {self.threshold.value():g}.")

    def _remove_unused(self):
        meshes = self._meshes()
        if not meshes:
            return
        removed = self._run(logic.remove_unused, meshes)
        if removed is not _FAILED:
            self.status.setText(f"Removed: {', '.join(removed)}." if removed else "No unused influences.")

    def _select_influences(self):
        meshes = self._meshes()
        if meshes:
            found = self._run(logic.influences, meshes)
            if found and found is not _FAILED:
                cmds.select(found)

    def _limit(self):
        count = self.max_influences.value()
        settings.set(SETTINGS_KEY, "max_influences", count)
        meshes = self._meshes()
        if meshes and self._run(logic.limit_influences, meshes, count) is not _FAILED:
            self.status.setText(f"Limited to {count} influence(s) per vertex.")

    def _normalize(self):
        meshes = self._meshes()
        if meshes and self._run(logic.normalize, meshes) is not _FAILED:
            self.status.setText("Normalized weights.")

    def _hammer(self):
        if self._run(logic.hammer, selected()) is not _FAILED:
            self.status.setText("Hammered the selected vertices.")

    def _copy_weights(self):
        copied = self._run(logic.copy_vertex_weights, selected())
        if copied is not _FAILED:
            self._copied = copied
            listed = ", ".join(f"{name} {w:.3f}" for name, w in copied.items())
            self.status.setText(f"Copied: {listed}.")

    def _paste_weights(self):
        if not self._copied:
            _warn("No weights copied. Select one vertex and click Copy Vertex Weights first.")
            return
        if self._run(logic.paste_vertex_weights, self._copied, selected()) is not _FAILED:
            self.status.setText("Pasted the copied weights.")

    def _mesh_and_joints(self):
        """``(mesh, joints)`` from the selection, or ``None`` after warning."""
        sel = selected()
        meshes = logic.meshes(sel)
        joints = cmds.ls(sel, type="joint", long=True)
        if len(meshes) != 1 or not joints:
            _warn("Select the joints and one skinned mesh.")
            return None
        return meshes[0], joints

    def _add_influences(self):
        picked = self._mesh_and_joints()
        if picked:
            added = self._run(logic.add_influences, *picked)
            if added is not _FAILED:
                self.status.setText(f"Added: {', '.join(added)}." if added else "Those joints are already influences.")

    def _remove_influences(self):
        picked = self._mesh_and_joints()
        if picked:
            removed = self._run(logic.remove_influences, *picked)
            if removed is not _FAILED:
                self.status.setText(f"Removed: {', '.join(removed)}.")
