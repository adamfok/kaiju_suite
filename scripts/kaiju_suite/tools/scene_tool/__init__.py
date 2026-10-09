def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.scene_tool.widget import SceneToolWindow

    SceneToolWindow.show_window()


TOOL = {
    "name": "Scene Tool",
    "category": "Utilities",
    "launch": show,
    "description": "Utilities for Assembler Scene items.",
}
