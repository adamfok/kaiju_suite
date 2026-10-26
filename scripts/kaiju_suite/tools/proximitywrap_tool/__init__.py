def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.proximitywrap_tool.widget import ProximityWrapToolWindow

    ProximityWrapToolWindow.show_window()


TOOL = {
    "name": "ProximityWrap Tool",
    "category": "Utility Tools",
    "launch": show,
    "description": "QC the proximityWraps on the selected meshes.",
}
