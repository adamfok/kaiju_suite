def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.controlshape_tool.widget import ControlShapeToolWindow

    ControlShapeToolWindow.show_window()


TOOL = {
    "name": "ControlShape Tool",
    "category": "Utilities",
    "launch": show,
    "description": "Control shape library; create, replace, edit, mirror and color control shapes.",
}
