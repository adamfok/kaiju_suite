def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.asset_library.widget import AssetLibraryWindow

    AssetLibraryWindow.show_window()


def startup():
    """Set ASSET to the remembered current asset when Maya starts."""
    from kaiju_suite.tools.asset_library import logic

    logic.restore_current()


TOOL = {
    "name": "Asset Library",
    "launch": show,
    "startup": startup,
    "description": "Browse assets, import or reference their published files, and pick the current asset.",
}
