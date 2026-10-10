def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.wrap_tool.widget import WrapToolWindow

    WrapToolWindow.show_window()


TOOL = {
    "name": "Wrap Tool",
    "category": "Utilities",
    "launch": show,
    "description": "Utilities for Assembler Wrap items.",
}
