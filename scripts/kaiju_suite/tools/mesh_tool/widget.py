from maya import cmds
from PySide6 import QtCore, QtWidgets

from kaiju_suite.core import settings
from kaiju_suite.core.selection import selected, short_name
from kaiju_suite.tools.mesh_tool import logic
from kaiju_suite.ui.base_window import ToolWindow

SETTINGS_KEY = "mesh_tool"
_RESULTS = QtCore.Qt.UserRole


def _warn(message):
    cmds.warning(f"Kaiju Mesh Tool: {message}")


class MeshToolWindow(ToolWindow):
    TITLE = "Kaiju Mesh Tool"

    def build_ui(self):
        disabled = set(filter(None, settings.get(SETTINGS_KEY, "disabled", "").split(",")))

        checks_box = QtWidgets.QGroupBox("Checks")
        grid = QtWidgets.QGridLayout(checks_box)
        self.toggles = {}
        for i, check in enumerate(logic.CHECKS):
            toggle = QtWidgets.QCheckBox(check.label)
            toggle.setToolTip(check.description + ("" if check.fix else "\nNo automatic fix."))
            toggle.setChecked(check.key not in disabled)
            toggle.toggled.connect(self._save_toggles)
            grid.addWidget(toggle, i // 2, i % 2)
            self.toggles[check.key] = toggle

        run = QtWidgets.QPushButton("Check")
        run.setToolTip("Check the selected meshes, or every mesh in the scene if nothing is selected.")
        run.clicked.connect(self._run)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["Problem", "Count"])
        self.tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tree.itemSelectionChanged.connect(self._update_buttons)
        self.tree.itemDoubleClicked.connect(lambda *_: self._select())

        self.status = QtWidgets.QLabel("Select meshes and click Check.")
        self.status.setWordWrap(True)

        buttons = QtWidgets.QHBoxLayout()
        self.select_button = QtWidgets.QPushButton("Select")
        self.select_button.setToolTip("Select what the highlighted rows found (double-clicking a row does the same).")
        self.select_button.clicked.connect(self._select)
        self.fix_button = QtWidgets.QPushButton("Fix")
        self.fix_button.setToolTip("Fix the highlighted rows' problems, then check again.")
        self.fix_button.clicked.connect(self._fix)
        buttons.addWidget(self.select_button)
        buttons.addWidget(self.fix_button)

        self.layout.addWidget(checks_box)
        self.layout.addWidget(run)
        self.layout.addWidget(self.tree, 1)
        self.layout.addWidget(self.status)
        self.layout.addLayout(buttons)
        self._meshes = []
        self._update_buttons()

    def _keys(self):
        return [key for key, toggle in self.toggles.items() if toggle.isChecked()]

    def _save_toggles(self):
        disabled = [key for key, toggle in self.toggles.items() if not toggle.isChecked()]
        settings.set(SETTINGS_KEY, "disabled", ",".join(disabled))

    def _run(self):
        if not self._keys():
            _warn("No checks turned on.")
            return
        self._meshes = logic.meshes(selected())
        if not self._meshes:
            _warn("No meshes to check.")
            return
        self._show(logic.run(self._meshes, self._keys()))

    def _show(self, results):
        self.tree.clear()
        by_check = {}
        for result in results:
            by_check.setdefault(result.check.key, []).append(result)
        for group in by_check.values():
            check = group[0].check
            parent = QtWidgets.QTreeWidgetItem([check.label, str(sum(len(r.items) for r in group))])
            parent.setToolTip(0, check.description)
            parent.setData(0, _RESULTS, group)
            for result in group:
                child = QtWidgets.QTreeWidgetItem([short_name(result.mesh), str(len(result.items))])
                child.setData(0, _RESULTS, [result])
                parent.addChild(child)
            self.tree.addTopLevelItem(parent)
        count = len(self._meshes)
        meshes = f"{count} mesh{'es' if count != 1 else ''}"
        found = f"{len(by_check)} kind{'s' if len(by_check) != 1 else ''} of problem" if results else "no problems"
        self.status.setText(f"Checked {meshes}: {found}.")
        self._update_buttons()

    def _picked(self):
        """The results behind the highlighted rows, each once."""
        found = []
        for item in self.tree.selectedItems():
            for result in item.data(0, _RESULTS) or []:
                if result not in found:
                    found.append(result)
        return found

    def _update_buttons(self):
        picked = self._picked()
        self.select_button.setEnabled(bool(picked))
        self.fix_button.setEnabled(any(r.check.fix for r in picked))

    def _select(self):
        items = [item for result in self._picked() for item in result.items]
        existing = [item for item in items if cmds.objExists(item.split(".", 1)[0])]
        if not existing:
            _warn("Nothing to select; check again.")
            return
        cmds.select(existing)

    def _fix(self):
        by_check = {}
        for result in self._picked():
            if result.check.fix and cmds.objExists(result.mesh):
                by_check.setdefault(result.check.key, []).append(result.mesh)
        for key, meshes in by_check.items():
            try:
                logic.fix(key, meshes)
            except RuntimeError as e:
                _warn(str(e))
        self._meshes = [m for m in self._meshes if cmds.objExists(m)]
        self._show(logic.run(self._meshes, self._keys()))
