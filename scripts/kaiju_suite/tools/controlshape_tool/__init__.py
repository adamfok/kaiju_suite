def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.controlshape_tool.widget import ControlShapeToolWindow

    ControlShapeToolWindow.show_window()


TOOL = {
    "name": "ControlShape Tool",
    "category": "Utilities",
    "launch": show,
    "description": "Utilities for Assembler ControlShape items.",
}
