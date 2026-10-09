def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.renamer.widget import RenamerWindow

    RenamerWindow.show_window()


TOOL = {
    "name": "Renamer",
    "launch": show,
    "description": "Rename, number, and search/replace selected nodes.",
}
