def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.builder import logic
    from kaiju_suite.tools.builder.widget import BuilderWindow

    logic.migrate_settings()
    BuilderWindow.show_window()


TOOL = {
    "name": "Builder",
    "launch": show,
    "description": "Run Python scripts from a folder, in your order, with breakpoints to pause a run.",
}
