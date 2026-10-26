"""Portable file paths: store a path so it still works on another machine.

:func:`to_portable` turns a picked path into the text to store, and
:func:`resolve` turns stored text back into a path to open. Stored text is
one of, in this order of preference:

- relative to a root folder (``files/hero.ma``), when the path is under it,
  so the root can be moved or copied anywhere;
- prefixed with an environment variable (``$ASSET/model/hero.ma``), when the
  path is under that variable's folder, so each machine sets its own;
- absolute, otherwise (and in entries written before this existed).

Stored text always uses forward slashes. No Maya or Qt here.
"""

import os

# Variables :func:`to_portable` tries, in order, for paths outside the root.
DEFAULT_VARIABLES = ("ASSET",)


def _slashes(path):
    return path.replace("\\", "/")


def _has_variable(text):
    return text.startswith(("$", "%"))


def _relative_under(path, folder):
    """``path`` relative to ``folder`` (forward slashes) if it's inside it, else ``None``."""
    path, folder = os.path.normpath(os.path.abspath(path)), os.path.normpath(os.path.abspath(folder))
    try:
        if os.path.normcase(os.path.commonpath([path, folder])) != os.path.normcase(folder):
            return None
    except ValueError:  # different drives
        return None
    if os.path.normcase(path) == os.path.normcase(folder):
        return None
    return _slashes(path[len(folder):].lstrip("\\/"))


def to_portable(path, root, variables=DEFAULT_VARIABLES):
    """The text to store for ``path``: relative to ``root`` when under it,
    else ``$VAR/...`` when under a set variable in ``variables``, else the
    absolute path. Text that already starts with a variable is kept."""
    if _has_variable(path):
        return _slashes(path)
    relative = _relative_under(path, root)
    if relative is not None:
        return relative
    for name in variables:
        value = os.environ.get(name)
        if value:
            under = _relative_under(path, value)
            if under is not None:
                return f"${name}/{under}"
    return _slashes(os.path.normpath(os.path.abspath(path)))


def resolve(stored, root):
    """The path that ``stored`` text points to: variables (``$VAR``,
    ``${VAR}``, ``%VAR%`` on Windows) and ``~`` expanded, relative text
    joined to ``root``. Text with a variable that isn't set is returned as
    it is, so error messages show what's missing."""
    if not stored:
        raise ValueError("No path stored.")
    expanded = os.path.expanduser(os.path.expandvars(stored))
    if _has_variable(expanded):
        return _slashes(expanded)
    if not os.path.isabs(expanded):
        expanded = os.path.join(root, expanded)
    return _slashes(os.path.normpath(expanded))
