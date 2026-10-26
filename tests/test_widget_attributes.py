"""Widgets must not store children under the names of Qt methods.

``self.size = QDoubleSpinBox()`` hides ``QWidget.size()``, and Maya's dock
code calls ``self.size()`` when it shows the window, so the tool fails to
open. Windows can't be shown in maya.standalone, so this scans the source.
"""

import ast
import os

from PySide6 import QtWidgets

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "kaiju_suite")

_QT_NAMES = set(dir(QtWidgets.QMainWindow)) | set(dir(QtWidgets.QDialog))


def _widget_sources():
    for folder, _dirs, files in os.walk(SCRIPTS):
        for name in files:
            if name.endswith(".py") and (name.startswith("widget") or name.endswith("_widget.py") or "ui" in folder.split(os.sep)):
                yield os.path.join(folder, name)


def _shadowed(path):
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for sub in ast.walk(node):
            targets = sub.targets if isinstance(sub, ast.Assign) else [sub.target] if isinstance(sub, ast.AnnAssign) else []
            for target in targets:
                if (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                    and target.attr in _QT_NAMES
                    and target.attr != "layout"  # ToolWindow.layout is the window's own layout, by design.
                ):
                    found.append(f"{os.path.relpath(path, SCRIPTS)}:{sub.lineno} {node.name}.{target.attr}")
    return found


def test_scan_finds_widget_files():
    paths = [os.path.relpath(p, SCRIPTS) for p in _widget_sources()]
    assert os.path.join("tools", "controlshape_tool", "widget.py") in paths


def test_no_widget_attribute_hides_a_qt_method():
    found = [hit for path in _widget_sources() for hit in _shadowed(path)]
    assert not found, "Attributes that hide Qt methods:\n" + "\n".join(found)
