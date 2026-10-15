from maya import cmds
from PySide6 import QtCore, QtWidgets

from kaiju_suite.core import settings
from kaiju_suite.core.selection import selected
from kaiju_suite.tools.mesh_tool import logic
from kaiju_suite.ui.base_window import ToolWindow
from kaiju_suite.ui.qc_tab import QCTab

SETTINGS_KEY = logic.SETTINGS_KEY


def _warn(message):
    cmds.warning(f"Kaiju Mesh Tool: {message}")


class MeshToolWindow(ToolWindow):
    TITLE = "Kaiju Mesh Tool"

    def build_ui(self):
        tabs = QtWidgets.QTabWidget()
        qc = QCTab(
            logic.QC_CHECKS,
            logic.qc_settings(),
            logic.save_qc_setting,
            self._run_qc,
            logic.select_problem,
            on_fix=self._fix,
        )
        tabs.addTab(qc, "QC")
        # A placeholder, so every datatype tool has the same two tabs.
        utilities = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(utilities)
        empty = QtWidgets.QLabel("No mesh utilities yet.")
        empty.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        empty.setEnabled(False)
        layout.addWidget(empty)
        tabs.addTab(utilities, "Utilities")
        tabs.setCurrentIndex(settings.get(SETTINGS_KEY, "tab", 0))
        tabs.currentChanged.connect(lambda index: settings.set(SETTINGS_KEY, "tab", index))
        self.layout.addWidget(tabs)

    def _attempt(self, fn, *args):
        """``fn(*args)``, or ``None`` after warning why it couldn't run."""
        try:
            return fn(*args)
        except ValueError as e:
            _warn(str(e))
            return None

    def _run_qc(self):
        return self._attempt(logic.run_qc, selected())

    def _fix(self, check):
        return self._attempt(logic.fix_and_check, check.key, selected())
