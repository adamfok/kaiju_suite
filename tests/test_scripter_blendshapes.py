"""Kaiju Scripter BlendShapes items (.bshp): blendShapes published from the
selected meshes through datatypes.blendshape, versioned, applied back when
run; double-click opens the BlendShape Tool, Publish runs its QC first."""

import json
import os
import subprocess
import sys

import pytest
from maya import cmds

from kaiju_suite.tools.scripter import items, logic, versions

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")


def _rig(name="face"):
    base = cmds.polyPlane(name=name, subdivisionsX=4, subdivisionsY=4, constructionHistory=False)[0]
    smile = cmds.duplicate(base, name="smile")[0]
    cmds.move(0, 1, 0, f"{smile}.vtx[0]", relative=True, objectSpace=True)
    node = cmds.blendShape(smile, base, name=f"{name}BS")[0]
    cmds.delete(smile)
    cmds.setAttr(f"{node}.smile", 0.5)
    return base, node


def _long(nodes):
    return cmds.ls(nodes, long=True)


def test_blendshapes_is_an_item_kind():
    assert items.BLENDSHAPES == logic.BLENDSHAPES == "BlendShapes"
    assert items.EXTENSIONS[items.BLENDSHAPES] == ".bshp"
    assert items.BLENDSHAPES in items.RUNNABLE
    assert items.kind_of("face.bshp") == items.BLENDSHAPES


def test_new_blendshapes_item_publishes_the_selection_as_v001(tmp_path, new_scene):
    base, _ = _rig()

    path = logic.create_data_item(items.BLENDSHAPES, str(tmp_path), "face", _long(base))

    assert path == os.path.join(str(tmp_path), "face.bshp")
    assert versions.is_versioned(path)
    assert versions.label(path) == "v001"
    assert items.describe(path) == ["1 blendShape, 1 target", "Meshes: face"]
    [entry] = logic.scan(str(tmp_path))
    assert (entry.kind, entry.type_label) == (items.BLENDSHAPES, "BlendShapes")


def test_new_blendshapes_item_needs_meshes_with_a_blendshape(tmp_path, new_scene):
    plain = cmds.polyCube(name="box", constructionHistory=False)[0]

    with pytest.raises(ValueError, match="No blendShape on: box"):
        logic.create_data_item(items.BLENDSHAPES, str(tmp_path), "face", _long(plain))
    assert logic.scan(str(tmp_path)) == []


def test_running_a_blendshapes_item_rebuilds_them_as_one_undo_step(tmp_path, new_scene):
    base, node = _rig()
    path = logic.create_data_item(items.BLENDSHAPES, str(tmp_path), "face", _long(base))
    cmds.delete(node)
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    assert logic.Runner().run([path]) == logic.DONE
    assert cmds.getAttr("faceBS.smile") == 0.5

    cmds.undo()
    assert not cmds.ls(type="blendShape")


def test_publish_adds_a_version_from_the_same_meshes(tmp_path, new_scene):
    base, node = _rig()
    path = logic.create_data_item(items.BLENDSHAPES, str(tmp_path), "face", _long(base))
    cmds.setAttr(f"{node}.smile", 0.8)

    found, problems = items.saved_objects(path)
    assert (found, problems) == (_long(base), [])
    assert items.publish_data(path, found, "stronger smile") == 2


def test_blendshapes_items_open_the_blendshape_tool():
    from kaiju_suite import registry

    assert items.tool_for(items.BLENDSHAPES) == "BlendShape Tool"
    assert registry.find(items.tool_for(items.BLENDSHAPES)) is not None


def test_open_in_tool_selects_the_base_meshes(tmp_path, new_scene, monkeypatch):
    from kaiju_suite import registry

    base, _ = _rig()
    path = logic.create_data_item(items.BLENDSHAPES, str(tmp_path), "face", _long(base))
    cmds.select(clear=True)
    calls = []
    monkeypatch.setattr(
        registry, "find", lambda name: {"name": name, "launch": lambda: calls.append((name, cmds.ls(selection=True)))}
    )

    assert items.open_in_tool(path) == "Selected 1 object from face.bshp"
    assert calls == [("BlendShape Tool", ["face"])]


def test_publish_qc_runs_the_blendshape_checks(tmp_path, new_scene):
    base, _ = _rig()
    path = logic.create_data_item(items.BLENDSHAPES, str(tmp_path), "face", _long(base))
    plain = cmds.polyCube(name="box", constructionHistory=False)[0]

    found = dict((check.key, problems) for check, problems in items.publish_qc(path, _long([base, plain])))

    assert list(found) == ["blendshape", "order", "empty_targets", "duplicate_names"]
    assert found["blendshape"] == ["box: no blendShape"]


# Double-click on a BlendShapes item opens its tool; right-click Info...
# shows what's in it (the widget, off-screen in its own mayapy process).
_PROBE = r"""
import json, os, sys, tempfile
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, sys.argv[1])
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
from kaiju_suite.tools.scripter import widget

path = os.path.join(tempfile.mkdtemp(), "face.bshp")
open(path, "w").close()
calls = []
widget.items.open_in_tool = lambda p: calls.append(("tool", os.path.basename(p))) or "Selected 1 object"
widget.items.describe = lambda p: calls.append(("describe", os.path.basename(p))) or ["info"]
widget.QtWidgets.QMessageBox.information = staticmethod(lambda *a: calls.append(("box", a[1])))
widget.settings.get = lambda tool, key, default=None: default
widget.settings.set = lambda *a: None
widget.versions.is_versioned = lambda p: False


class Stand(QtWidgets.QWidget):
    root = os.path.dirname(path)
    runner = None
    copied = []
    attempt = staticmethod(lambda fn: fn())
    selected_paths = staticmethod(lambda: [])
    _delete_selected = staticmethod(lambda: None)
    _on_double_click = widget.ScripterWindow._on_double_click
    _on_context_menu = widget.ScripterWindow._on_context_menu
    _show_info = widget.ScripterWindow._show_info


stand = Stand()
stand.status = QtWidgets.QLabel()
stand.tree = widget._Tree(stand)
item = QtWidgets.QTreeWidgetItem(stand.tree, ["face.bshp"])
item.setData(0, widget.PATH_ROLE, path)
stand._on_double_click(item, 0)
out = {"double_click": list(calls)}
menus = []


class RecordingMenu(QtWidgets.QMenu):
    def exec(self, *_):
        menus.append(self.actions())


real_menu = QtWidgets.QMenu
QtWidgets.QMenu = RecordingMenu
stand.tree.itemAt = lambda pos: item
stand._on_context_menu(stand.tree.rect().center())
QtWidgets.QMenu = real_menu
out["menu"] = [a.text() for a in menus[0]]
new_menu = [a.menu() for a in menus[0] if a.menu() and a.text() == "New"]
out["new"] = [a.text() for a in new_menu[0].actions()] if new_menu else []
calls.clear()
[info] = [a for a in menus[0] if a.text() == "Info..."]
info.trigger()
out["info"] = list(calls)
out["icon"] = widget.ICONS.get("BlendShapes")
out["icon_null"] = widget.kind_icon("BlendShapes").isNull()
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def probe():
    done = subprocess.run([sys.executable, "-c", _PROBE, SCRIPTS], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads([line for line in done.stdout.splitlines() if line.startswith("{")][-1])


def test_double_click_opens_the_blendshape_tool(probe):
    assert probe["double_click"] == [["tool", "face.bshp"]]


def test_right_click_info_shows_what_is_in_it(probe):
    assert probe["info"] == [["describe", "face.bshp"], ["box", "face.bshp"]]


def test_the_new_menu_offers_blendshapes_with_its_icon(probe):
    assert "BlendShapes" in probe["new"]
    assert probe["icon"] == "scripter_blendshapes.svg"
    assert not probe["icon_null"]
