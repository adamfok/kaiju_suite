def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.blendshape_tool.widget import BlendShapeToolWindow

    BlendShapeToolWindow.show_window()


TOOL = {
    "name": "BlendShape Tool",
    "category": "Utilities",
    "launch": show,
    "description": "Sculpt corrective shapes on skinned meshes, drive them with pose readers, and manage targets.",
}
