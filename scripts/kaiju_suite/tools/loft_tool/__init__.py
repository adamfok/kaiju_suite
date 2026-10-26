def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.loft_tool.widget import LoftToolWindow

    LoftToolWindow.show_window()


TOOL = {
    "name": "Loft Tool",
    "category": "Utility Tools",
    "launch": show,
    "description": "QC the selected lofted NURBS surfaces.",
}
