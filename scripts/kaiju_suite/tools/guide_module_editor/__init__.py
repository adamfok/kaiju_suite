def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.guide_module_editor.widget import GuideModuleEditorWindow

    GuideModuleEditorWindow.show_window()


def open_file(path):
    """Open the editor on the Guide item at ``path`` (Assembler double-click)."""
    from kaiju_suite.tools.guide_module_editor.widget import GuideModuleEditorWindow

    GuideModuleEditorWindow.show_window().open_file(path)


TOOL = {
    "name": "Guide Module Editor",
    "category": "Utilities",
    "launch": show,
    "open": open_file,
    "menu": False,  # opened by double-clicking a Guide item in the Assembler
    "description": "Edit Assembler Guide items: their guides in the scene, saved back to the file.",
}
