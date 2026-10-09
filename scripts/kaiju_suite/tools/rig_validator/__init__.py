def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.rig_validator.widget import RigValidatorWindow

    RigValidatorWindow.show_window()


TOOL = {
    "name": "Rig Validator",
    "category": "Rigging",
    "launch": show,
    "description": "Check the scene's rig for problems and fix the safe ones.",
}
