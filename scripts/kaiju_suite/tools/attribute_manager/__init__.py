def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.attribute_manager.widget import AttributeManagerWindow

    AttributeManagerWindow.show_window()


TOOL = {
    "name": "Attribute Manager",
    "category": "Rigging",
    "launch": show,
    "description": "Add, rename, reorder, lock/hide and delete custom attributes on many nodes at once.",
}
