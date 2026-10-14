"""Open scripts in Maya's Script Editor, each in its own tab that reloads
when the file changes on disk. Needs the Maya UI; no Qt here."""

import os

from maya import cmds, mel

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
    """Load a ``.py`` file into its own Script Editor tab, or focus its tab
    if it's already open (GUI Maya only)."""
    if os.path.splitext(path)[1].lower() != ".py":
        raise ValueError(f"Not a Python script: {os.path.basename(path)}")
    mel.eval(_FILE_CHANGED_MEL)
    mel.eval(_OPEN_IN_EDITOR_MEL % _mel_path(path))
