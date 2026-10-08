from maya import cmds
from PySide6 import QtWidgets

from kaiju_suite.core import settings
from kaiju_suite.core.selection import selected
from kaiju_suite.tools.renamer import logic
from kaiju_suite.ui.base_window import ToolWindow

SETTINGS_KEY = "renamer"


class RenamerWindow(ToolWindow):
    TITLE = "Kaiju Renamer"

    def build_ui(self):
        # Sequential rename
        seq_box = QtWidgets.QGroupBox("Rename && Number")
        seq = QtWidgets.QFormLayout(seq_box)
        self.pattern = QtWidgets.QLineEdit(settings.get(SETTINGS_KEY, "pattern", "node_##"))
        self.pattern.setToolTip("Use # for the number; ## pads to two digits.")
        self.start = QtWidgets.QSpinBox(minimum=0, maximum=99999, value=1)
        seq_btn = QtWidgets.QPushButton("Rename")
        seq_btn.clicked.connect(self._rename_sequential)
        seq.addRow("Pattern", self.pattern)
        seq.addRow("Start", self.start)
        seq.addRow(seq_btn)

        # Search / replace
        sr_box = QtWidgets.QGroupBox("Search && Replace")
        sr = QtWidgets.QFormLayout(sr_box)
        self.search = QtWidgets.QLineEdit()
        self.replace = QtWidgets.QLineEdit()
        sr_btn = QtWidgets.QPushButton("Replace")
        sr_btn.clicked.connect(self._search_replace)
        sr.addRow("Search", self.search)
        sr.addRow("Replace", self.replace)
        sr.addRow(sr_btn)

        # Prefix / suffix
        ps_box = QtWidgets.QGroupBox("Prefix && Suffix")
        ps = QtWidgets.QFormLayout(ps_box)
        self.prefix = QtWidgets.QLineEdit()
        self.suffix = QtWidgets.QLineEdit()
        ps_btn = QtWidgets.QPushButton("Add")
        ps_btn.clicked.connect(self._prefix_suffix)
        ps.addRow("Prefix", self.prefix)
        ps.addRow("Suffix", self.suffix)
        ps.addRow(ps_btn)

        for box in (seq_box, sr_box, ps_box):
            self.layout.addWidget(box)
        self.layout.addStretch()

    def _nodes(self):
        nodes = selected()
        if not nodes:
            cmds.warning("Kaiju Renamer: nothing selected.")
        return nodes

    def _rename_sequential(self):
        nodes = self._nodes()
        if nodes:
            settings.set(SETTINGS_KEY, "pattern", self.pattern.text())
            cmds.select(logic.rename_sequential(nodes, self.pattern.text(), self.start.value()))

    def _search_replace(self):
        nodes = self._nodes()
        if nodes:
            cmds.select(logic.search_replace(nodes, self.search.text(), self.replace.text()))

    def _prefix_suffix(self):
        nodes = self._nodes()
        if nodes:
            cmds.select(logic.add_prefix_suffix(nodes, self.prefix.text(), self.suffix.text()))
