"""Open scripts in VS Code, in the window already open. No Qt or Maya here."""

import os
import shutil
import subprocess
import sys

# Where the VS Code installer puts its `code` launcher, per user then for
# everyone, when it isn't on PATH.
_INSTALLS = (
    ("LOCALAPPDATA", ("Programs", "Microsoft VS Code", "bin", "code.cmd")),
    ("ProgramFiles", ("Microsoft VS Code", "bin", "code.cmd")),
)


def find_code():
    """The path of VS Code's ``code`` launcher, or ``None`` if it isn't installed."""
    found = shutil.which("code")
    if found:
        return found
    for variable, parts in _INSTALLS:
        root = os.environ.get(variable)
        if root:
            path = os.path.join(root, *parts)
            if os.path.isfile(path):
                return path
    return None


def open_in_vscode(path):
    """Open ``path`` in VS Code, reusing its open window."""
    path = os.path.normpath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"No such file: {path}")
    code = find_code()
    if not code:
        raise RuntimeError("VS Code not found. Install it, or add its 'code' command to PATH.")
    # No console window flashing up for code.cmd on Windows.
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    subprocess.Popen([code, "--reuse-window", path], creationflags=flags)
