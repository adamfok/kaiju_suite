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

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)

        for box in (copy_box, mirror_box, clean_box):
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
