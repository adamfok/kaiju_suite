def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.curve_tool.widget import CurveToolWindow

    CurveToolWindow.show_window()


TOOL = {
    "name": "Curve Tool",
    "category": "Utilities",
    "launch": show,
    "description": "QC the selected NURBS curves.",
}
