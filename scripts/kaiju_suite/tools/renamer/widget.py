from html import escape

from maya import cmds
from maya.api import OpenMaya as om
from PySide6 import QtWidgets

from kaiju_suite.core import settings
from kaiju_suite.core.selection import selected
from kaiju_suite.tools.renamer import logic
from kaiju_suite.ui.base_window import ToolWindow

SETTINGS_KEY = "renamer"


def _remove_callback(callback_id):
    try:
        om.MMessage.removeCallback(callback_id)
    except RuntimeError:
        pass  # already removed


class RenamerWindow(ToolWindow):
    """One text field; what you type decides the action (see ``logic.SHORTCUTS``)."""

    TITLE = "Kaiju Renamer"

    def build_ui(self):
        row = QtWidgets.QHBoxLayout()
        self.field = QtWidgets.QLineEdit(settings.get(SETTINGS_KEY, "text", ""))
        self.field.setPlaceholderText("L_arm_##_jnt   *_jnt   L_*   old > new")
        self.field.textChanged.connect(self._update_preview)
        self.field.returnPressed.connect(self._rename)
        help_btn = QtWidgets.QToolButton(text="?")
        help_btn.setToolTip("Show the shortcuts")
        # A menu, not a Qt.Popup window: Maya closes menus on any click, but a
        # popup only closed on clicks outside Maya.
        help_btn.setMenu(self._help_menu())
        help_btn.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        help_btn.setStyleSheet("QToolButton::menu-indicator { image: none; }")
        row.addWidget(self.field)
        row.addWidget(help_btn)

        self.preview = QtWidgets.QLabel()

        self.layout.addLayout(row)
        self.layout.addWidget(self.preview)
        self.layout.addStretch()

        # Keep the preview in step with the selection while the window is open.
        self._callback = om.MEventMessage.addEventCallback(
            "SelectionChanged", lambda *_: self._update_preview()
        )
        callback = self._callback
        self.destroyed.connect(lambda *_: _remove_callback(callback))
        self._update_preview()

    def dockCloseEventTriggered(self):
        _remove_callback(self._callback)

    def _update_preview(self):
        try:
            line, problem = logic.preview(selected(), self.field.text())
            self.preview.setText(line)
            self.preview.setStyleSheet("color: orange;" if problem else "color: gray;")
        except RuntimeError:
            pass  # Maya fired the callback after the Qt widget was deleted.

    def _rename(self):
        nodes = selected()
        if not nodes:
            cmds.warning("Kaiju Renamer: nothing selected.")
            return
        text = self.field.text()
        try:
            new = logic.rename(nodes, text)
        except ValueError as e:
            cmds.warning(f"Kaiju Renamer: {e}")
            return
        settings.set(SETTINGS_KEY, "text", text)
        cmds.select(new)

    def _help_menu(self):
        rows = "".join(
            f"<tr><td><code>{escape(example)}</code>&nbsp;&nbsp;</td><td>{escape(action)}</td></tr>"
            for example, action in logic.SHORTCUTS
        )
        label = QtWidgets.QLabel(
            f"<b>Renamer shortcuts</b><table>{rows}</table><br>Enter applies to the selection."
        )
        label.setContentsMargins(10, 8, 10, 8)
        menu = QtWidgets.QMenu(self)
        action = QtWidgets.QWidgetAction(menu)
        action.setDefaultWidget(label)
        menu.addAction(action)
        return menu
