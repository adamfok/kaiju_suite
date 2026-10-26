"""Runs inside the test Maya started by ``maya_ui.py``.

At start-up it moves every Maya window off the screens (unless the run asked
to see them), loads the Kaiju plug-in from the worktree under test, starts
collecting Maya warnings and errors, starts a watcher that records and closes
any modal dialog, opens the command port, and writes ``ready.json``.

``maya_ui.py`` then sends ``run_file(script, result_path)`` over the port.
The script runs with a ``ui`` object (see ``Scenario``) in its globals, and
the result is written to ``result_path`` as JSON.
"""

import contextlib
import json
import os
import re
import sys
import time
import traceback

from maya import cmds, utils
from maya.api import OpenMaya as om
from PySide6 import QtCore, QtGui, QtWidgets

_session_dir = None
_messages = []  # (kind, text, step name or None)
_dialogs = []
_current_step = None
_callback_id = None
_watcher = None


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def boot_later(session_dir):
    """Called from userSetup.py; boots once Maya's UI is up."""
    with open(os.path.join(session_dir, "boot.json"), encoding="utf-8") as f:
        if json.load(f).get("hide"):
            _keep_off_screen()
    utils.executeDeferred(lambda: _boot(session_dir))


OFF_SCREEN = -20000
_off_screen = None


def _on_a_screen(widget):
    rect = widget.frameGeometry()
    return any(screen.geometry().intersects(rect) for screen in QtGui.QGuiApplication.screens())


class _OffScreen(QtCore.QObject):
    """Moves every top-level window off the screens before it's drawn, and
    shows it without taking focus, so the test Maya never gets in the way."""

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind in (QtCore.QEvent.Type.Polish, QtCore.QEvent.Type.Show, QtCore.QEvent.Type.Move) and isinstance(obj, QtWidgets.QWidget) and obj.isWindow():
            if kind == QtCore.QEvent.Type.Polish:
                obj.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating)
            elif _on_a_screen(obj):
                obj.move(OFF_SCREEN, OFF_SCREEN)
        return False


def _keep_off_screen():
    global _off_screen
    app = QtWidgets.QApplication.instance()
    _off_screen = _OffScreen()
    app.installEventFilter(_off_screen)
    for widget in app.topLevelWidgets():  # anything already up, e.g. the main window
        if widget.isVisible() and _on_a_screen(widget):
            widget.move(OFF_SCREEN, OFF_SCREEN)


def _boot(session_dir):
    global _session_dir
    _session_dir = session_dir
    ready = os.path.join(session_dir, "ready.json")
    try:
        with open(os.path.join(session_dir, "boot.json"), encoding="utf-8") as f:
            boot = json.load(f)
        _start_capture()
        cmds.loadPlugin("kaiju_suite_plugin")
        import kaiju_suite

        loaded = os.path.normcase(os.path.realpath(kaiju_suite.__file__))
        expected = os.path.normcase(os.path.realpath(boot["worktree"]))
        if not loaded.startswith(expected + os.sep):
            raise RuntimeError(f"kaiju_suite loaded from {loaded}, not from {expected}")
        cmds.commandPort(name=f"127.0.0.1:{boot['port']}", sourceType="python")
    except Exception:
        _write_json(ready, {"error": traceback.format_exc()})
        return
    # Maya keeps printing start-up messages (Bifrost, deferred plug-in scripts)
    # for a few seconds; say ready only once it has gone quiet, so that noise
    # isn't blamed on the first check.
    _when_quiet(lambda: _write_json(ready, {"port": boot["port"], "kaiju_suite": loaded}))


QUIET_SECONDS = 2.0
SETTLE_LIMIT = 30.0


def _when_quiet(callback):
    start = time.monotonic()
    state = {"count": len(_messages), "since": start}

    def poll():
        now = time.monotonic()
        if len(_messages) != state["count"]:
            state["count"], state["since"] = len(_messages), now
        if now - state["since"] >= QUIET_SECONDS or now - start >= SETTLE_LIMIT:
            callback()
        else:
            QtCore.QTimer.singleShot(250, poll)

    QtCore.QTimer.singleShot(250, poll)


# --- capturing warnings, errors and dialogs ---------------------------------

def _on_output(text, kind, _data):
    if kind == om.MCommandMessage.kWarning:
        _messages.append(("warning", text.strip(), _current_step))
    elif kind == om.MCommandMessage.kError:
        _messages.append(("error", text.strip(), _current_step))


def _start_capture():
    global _callback_id, _watcher
    _callback_id = om.MCommandMessage.addCommandOutputCallback(_on_output)
    _watcher = QtCore.QTimer()
    _watcher.setInterval(250)
    _watcher.timeout.connect(_close_modal_dialog)
    _watcher.start()


def _close_modal_dialog():
    widget = QtWidgets.QApplication.activeModalWidget()
    if widget is None or not widget.isVisible():
        return
    if isinstance(widget, QtWidgets.QMessageBox):
        text = widget.text()
    else:
        text = " | ".join(label.text() for label in widget.findChildren(QtWidgets.QLabel) if label.text())
    entry = {"title": widget.windowTitle(), "text": text, "step": _current_step}
    if _session_dir:
        entry["screenshot"] = _save(widget, f"dialog_{len(_dialogs) + 1}")
    _dialogs.append(entry)
    if isinstance(widget, QtWidgets.QDialog):
        widget.reject()
    else:
        widget.close()


def _save(widget, name):
    folder = os.path.join(_session_dir, "screenshots")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{name}.png")
    widget.grab().save(path)
    return path.replace("\\", "/")


# --- running scenarios -------------------------------------------------------

def _slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def process_events(times=10):
    for _ in range(times):
        QtWidgets.QApplication.processEvents()
        time.sleep(0.01)


class Scenario:
    """The ``ui`` object scenario scripts get. Each ``step`` becomes one
    PASS/FAIL line; a step fails if it raises, or if Maya printed a warning
    or error, or a dialog appeared while it ran."""

    def __init__(self):
        self.checks = []
        self.screenshots = []

    @contextlib.contextmanager
    def step(self, name):
        global _current_step
        _current_step = name
        before = len(_dialogs)
        detail = []
        try:
            yield
        except Exception:
            detail.append(traceback.format_exc().rstrip())
        finally:
            process_events()
            _current_step = None
        detail += [f"{kind}: {text}" for kind, text, step in _messages if step == name]
        detail += [f"dialog: {d['title']}: {d['text']}" for d in _dialogs[before:]]
        self.checks.append({"name": name, "ok": not detail, "detail": "\n".join(detail)})

    def check(self, name, ok, detail=""):
        self.checks.append({"name": name, "ok": bool(ok), "detail": "" if ok else detail})

    def tool(self, name):
        from kaiju_suite import registry

        tool = registry.find(name)
        if tool is None:
            raise LookupError(f"No tool named {name!r}")
        return tool

    def open_tool(self, name):
        """Launch the tool like its menu item does, and return its window."""
        from kaiju_suite.ui.base_window import ToolWindow

        tool = self.tool(name)
        tool["launch"]()
        process_events()
        package = tool["launch"].__module__
        for window in ToolWindow._instances.values():
            if type(window).__module__.startswith(package + ".") and window.isVisible():
                return window
        raise LookupError(f"{name} opened no visible window")

    def close_tool(self, window):
        control = f"{window.objectName()}WorkspaceControl"
        if cmds.workspaceControl(control, exists=True):
            cmds.deleteUI(control)
        process_events()

    def buttons(self, window):
        return [b for b in window.findChildren(QtWidgets.QAbstractButton) if b.isVisible()]

    @staticmethod
    def label(button):
        """What the user reads: the button's text (``&`` shortcuts dropped) or,
        for an icon-only button, its tooltip up to the first colon or line end."""
        text = button.text().replace("&", "").strip()
        if text:
            return text
        return button.toolTip().splitlines()[0].split(":")[0].strip() if button.toolTip() else ""

    def button(self, window, label):
        """The visible button labelled ``label`` (see ``label``)."""
        found = [b for b in self.buttons(window) if self.label(b) == label]
        if len(found) != 1:
            labels = sorted({self.label(b) for b in self.buttons(window)} - {""})
            raise LookupError(f"{len(found)} buttons labelled {label!r}; visible labels: {labels}")
        return found[0]

    def click(self, window, label):
        self.button(window, label).click()
        process_events()

    def screenshot(self, widget, name):
        process_events()
        path = _save(widget, _slug(name))
        self.screenshots.append(path)
        return path

    def screenshot_maya(self, name):
        from maya import OpenMayaUI
        from shiboken6 import wrapInstance

        main = wrapInstance(int(OpenMayaUI.MQtUtil.mainWindow()), QtWidgets.QWidget)
        return self.screenshot(main, name)


def run_file(script, result_path):
    """Run a scenario script and write its result to ``result_path``."""
    first_message = len(_messages)
    first_dialog = len(_dialogs)
    scenario = Scenario()
    errors = []
    try:
        with open(script, encoding="utf-8") as f:
            source = f.read()
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        exec(compile(source, script, "exec"), {"__name__": "__kaiju_scenario__", "__file__": script, "ui": scenario, "cmds": cmds})
    except Exception:
        errors.append(traceback.format_exc().rstrip())
    process_events()
    # Messages and dialogs from inside a step are already in that step's line.
    outside = [(kind, text) for kind, text, step in _messages[first_message:] if step is None]
    _write_json(result_path, {
        "checks": scenario.checks,
        "errors": errors + [text for kind, text in outside if kind == "error"],
        "warnings": [text for kind, text in outside if kind == "warning"],
        "dialogs": [d for d in _dialogs[first_dialog:] if d["step"] is None],
        "screenshots": scenario.screenshots,
    })
