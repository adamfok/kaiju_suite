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


# Sizes an icon is drawn at, so it stays sharp under Maya's UI scaling.
SIZES = (16, 20, 24, 32, 48, 64)


def same_when_selected(icon):
    """``icon`` drawn the same when its item is selected.

    Left to itself, the style makes the selected look by tinting the icon with
    the selection color, and Maya's style tints it out of sight."""
    from PySide6 import QtGui

    fixed = QtGui.QIcon()
    for size in SIZES:
        pixmap = icon.pixmap(size, size)
        fixed.addPixmap(pixmap, QtGui.QIcon.Mode.Normal)
        fixed.addPixmap(pixmap, QtGui.QIcon.Mode.Selected)
    return fixed
