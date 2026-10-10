def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.attribute_manager.widget import AttributeManagerWindow

    AttributeManagerWindow.show_window()


TOOL = {
    "name": "Attribute Manager",
    "category": "Utilities",
    "launch": show,
    "description": "Utilities for Assembler Attributes items.",
}
