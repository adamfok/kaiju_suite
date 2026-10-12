def show():
    # Imported lazily so building the menu never loads Qt.
    from kaiju_suite.tools.assembler.widget import AssemblerWindow

    AssemblerWindow.show_window()


def open_folder(path):
    """Open the Assembler on the build folder ``path`` (e.g. from the Asset Library)."""
    from kaiju_suite.tools.assembler.widget import AssemblerWindow

    AssemblerWindow.show_window().open_folder(path)


def start_build(path, output_path):
    """Start the empty build folder ``path``: a ``build`` folder holding an
    Output saving to ``output_path`` (e.g. for a new Asset Library rig)."""
    from kaiju_suite.tools.assembler import plan

    return plan.start_build(path, output_path)


TOOL = {
    "name": "Assembler",
    "launch": show,
    "open": open_folder,
    "start_build": start_build,
    "description": "Browse, run, and import script and scene snippets from a folder.",
}
