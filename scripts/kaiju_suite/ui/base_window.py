"""Base class for tool windows: dockable, one instance per tool."""

from maya.app.general.mayaMixin import MayaQWidgetDockableMixin
from PySide6 import QtWidgets


class ToolWindow(MayaQWidgetDockableMixin, QtWidgets.QWidget):
    """Subclass, set ``TITLE``, and build widgets in ``build_ui``.

    Open it with ``MyWindow.show_window()``; calling again brings the
    existing window to the front instead of opening a second copy.
    """

    TITLE = "Kaiju Tool"
    _instances = {}

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName(f"kaiju_{type(self).__name__}")
        self.setWindowTitle(self.TITLE)
        self.layout = QtWidgets.QVBoxLayout(self)
        self.build_ui()

    def build_ui(self):
        raise NotImplementedError

    @classmethod
    def show_window(cls):
        window = cls._instances.get(cls)
        if window is not None:
            try:
                window.show(dockable=True)
                window.raise_()
                return window
            except RuntimeError:
                # The underlying Qt object was deleted (e.g. Maya closed it).
                pass
        window = cls()
        cls._instances[cls] = window
        window.show(dockable=True)
        return window
