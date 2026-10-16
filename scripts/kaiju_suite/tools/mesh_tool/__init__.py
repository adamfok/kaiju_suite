def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.mesh_tool.widget import MeshToolWindow

    MeshToolWindow.show_window()


TOOL = {
    "name": "Mesh Tool",
    "category": "Utility Tools",
    "launch": show,
    "description": "QC the selected meshes and fix some of their problems.",
}
