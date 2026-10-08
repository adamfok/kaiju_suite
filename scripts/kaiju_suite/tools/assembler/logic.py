"""Assembler logic: browse a folder of script and scene snippets.

No Qt here, so it can be scripted and tested headless. Functions raise on
bad input instead of warning; the widget decides how to tell the user.
"""

import os
import shutil
from dataclasses import dataclass, field

from maya import cmds, mel

from kaiju_suite.core.log import get_logger
from kaiju_suite.core.undo import undo_chunk, undoable

log = get_logger(__name__)

SCRIPT_EXTS = (".py", ".mel")
SCENE_EXTS = (".ma", ".mb")
SKIP_DIRS = ("__pycache__",)

_SCENE_TYPES = {".ma": "mayaAscii", ".mb": "mayaBinary"}


@dataclass
class Entry:
    name: str
    path: str
    is_dir: bool
    children: list = field(default_factory=list)

    @property
    def ext(self):
        return "" if self.is_dir else os.path.splitext(self.name)[1].lower()


def ext_of(path):
    return os.path.splitext(path)[1].lower()


def scan(root):
    """Return the snippet tree under ``root`` as a list of :class:`Entry`.

    Folders come first, then files, each sorted by name. Hidden entries and
    ``__pycache__`` are skipped; empty folders are kept so items can be
    dropped into them.
    """
    entries = []
    try:
        names = os.listdir(root)
    except OSError:
        log.exception("Cannot list %s", root)
        return entries

    dirs, files = [], []
    for name in sorted(names, key=str.lower):
        if name.startswith("."):
            continue
        path = os.path.join(root, name)
        if os.path.isdir(path):
            if name not in SKIP_DIRS:
                dirs.append(Entry(name, path, True, scan(path)))
        elif ext_of(name) in SCRIPT_EXTS + SCENE_EXTS:
            files.append(Entry(name, path, False))
    return dirs + files


def matches(name, text):
    """Case-insensitive search rule used by the filter box."""
    return text.lower() in name.lower()


def _file_path(directory, name, ext):
    name = name.strip()
    if not name:
        raise ValueError("Please provide a name.")
    if "/" in name or "\\" in name:
        raise ValueError("Name can't contain path separators.")
    if not name.lower().endswith(ext):
        name += ext
    path = os.path.join(directory, name)
    if os.path.exists(path):
        raise FileExistsError(f"Already exists: {name}")
    return path


def create_script(directory, name, ext):
    """Create an empty ``.py`` or ``.mel`` file and return its path."""
    if ext not in SCRIPT_EXTS:
        raise ValueError(f"Not a script extension: {ext}")
    path = _file_path(directory, name, ext)
    with open(path, "w", encoding="utf-8"):
        pass
    return path


def create_scene(directory, name, ext):
    """Export the selection to a new ``.ma``/``.mb`` file and return its path."""
    if ext not in SCENE_EXTS:
        raise ValueError(f"Not a scene extension: {ext}")
    return export_selection(_file_path(directory, name, ext))


def create_folder(directory, name):
    name = name.strip()
    if not name:
        raise ValueError("Please provide a name.")
    path = os.path.join(directory, name)
    if os.path.exists(path):
        raise FileExistsError(f"Already exists: {name}")
    os.makedirs(path)
    return path


def delete_path(path):
    if os.path.isfile(path):
        os.remove(path)
    elif os.path.isdir(path):
        shutil.rmtree(path)
    else:
        raise FileNotFoundError(path)


def move_path(src, target):
    """Move ``src`` into ``target`` (a folder, or a file whose folder is used).

    Returns the new path, or ``src`` unchanged if it's already there.
    """
    src = os.path.normpath(src)
    target_dir = os.path.normpath(target if os.path.isdir(target) else os.path.dirname(target))
    if target_dir == src or target_dir.startswith(src + os.sep):
        raise ValueError("Cannot move a folder into itself.")
    if os.path.dirname(src) == target_dir:
        return src
    new_path = os.path.join(target_dir, os.path.basename(src))
    if os.path.exists(new_path):
        raise FileExistsError(f"Already exists at destination: {os.path.basename(src)}")
    shutil.move(src, new_path)
    return new_path


def run_script(path):
    """Execute a ``.py`` (in ``__main__``) or ``.mel`` file as one undo step."""
    ext = ext_of(path)
    if ext not in SCRIPT_EXTS:
        raise ValueError(f"Not a script: {os.path.basename(path)}")
    with open(path, encoding="utf-8") as f:
        code = f.read()
    with undo_chunk(os.path.basename(path)):
        if ext == ".py":
            import __main__

            exec(compile(code, path, "exec"), __main__.__dict__)
        else:
            mel.eval(code)


@undoable
def import_scene(path):
    """Import a scene into the current one, merging namespaces on clash.

    Maya flushes the undo queue on file import, so this can't be undone;
    the chunk still keeps the undo state consistent afterwards.
    """
    if ext_of(path) not in SCENE_EXTS:
        raise ValueError(f"Not a scene: {os.path.basename(path)}")
    return cmds.file(path, i=True, mergeNamespacesOnClash=True, namespace=":", returnNewNodes=True)


def export_selection(path, overwrite=False):
    """Export the current selection to ``path``; type comes from the extension."""
    file_type = _SCENE_TYPES.get(ext_of(path))
    if file_type is None:
        raise ValueError(f"Not a scene: {os.path.basename(path)}")
    if not cmds.ls(selection=True):
        raise RuntimeError("Nothing selected to export.")
    if os.path.exists(path) and not overwrite:
        raise FileExistsError(f"Already exists: {os.path.basename(path)}")
    cmds.file(path, exportSelected=True, type=file_type, force=True)
    return path


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
    if ext_of(path) not in SCRIPT_EXTS:
        raise ValueError(f"Not a script: {os.path.basename(path)}")
    safe = path.replace("\\", "/").replace('"', '\\"')
    mel.eval(_OPEN_IN_EDITOR_MEL % safe)
