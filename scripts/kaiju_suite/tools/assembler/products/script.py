"""Scripts (.py, .mel): run as a build step, edited in the Script Editor."""

import os

from maya import mel

from kaiju_suite.core.undo import undo_chunk
from kaiju_suite.tools.assembler.products import Creator, Product, new_path

EXTENSIONS = (".py", ".mel")


def _ext(path):
    return os.path.splitext(path)[1].lower()


def create_script(directory, name, ext):
    """Create an empty ``.py`` or ``.mel`` file and return its path."""
    if ext not in EXTENSIONS:
        raise ValueError(f"Not a script extension: {ext}")
    path = new_path(directory, name, ext)
    with open(path, "w", encoding="utf-8"):
        pass
    return path


def run_script(path):
    """Execute a ``.py`` (in ``__main__``) or ``.mel`` file as one undo step."""
    ext = _ext(path)
    if ext not in EXTENSIONS:
        raise ValueError(f"Not a script: {os.path.basename(path)}")
    with open(path, encoding="utf-8") as f:
        code = f.read()
    with undo_chunk(os.path.basename(path)):
        if ext == ".py":
            import __main__

            exec(compile(code, path, "exec"), __main__.__dict__)
        else:
            mel.eval(code)


# Opens a file in a new Script Editor tab, or focuses its tab if already open.
# Needs the Script Editor UI, so it can't run in standalone.
_OPEN_IN_EDITOR_MEL = """
{
    global string $gCommandExecuterTabs;
    global string $gLastFocusedCommandExecuter;

    if (size($gCommandExecuterTabs) == 0 || !`tabLayout -exists $gCommandExecuterTabs`) {
        ScriptEditor;
    }

    string $loadFile = "%s";

    if (!selectExecuterTabByName($loadFile)) {
        string $ext = fileExtension($loadFile);

        int $sel = 1;
        if ($ext == "py") {
            buildNewExecuterTab(-1, "Python", "python", 0);
        } else if ($ext == "mel") {
            buildNewExecuterTab(-1, "MEL", "mel", 0);
        } else {
            $sel = 0;
            addNewExecuterTab("", 0);
        }

        if ($sel) {
            tabLayout -e -selectTabIndex `tabLayout -q -numberOfChildren $gCommandExecuterTabs` $gCommandExecuterTabs;
            selectCurrentExecuterControl();
        }

        delegateCommandToFocusedExecuterWindow("-e -loadFile \\"" + $loadFile + "\\"", 0);

        string $filename = `cmdScrollFieldExecuter -query -filename $gLastFocusedCommandExecuter`;
        if (size($filename) > 0) {
            renameCurrentExecuterTab($filename, 0);
            delegateCommandToFocusedExecuterWindow "-e -modificationChangedCommand executerTabModificationChanged" 0;
            delegateCommandToFocusedExecuterWindow "-e -fileChangedCommand executerTabFileChanged" 0;
        }
    }
}
"""


def open_in_script_editor(path):
    """Load a script into its own Script Editor tab (GUI Maya only)."""
    if _ext(path) not in EXTENSIONS:
        raise ValueError(f"Not a script: {os.path.basename(path)}")
    safe = path.replace("\\", "/").replace('"', '\\"')
    mel.eval(_OPEN_IN_EDITOR_MEL % safe)


class ScriptProduct(Product):
    name = "Script"
    extensions = EXTENSIONS
    order = 10
    runnable = True
    creators = (
        Creator("Script", create_script, [("Python (.py)", ".py"), ("MEL (.mel)", ".mel")], open_after=True),
    )

    def run(self, path):
        run_script(path)

    def open(self, path):
        open_in_script_editor(path)


PRODUCT = ScriptProduct()
