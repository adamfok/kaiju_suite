from maya import cmds
from PySide6 import QtCore, QtWidgets

from kaiju_suite.core.selection import selected
from kaiju_suite.tools.selection_sets import logic
from kaiju_suite.ui.base_window import ToolWindow


def _warn(message):
    cmds.warning(f"Kaiju Selection Sets: {message}")


def _button(label, tip, slot):
    button = QtWidgets.QPushButton(label)
    button.setToolTip(tip)
    button.clicked.connect(slot)
    return button


class SelectionSetsWindow(ToolWindow):
    TITLE = "Kaiju Selection Sets"

    def build_ui(self):
        sets_box = QtWidgets.QGroupBox("Selection Sets")
        sets = QtWidgets.QVBoxLayout(sets_box)
        note = QtWidgets.QLabel(
            "Sets are saved in the scene. Double-click a set to select it; Shift+double-click adds it."
        )
        note.setWordWrap(True)
        sets.addWidget(note)

        self.list = QtWidgets.QListWidget()
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.list.itemDoubleClicked.connect(self._double_clicked)
        sets.addWidget(self.list)

        recall = QtWidgets.QHBoxLayout()
        recall.addWidget(_button("Select", "Select the set's members, replacing the selection.", lambda: self._recall(False)))
        recall.addWidget(_button("Add", "Add the set's members to the selection.", lambda: self._recall(True)))
        recall.addWidget(_button("Refresh", "Reload the list from the scene.", self.refresh))
        sets.addLayout(recall)

        grid = QtWidgets.QGridLayout()
        for index, (label, tip, slot) in enumerate(
            (
                ("Save Selection...", "Save the selected nodes as a new set.", self._save),
                ("Update", "Replace the set's members with the selected nodes.", self._update),
                ("Rename...", "Rename the set.", self._rename),
                ("Delete", "Delete the set (its members are left alone).", self._delete),
                ("Mirror Set", "Create or update the opposite-side set (L_arm -> R_arm) with each member's opposite.", self._mirror),
            )
        ):
            grid.addWidget(_button(label, tip, slot), index // 2, index % 2)
        sets.addLayout(grid)

        pose_box = QtWidgets.QGroupBox("Selection")
        pose = QtWidgets.QHBoxLayout(pose_box)
        pose.addWidget(_button("Select Rig Controls", "Select every control (curve transform) under the selected top nodes.", self._rig_controls))
        pose.addWidget(_button("Key", "Key every keyable attribute of the selection at the current frame.", self._key))
        pose.addWidget(_button("Reset to Default", "Set every keyable attribute of the selection to its default (bind pose).", self._reset))

        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)

        self.layout.addWidget(sets_box)
        self.layout.addWidget(pose_box)
        self.layout.addWidget(self.status)
        self.refresh()

    # -- helpers ------------------------------------------------------------

    def refresh(self, select=None):
        current = select or self._current(warn=False)
        self.list.clear()
        try:
            names = logic.list_sets()
        except ValueError as e:
            _warn(str(e))
            names = []
        for name in names:
            self.list.addItem(name)
        matches = self.list.findItems(current or "", QtCore.Qt.MatchExactly)
        if matches:
            self.list.setCurrentItem(matches[0])

    def _current(self, warn=True):
        item = self.list.currentItem()
        if item is None:
            if warn:
                _warn("Pick a set in the list first.")
            return None
        return item.text()

    def _nodes(self):
        nodes = selected()
        if not nodes:
            _warn("Nothing selected. Select the controls first.")
        return nodes

    def _ask_name(self, title, text=""):
        name, ok = QtWidgets.QInputDialog.getText(self, title, "Set name:", text=text)
        return name.strip() if ok and name.strip() else None

    def _run(self, func, *args):
        """Call ``func``, warning instead of raising on ``ValueError``."""
        try:
            return func(*args), True
        except ValueError as e:
            _warn(str(e))
            return None, False

    # -- sets ---------------------------------------------------------------

    def _double_clicked(self, item):
        add = bool(QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.ShiftModifier)
        self._recall(add, item.text())

    def _recall(self, add, name=None):
        name = name or self._current()
        if not name:
            return
        found, ok = self._run(logic.recall, name, add)
        if ok:
            self.status.setText(f"{'Added' if add else 'Selected'} {len(found)} node(s) from {name}.")
            if not found:
                _warn(f"{name} has no members left.")

    def _save(self):
        nodes = self._nodes()
        if not nodes:
            return
        name = self._ask_name("Save Selection Set")
        if name and self._run(logic.save_set, name, nodes)[1]:
            self.status.setText(f"Saved {len(nodes)} node(s) as {name}.")
            self.refresh(select=name)

    def _update(self):
        name = self._current()
        nodes = name and self._nodes()
        if nodes and self._run(logic.update_set, name, nodes)[1]:
            self.status.setText(f"{name} now holds {len(nodes)} node(s).")

    def _rename(self):
        name = self._current()
        if not name:
            return
        new_name = self._ask_name("Rename Selection Set", name)
        if new_name and new_name != name and self._run(logic.rename_set, name, new_name)[1]:
            self.refresh(select=new_name)

    def _delete(self):
        name = self._current()
        if name and self._run(logic.delete_set, name)[1]:
            self.status.setText(f"Deleted {name}.")
            self.refresh()

    def _mirror(self):
        name = self._current()
        if not name:
            return
        result, ok = self._run(logic.mirror_set, name)
        if ok:
            self.status.setText(f"Mirrored {name} to {result.name}.")
            if result.skipped:
                _warn(f"No opposite for: {', '.join(result.skipped)}")
            self.refresh(select=result.name)

    # -- selection ----------------------------------------------------------

    def _rig_controls(self):
        nodes = self._nodes()
        if not nodes:
            return
        found = logic.select_rig_controls(nodes)
        if found:
            self.status.setText(f"Selected {len(found)} control(s).")
        else:
            _warn("No controls (transforms with curve shapes) under the selected nodes.")

    def _key(self):
        nodes = self._nodes()
        if nodes:
            self.status.setText(f"Keyed {logic.key(nodes)} node(s).")

    def _reset(self):
        nodes = self._nodes()
        if not nodes:
            return
        result = logic.reset(nodes)
        self.status.setText(f"Reset {len(result.changed)} node(s).")
        if result.skipped:
            _warn(f"Skipped: {', '.join(result.skipped)}")
