def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.rig_module_editor.widget import RigModuleEditorWindow

    RigModuleEditorWindow.show_window()


def open_file(path):
    """Open the editor on the rig module file at ``path`` (Assembler double-click)."""
    from kaiju_suite.tools.rig_module_editor.widget import RigModuleEditorWindow

    RigModuleEditorWindow.show_window().open_file(path)


TOOL = {
    "name": "Rig Module Editor",
    "category": "Utilities",
    "launch": show,
    "open": open_file,
    "description": "Edit the parameters of Assembler Rig Module items.",
}
