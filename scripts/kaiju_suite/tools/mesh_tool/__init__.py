def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.mesh_tool.widget import MeshToolWindow

    MeshToolWindow.show_window()


TOOL = {
    "name": "Mesh Tool",
    "category": "Utilities",
    "launch": show,
    "description": "Check meshes for problems and fix some of them.",
}
