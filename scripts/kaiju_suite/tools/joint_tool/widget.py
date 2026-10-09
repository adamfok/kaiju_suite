from kaiju_suite.ui.base_window import ToolWindow


class JointToolWindow(ToolWindow):
    TITLE = "Kaiju Joint Tool"

    def build_ui(self):
        self.layout.addStretch()
