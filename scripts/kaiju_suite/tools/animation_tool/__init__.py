def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.animation_tool.widget import AnimationToolWindow

    AnimationToolWindow.show_window()


TOOL = {
    "name": "Animation Tool",
    "category": "Utilities",
    "launch": show,
    "description": "Mirror and flip animation across sides.",
}
