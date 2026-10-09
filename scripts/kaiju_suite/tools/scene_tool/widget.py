from kaiju_suite.ui.base_window import ToolWindow


class SceneToolWindow(ToolWindow):
    TITLE = "Kaiju Scene Tool"

    def build_ui(self):
        self.layout.addStretch()
