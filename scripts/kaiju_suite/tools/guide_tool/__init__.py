def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.guide_tool.widget import GuideToolWindow

    GuideToolWindow.show_window()


def open_file(path):
    """Open the window with Name, # Mid, Aim and Up from the Guide item at
    ``path`` (Assembler double-click)."""
    from kaiju_suite.tools.guide_tool.widget import GuideToolWindow

    GuideToolWindow.show_window().open_file(path)


TOOL = {
    "name": "Guide Tool",
    "launch": show,
    "open": open_file,
    "description": "Place a joint chain with move-only guides and build it planar.",
}
