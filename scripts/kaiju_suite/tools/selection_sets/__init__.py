def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.selection_sets.widget import SelectionSetsWindow

    SelectionSetsWindow.show_window()


TOOL = {
    "name": "Selection Sets",
    "category": "Animation",
    "launch": show,
    "description": "Save, recall and mirror sets of controls; select, key and reset rig controls.",
}
