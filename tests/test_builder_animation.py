"""Kaiju Builder's Animation item (``.anim``): keys published from the
selection through kaiju_suite.datatypes.animation, versioned, applied back
when run; double-click opens the Animation Tool; Publish runs its QC first."""

import json
import os
import subprocess
import sys

import pytest
from maya import cmds

from kaiju_suite.tools.builder import items, logic, versions

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")


def _box(name="box"):
    node = cmds.createNode("transform", name=name, skipSelect=True)
    cmds.setKeyframe(f"{node}.translateX", time=1, value=0)
    cmds.setKeyframe(f"{node}.translateX", time=10, value=5)
    return node


def _long(*nodes):
    return cmds.ls(nodes, long=True)


def test_animation_is_a_data_kind_with_the_anim_extension():
    assert items.ANIMATION == "Animation"
    assert items.EXTENSIONS[items.ANIMATION] == ".anim"
    assert items.kind_of("walk.anim") == items.ANIMATION
    assert items.ANIMATION in items.DATATYPES and items.ANIMATION in items.RUNNABLE
    assert ".anim" in versions.VERSIONED_EXTENSIONS


def test_new_animation_item_publishes_the_selection_as_v001(tmp_path, new_scene):
    box = _box()

    path = logic.create_data_item(items.ANIMATION, str(tmp_path), "walk", _long(box))

    assert path == os.path.join(str(tmp_path), "walk.anim")
    assert versions.label(path) == "v001"
    assert items.describe(path) == ["1 animated attribute on 1 node, 2 keys", "Frames 1 to 10"]
    [entry] = logic.scan(str(tmp_path))
    assert (entry.kind, entry.type_label) == (items.ANIMATION, "Animation")


def test_new_animation_item_needs_keys(tmp_path, new_scene):
    still = cmds.createNode("transform", name="still")
    with pytest.raises(ValueError, match="keys"):
        logic.create_data_item(items.ANIMATION, str(tmp_path), "walk", _long(still))
    assert logic.scan(str(tmp_path)) == []


def test_running_an_animation_item_puts_the_keys_back_as_one_undo_step(tmp_path, new_scene):
    box = _box()
    path = logic.create_data_item(items.ANIMATION, str(tmp_path), "walk", _long(box))
    cmds.cutKey(box, clear=True)
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    assert logic.Runner().run([path]) == logic.DONE
    assert cmds.keyframe("box.translateX", query=True, timeChange=True) == [1, 10]

    cmds.undo()
    assert not cmds.keyframe("box.translateX", query=True, timeChange=True)


def test_publish_adds_a_version_only_when_the_keys_changed(tmp_path, new_scene):
    box = _box()
    path = logic.create_data_item(items.ANIMATION, str(tmp_path), "walk", _long(box))

    with pytest.raises(ValueError, match="No changes"):
        items.publish_data(path, _long(box), "Same")
    cmds.setKeyframe("box.translateX", time=20, value=1)
    assert items.publish_data(path, _long(box), "Longer") == 2


def test_animation_items_open_the_animation_tool():
    from kaiju_suite import registry

    assert items.tool_for(items.ANIMATION) == "Animation Tool"
    assert registry.find(items.tool_for(items.ANIMATION)) is not None


def test_open_in_tool_selects_the_animated_nodes(tmp_path, new_scene, monkeypatch):
    from kaiju_suite import registry

    path = logic.create_data_item(items.ANIMATION, str(tmp_path), "walk", _long(_box("a"), _box("b")))
    cmds.select(clear=True)
    calls = []
    monkeypatch.setattr(
        registry, "find", lambda name: {"name": name, "launch": lambda: calls.append((name, cmds.ls(selection=True)))}
    )

    assert items.open_in_tool(path) == "Selected 2 objects from walk.anim"
    assert calls == [("Animation Tool", ["a", "b"])]


def test_publish_qc_runs_the_animation_checks(tmp_path, new_scene):
    box = _box()
    still = cmds.createNode("transform", name="still")
    path = logic.create_data_item(items.ANIMATION, str(tmp_path), "walk", _long(box))

    found = dict((check.key, problems) for check, problems in items.publish_qc(path, _long(box, still)))

    assert list(found) == ["not_animated", "unsaved", "duplicate_names"]
    assert found["not_animated"] == ["still: no keys"]


# -- the window ---------------------------------------------------------------

_PROBE = r"""
import json, os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, sys.argv[1])
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from kaiju_suite.tools.builder import items, widget

path = os.path.join(tempfile.mkdtemp(), "walk.anim")
open(path, "w").close()
calls = []
widget.items.open_in_tool = lambda p: calls.append(("tool", os.path.basename(p))) or "Selected 1 object"
widget.items.describe = lambda p: calls.append(("describe", os.path.basename(p))) or ["info"]
widget.QtWidgets.QMessageBox.information = staticmethod(lambda *a: calls.append(("box", a[1])))


class Stand(QtWidgets.QWidget):
    attempt = staticmethod(lambda fn: fn())
    _on_double_click = widget.BuilderWindow._on_double_click
    _show_info = widget.BuilderWindow._show_info


stand = Stand()
item = QtWidgets.QTreeWidgetItem([os.path.basename(path)])
item.setData(0, widget.PATH_ROLE, path)
stand._on_double_click(item, 0)
icon = widget.kind_icon(items.ANIMATION)
print(json.dumps({
    "double_click": calls,
    "in_new_menu": items.ANIMATION in widget.NEW_KINDS,
    "icon_file": widget.ICONS.get(items.ANIMATION),
    "icon_null": icon.isNull(),
}))
"""


@pytest.fixture(scope="module")
def probe():
    done = subprocess.run([sys.executable, "-c", _PROBE, SCRIPTS], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads([line for line in done.stdout.splitlines() if line.startswith("{")][-1])


def test_double_click_on_an_animation_item_opens_the_animation_tool(probe):
    assert probe["double_click"] == [["tool", "walk.anim"]]


def test_the_new_menu_offers_animation_with_its_icon(probe):
    assert probe["in_new_menu"]
    assert probe["icon_file"] == "builder_animation.svg"
    assert not probe["icon_null"]
