def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.outliner_tool.widget import OutlinerToolWindow

    OutlinerToolWindow.show_window()


TOOL = {
    "name": "Outliner Tool",
    "launch": show,
    "description": "Rename selected nodes from one field: number (##), add prefix/suffix (*), search and replace (>).",
}
