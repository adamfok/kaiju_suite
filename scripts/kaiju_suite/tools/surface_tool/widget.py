from maya import cmds
from PySide6 import QtWidgets

from kaiju_suite.core.selection import selected
from kaiju_suite.tools.surface_tool import logic
from kaiju_suite.ui.base_window import ToolWindow
from kaiju_suite.ui.qc_tab import QCTab


def _warn(message):
    cmds.warning(f"Kaiju Surface Tool: {message}")


class SurfaceToolWindow(ToolWindow):
    TITLE = "Kaiju Surface Tool"

    def build_ui(self):
        # Tabs, with only QC for now, so a Utilities tab can join it later.
        tabs = QtWidgets.QTabWidget()
        qc = QCTab(
            logic.QC_CHECKS,
            logic.qc_settings(),
            logic.save_qc_setting,
            self._run_qc,
            logic.select_problem,
        )
        tabs.addTab(qc, "QC")
        self.layout.addWidget(tabs)

    def _run_qc(self):
        try:
            return logic.run_qc(selected())
        except ValueError as e:
            _warn(str(e))
            return None
