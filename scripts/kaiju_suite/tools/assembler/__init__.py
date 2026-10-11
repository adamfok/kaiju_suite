def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.assembler.widget import AssemblerWindow

    AssemblerWindow.show_window()


def open_folder(path):
    """Open the Assembler on the build folder ``path`` (e.g. from the Asset Library)."""
    from kaiju_suite.tools.assembler.widget import AssemblerWindow

    AssemblerWindow.show_window().open_folder(path)


TOOL = {
    "name": "Assembler",
    "launch": show,
    "open": open_folder,
    "description": "Browse, run, and import script and scene snippets from a folder.",
}
