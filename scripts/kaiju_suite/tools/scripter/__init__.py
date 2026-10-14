def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.scripter.widget import ScripterWindow

    ScripterWindow.show_window()


TOOL = {
    "name": "Scripter",
    "launch": show,
    "description": "Run Python scripts from a folder, in your order, with breakpoints to pause a run.",
}
