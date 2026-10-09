from kaiju_suite.ui.base_window import ToolWindow


class MaterialToolWindow(ToolWindow):
    TITLE = "Kaiju Material Tool"

    def build_ui(self):
        self.layout.addStretch()
