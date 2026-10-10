from maya import cmds
from PySide6 import QtCore, QtWidgets

from kaiju_suite.core import settings
from kaiju_suite.core.selection import short_name
from kaiju_suite.tools.rig_validator import logic
from kaiju_suite.ui.base_window import ToolWindow

SETTINGS_KEY = "rig_validator"
# Each row holds (check, items): every item for a check's row, one for a child.
_FOUND = QtCore.Qt.UserRole


def _warn(message):
    cmds.warning(f"Kaiju Rig Validator: {message}")


class RigValidatorWindow(ToolWindow):
    TITLE = "Kaiju Rig Validator"

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

        run = QtWidgets.QPushButton("Check Scene")
        run.setToolTip("Run the turned-on checks on the whole scene.")
        run.clicked.connect(self._run)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["Problem", "Count"])
        self.tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tree.itemSelectionChanged.connect(self._update_buttons)
        self.tree.itemDoubleClicked.connect(lambda *_: self._select())

        self.status = QtWidgets.QLabel("Click Check Scene.")
        self.status.setWordWrap(True)

        buttons = QtWidgets.QHBoxLayout()
        self.select_button = QtWidgets.QPushButton("Select")
        self.select_button.setToolTip("Select what the highlighted rows found (double-clicking a row does the same).")
        self.select_button.clicked.connect(self._select)
        self.fix_button = QtWidgets.QPushButton("Fix")
        self.fix_button.setToolTip("Fix the highlighted rows' problems (one undo step each), then check again.")
        self.fix_button.clicked.connect(self._fix)
        buttons.addWidget(self.select_button)
        buttons.addWidget(self.fix_button)

        self.layout.addWidget(checks_box)
        self.layout.addWidget(run)
        self.layout.addWidget(self.tree, 1)
        self.layout.addWidget(self.status)
        self.layout.addLayout(buttons)
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
        self._show(logic.run(self._keys()))

    def _show(self, results):
        self.tree.clear()
        for result in results:
            check = result.check
            parent = QtWidgets.QTreeWidgetItem([check.label, str(len(result.items))])
            parent.setToolTip(0, check.description)
            parent.setData(0, _FOUND, (check, list(result.items)))
            for item in result.items:
                child = QtWidgets.QTreeWidgetItem([short_name(item), ""])
                child.setToolTip(0, item)
                child.setData(0, _FOUND, (check, [item]))
                parent.addChild(child)
            self.tree.addTopLevelItem(parent)
        found = f"{len(results)} kind{'s' if len(results) != 1 else ''} of problem" if results else "no problems"
        self.status.setText(f"Checked the scene: {found}.")
        self._update_buttons()

    def _picked(self):
        """The highlighted rows' items, as {check key: (check, items)}."""
        found = {}
        for row in self.tree.selectedItems():
            check, items = row.data(0, _FOUND)
            picked = found.setdefault(check.key, (check, []))[1]
            picked.extend(item for item in items if item not in picked)
        return found

    def _update_buttons(self):
        picked = self._picked().values()
        self.select_button.setEnabled(bool(picked))
        self.fix_button.setEnabled(any(check.fix for check, _ in picked))

    def _select(self):
        targets = []
        for key, (_, items) in self._picked().items():
            targets += logic.select_targets(key, items)
        if not targets:
            _warn("Nothing to select; check again.")
            return
        cmds.select(targets)

    def _fix(self):
        for key, (check, items) in self._picked().items():
            if not check.fix:
                continue
            try:
                logic.fix(key, items)
            except RuntimeError as e:
                _warn(f"{check.label}: {e}")
        self._run()
