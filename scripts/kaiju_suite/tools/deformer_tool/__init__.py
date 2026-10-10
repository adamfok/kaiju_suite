def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.deformer_tool.widget import DeformerToolWindow

    DeformerToolWindow.show_window()


TOOL = {
    "name": "Deformer Tool",
    "category": "Utilities",
    "launch": show,
    "description": "Utilities for Assembler Deformers items.",
}
