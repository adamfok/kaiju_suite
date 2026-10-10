from kaiju_suite.ui.base_window import ToolWindow


class DeformerToolWindow(ToolWindow):
    TITLE = "Kaiju Deformer Tool"

    def build_ui(self):
        self.layout.addStretch()
