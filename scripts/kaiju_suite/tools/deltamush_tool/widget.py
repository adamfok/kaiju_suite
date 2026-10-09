from kaiju_suite.ui.base_window import ToolWindow


class DeltaMushToolWindow(ToolWindow):
    TITLE = "Kaiju DeltaMush Tool"

    def build_ui(self):
        self.layout.addStretch()
