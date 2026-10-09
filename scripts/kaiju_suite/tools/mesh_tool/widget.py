from kaiju_suite.ui.base_window import ToolWindow


class MeshToolWindow(ToolWindow):
    TITLE = "Kaiju Mesh Tool"

    def build_ui(self):
        self.layout.addStretch()
