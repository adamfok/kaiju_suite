"""Base class for tool windows: dockable, one instance per tool."""

from maya import cmds
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
        self.setObjectName(self.object_name())
        self.setWindowTitle(self.TITLE)
        self.layout = QtWidgets.QVBoxLayout(self)
        self.build_ui()

    def build_ui(self):
        raise NotImplementedError

    @classmethod
    def object_name(cls):
        return f"kaiju_{cls.__name__}"

    @classmethod
    def _delete_leftover_ui(cls):
        # After a reload the Python instance cache is empty, but Maya still
        # holds the old window's workspace control under the same name.
        control = f"{cls.object_name()}WorkspaceControl"
        if cmds.workspaceControl(control, exists=True):
            cmds.deleteUI(control)
        if cmds.window(cls.object_name(), exists=True):
            cmds.deleteUI(cls.object_name())

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
        cls._delete_leftover_ui()
        window = cls()
        cls._instances[cls] = window
        window.show(dockable=True)
        return window
