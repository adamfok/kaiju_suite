def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.deltamush_tool.widget import DeltaMushToolWindow

    DeltaMushToolWindow.show_window()


TOOL = {
    "name": "DeltaMush Tool",
    "category": "Utility Tools",
    "launch": show,
    "description": "QC the selected meshes' deltaMush.",
}
