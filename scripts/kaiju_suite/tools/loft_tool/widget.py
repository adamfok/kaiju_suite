from maya import cmds
from PySide6 import QtCore, QtWidgets

from kaiju_suite.core import settings
from kaiju_suite.core.selection import selected
from kaiju_suite.tools.loft_tool import logic
from kaiju_suite.ui.base_window import ToolWindow
from kaiju_suite.ui.qc_tab import QCTab


def _warn(message):
    cmds.warning(f"Kaiju Loft Tool: {message}")


class LoftToolWindow(ToolWindow):
    TITLE = "Kaiju Loft Tool"

    def build_ui(self):
        tabs = QtWidgets.QTabWidget()
        qc = QCTab(
            logic.QC_CHECKS,
            logic.qc_settings(),
            logic.save_qc_setting,
            self._run_qc,
            logic.select_problem,
        )
        tabs.addTab(qc, "QC")
        # A placeholder, so every datatype tool has the same two tabs.
        utilities = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(utilities)
        empty = QtWidgets.QLabel("No loft utilities yet.")
        empty.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        empty.setEnabled(False)
        layout.addWidget(empty)
        tabs.addTab(utilities, "Utilities")
        tabs.setCurrentIndex(settings.get(logic.SETTINGS_KEY, "tab", 0))
        tabs.currentChanged.connect(lambda index: settings.set(logic.SETTINGS_KEY, "tab", index))
        self.layout.addWidget(tabs)

    def _run_qc(self):
        try:
            return logic.run_qc(selected())
        except ValueError as e:
            _warn(str(e))
            return None
