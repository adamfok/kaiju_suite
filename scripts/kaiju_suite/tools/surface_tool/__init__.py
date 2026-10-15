def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.surface_tool.widget import SurfaceToolWindow

    SurfaceToolWindow.show_window()


TOOL = {
    "name": "Surface Tool",
    "category": "Utilities",
    "launch": show,
    "description": "QC the selected NURBS surfaces.",
}
