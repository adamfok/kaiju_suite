from kaiju_suite.ui.base_window import ToolWindow


class PoseToolWindow(ToolWindow):
    TITLE = "Kaiju Pose Tool"

    def build_ui(self):
        self.layout.addStretch()
