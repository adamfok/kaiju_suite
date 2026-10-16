def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.joint_tool.widget import JointToolWindow

    JointToolWindow.show_window()


TOOL = {
    "name": "Joint Tool",
    "category": "Utility Tools",
    "launch": show,
    "description": "QC the selected joints.",
}
