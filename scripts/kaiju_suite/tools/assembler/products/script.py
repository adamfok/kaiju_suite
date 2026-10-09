"""Scripts (.py, .mel): run as a build step, edited in the Script Editor."""

import os

from maya import cmds, mel

from kaiju_suite.core.undo import undo_chunk
from kaiju_suite.tools.assembler.products import Creator, Product, ext_of, new_path

EXTENSIONS = (".py", ".mel")


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
    ext = ext_of(path)
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


# Script Editor tabs opened here call kaijuExecuterTabFileChanged when their
# file changes on disk (e.g. a version is restored). Maya's own handler,
# executerTabFileChanged, parents its "Reload?" dialog to a window that
# doesn't exist in Maya 2026 ("Object 'scriptEditorPanel1Window' not found"),
# so the dialog fails and the tab keeps the old text. This one reloads
# straight away, asking first only if the tab has unsaved edits.
_FILE_CHANGED_MEL = """
global proc kaijuExecuterTabFileChanged(string $file)
{
    global string $gCommandExecuter[];
    global string $gCommandExecuterName[];

    if (!`filetest -r $file`) {
        return;
    }
    int $i;
    for ($i = 0; $i < size($gCommandExecuter); $i++) {
        if ($gCommandExecuterName[$i] != $file) {
            continue;
        }
        string $executer = $gCommandExecuter[$i];
        if (`cmdScrollFieldExecuter -q -modified $executer`) {
            string $answer = `confirmDialog -title "Script Changed on Disk"
                -message ($file + " changed on disk.\\nReload it and lose your unsaved edits in the Script Editor?")
                -button "Reload" -button "Keep My Edits"
                -defaultButton "Keep My Edits" -cancelButton "Keep My Edits" -dismissString "Keep My Edits"`;
            if ($answer != "Reload") {
                continue;
            }
        }
        cmdScrollFieldExecuter -e -loadFile $file $executer;
    }
}

global proc kaijuWatchExecuterFile(string $file)
{
    global string $gCommandExecuter[];
    global string $gCommandExecuterName[];

    int $i;
    for ($i = 0; $i < size($gCommandExecuter); $i++) {
        if ($gCommandExecuterName[$i] == $file) {
            cmdScrollFieldExecuter -e -fileChangedCommand "kaijuExecuterTabFileChanged" $gCommandExecuter[$i];
        }
    }
}
"""


def _mel_path(path):
    return path.replace("\\", "/").replace('"', '\\"')


def watch_in_script_editor(path):
    """Make any open Script Editor tab for ``path`` reload when the file
    changes (GUI Maya only; does nothing in standalone)."""
    if cmds.about(batch=True):
        return
    mel.eval(_FILE_CHANGED_MEL)
    mel.eval(f'kaijuWatchExecuterFile "{_mel_path(path)}"')


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
            delegateCommandToFocusedExecuterWindow "-e -fileChangedCommand kaijuExecuterTabFileChanged" 0;
        }
    }
    kaijuWatchExecuterFile($loadFile);
}
"""


def open_in_script_editor(path):
    """Load a script into its own Script Editor tab (GUI Maya only)."""
    if ext_of(path) not in EXTENSIONS:
        raise ValueError(f"Not a script: {os.path.basename(path)}")
    mel.eval(_FILE_CHANGED_MEL)
    mel.eval(_OPEN_IN_EDITOR_MEL % _mel_path(path))


class ScriptProduct(Product):
    name = "Script"
    extensions = EXTENSIONS
    order = 10
    runnable = True
    versioned = True
    creators = (
        Creator("Script", create_script, [("Python (.py)", ".py"), ("MEL (.mel)", ".mel")], open_after=True),
    )

    def run(self, path):
        run_script(path)

    def open(self, path):
        open_in_script_editor(path)

    def before_replace(self, path):
        watch_in_script_editor(path)


PRODUCT = ScriptProduct()
