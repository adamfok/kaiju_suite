def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.space_switch.widget import SpaceSwitchWindow

    SpaceSwitchWindow.show_window()


TOOL = {
    "name": "Space Switch Tool",
    "category": "Animation",
    "launch": show,
    "description": "Switch controls' spaces without a pop.",
}
