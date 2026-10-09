def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.pose_tool.widget import PoseToolWindow

    PoseToolWindow.show_window()


TOOL = {
    "name": "Pose Tool",
    "category": "Utilities",
    "launch": show,
    "description": "Utilities for Assembler Pose items.",
}
