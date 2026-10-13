def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.guide_tool.widget import GuideToolWindow

    GuideToolWindow.show_window()


TOOL = {
    "name": "Guide Tool",
    "launch": show,
    "description": "Place a joint chain with move-only guides and build it planar.",
}
