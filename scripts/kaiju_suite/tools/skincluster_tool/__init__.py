def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.skincluster_tool.widget import SkinClusterToolWindow

    SkinClusterToolWindow.show_window()


TOOL = {
    "name": "SkinCluster Tool",
    "category": "Utility Tools",
    "launch": show,
    "description": "QC the selected skins.",
}
