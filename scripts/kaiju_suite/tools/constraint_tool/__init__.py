def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.constraint_tool.widget import ConstraintToolWindow

    ConstraintToolWindow.show_window()


TOOL = {
    "name": "Constraint Tool",
    "category": "Utilities",
    "launch": show,
    "description": "Utilities for Assembler Constraints items.",
}
