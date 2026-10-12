"""Icons shipped in the module's ``icons/`` folder."""

import os

import kaiju_suite

ICON_DIR = os.path.normpath(
    os.path.join(os.path.dirname(kaiju_suite.__file__), "..", "..", "icons")
)


def path(name):
    """Full path of ``name`` in the icons folder."""
    return os.path.join(ICON_DIR, name)


def icon(name):
    """A ``QIcon`` of ``name`` in the icons folder."""
    from PySide6 import QtGui

    return QtGui.QIcon(path(name))
