def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.assembler.widget import AssemblerWindow

    AssemblerWindow.show_window()


TOOL = {
    "name": "Assembler",
    "category": "Utilities",
    "launch": show,
    "description": "Browse, run, and import script and scene snippets from a folder.",
}
