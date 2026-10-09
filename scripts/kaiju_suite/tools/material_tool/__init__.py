def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.material_tool.widget import MaterialToolWindow

    MaterialToolWindow.show_window()


TOOL = {
    "name": "Material Tool",
    "category": "Utilities",
    "launch": show,
    "description": "Utilities for Assembler Material items.",
}
