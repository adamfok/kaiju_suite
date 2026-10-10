from kaiju_suite.ui.base_window import ToolWindow


class ConstraintToolWindow(ToolWindow):
    TITLE = "Kaiju Constraint Tool"

    def build_ui(self):
        self.layout.addStretch()
