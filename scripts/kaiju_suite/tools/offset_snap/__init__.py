def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.offset_snap.widget import OffsetSnapWindow

    OffsetSnapWindow.show_window()


TOOL = {
    "name": "Offset & Snap Tool",
    "category": "Rigging",
    "launch": show,
    "description": "Add zero/offset groups, snap nodes to each other, place at centroid, zero out controls.",
}
