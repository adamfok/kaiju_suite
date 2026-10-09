from kaiju_suite.ui.base_window import ToolWindow


class ControlShapeToolWindow(ToolWindow):
    TITLE = "Kaiju ControlShape Tool"

    def build_ui(self):
        self.layout.addStretch()
