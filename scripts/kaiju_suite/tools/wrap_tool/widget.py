from kaiju_suite.ui.base_window import ToolWindow


class WrapToolWindow(ToolWindow):
    TITLE = "Kaiju Wrap Tool"

    def build_ui(self):
        self.layout.addStretch()
