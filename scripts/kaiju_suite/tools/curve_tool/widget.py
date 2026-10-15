from maya import cmds
from PySide6 import QtWidgets

from kaiju_suite.core import settings
from kaiju_suite.core.selection import selected
from kaiju_suite.tools.curve_tool import logic
from kaiju_suite.ui.base_window import ToolWindow
from kaiju_suite.ui.qc_tab import QCTab

SETTINGS_KEY = logic.SETTINGS_KEY


def _warn(message):
    cmds.warning(f"Kaiju Curve Tool: {message}")


class CurveToolWindow(ToolWindow):
    TITLE = "Kaiju Curve Tool"

    def build_ui(self):
        # Tabs, though there's only QC for now, so a Utilities tab can join it
        # as in the other datatype tools.
        tabs = QtWidgets.QTabWidget()
        qc = QCTab(
            logic.QC_CHECKS,
            logic.qc_settings(),
            logic.save_qc_setting,
            self._run_qc,
            logic.select_problem,
        )
        tabs.addTab(qc, "QC")
        tabs.setCurrentIndex(settings.get(SETTINGS_KEY, "tab", 0))
        tabs.currentChanged.connect(lambda index: settings.set(SETTINGS_KEY, "tab", index))
        self.layout.addWidget(tabs)

    def _run_qc(self):
        try:
            return logic.run_qc(selected())
        except ValueError as e:
            _warn(str(e))
            return None
