from kaiju_suite.ui.base_window import ToolWindow


class AnimationToolWindow(ToolWindow):
    TITLE = "Kaiju Animation Tool"

    def build_ui(self):
        self.layout.addStretch()
