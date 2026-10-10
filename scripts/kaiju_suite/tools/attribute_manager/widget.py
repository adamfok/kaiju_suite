from kaiju_suite.ui.base_window import ToolWindow


class AttributeManagerWindow(ToolWindow):
    TITLE = "Kaiju Attribute Manager"

    def build_ui(self):
        self.layout.addStretch()
