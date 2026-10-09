import json
import os

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import data, logic, products, versions


class _Locators(data.DataProduct):
    """A made-up data product: saves the selected transforms' names."""

    name = "Locators"
    kind = "locators"
    extension = ".loc"
    order = 900

    def gather(self, selection):
        names = [n.rsplit("|", 1)[-1] for n in cmds.ls(selection, type="transform")]
        if not names:
            raise RuntimeError("No transforms selected.")
        return {"names": names}

    def apply(self, payload):
        for name in payload["names"]:
            data.create_node("transform", name)
        return f"Created {len(payload['names'])}"

    def selection_problems(self):
        return [] if cmds.ls(selection=True, type="transform") else ["Select transforms."]

    def describe(self, payload):
        return [f"{len(payload['names'])} locators"]


@pytest.fixture
def locators(monkeypatch):
    product = _Locators()
    monkeypatch.setattr(products, "_cache", sorted(products.discover() + [product], key=lambda p: p.order))
    return product


def _raw(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return str(path)


# -- read / write -----------------------------------------------------------


def test_write_then_read_round_trips_with_a_header(tmp_path):
    path = str(tmp_path / "a.loc")
    data.write(path, "locators", {"names": ["a", "b"]})
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["kaiju"] == "locators" and raw["format"] == data.FORMAT == 1
    assert data.read(path, "locators") == {"names": ["a", "b"]}


def test_write_is_deterministic(tmp_path):
    a, b = str(tmp_path / "a.loc"), str(tmp_path / "b.loc")
    data.write(a, "locators", {"x": 1, "y": [1.5, 2]})
    data.write(b, "locators", {"x": 1, "y": [1.5, 2]})
    with open(a, "rb") as fa, open(b, "rb") as fb:
        assert fa.read() == fb.read()


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[1, 2]",
        json.dumps({"kaiju": "joints", "format": 1, "data": {}}),
        json.dumps({"kaiju": "locators", "format": 99, "data": {}}),
        json.dumps({"kaiju": "locators", "data": {}}),
        json.dumps({"kaiju": "locators", "format": 1}),
    ],
)
def test_read_rejects_bad_files(tmp_path, content):
    path = tmp_path / "a.loc"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(data.DataFormatError) as info:
        data.read(str(path), "locators")
    assert "a.loc" in str(info.value)


def test_data_format_error_is_a_value_error():
    assert issubclass(data.DataFormatError, ValueError)


# -- node helpers -----------------------------------------------------------


def test_unique_name_numbers_like_maya(new_scene):
    assert data.unique_name("spine_jnt") == "spine_jnt"
    cmds.createNode("transform", name="spine_jnt")
    assert data.unique_name("spine_jnt") == "spine_jnt1"
    cmds.createNode("transform", name="spine_jnt1")
    assert data.unique_name("spine_jnt") == "spine_jnt2"
    cmds.createNode("transform", name="joint1")
    assert data.unique_name("joint1") == "joint2"


def test_unique_name_sees_names_under_other_parents(new_scene):
    grp = cmds.createNode("transform", name="grp")
    cmds.createNode("transform", name="arm", parent=grp)
    assert data.unique_name("arm") == "arm1"


def test_create_node_returns_a_uuid_and_picks_a_free_name(new_scene):
    cmds.createNode("transform", name="hero")
    grp = cmds.createNode("transform", name="grp")
    cmds.select(clear=True)
    uuid = data.create_node("joint", "hero", parent=grp)
    path = data.node_path(uuid)
    assert path == "|grp|hero1"
    assert cmds.nodeType(path) == "joint"
    assert cmds.ls(selection=True) == []


def test_require_nodes_lists_every_missing_one(new_scene):
    cmds.createNode("transform", name="there")
    data.require_nodes(["there"])  # no error
    with pytest.raises(data.MissingNodesError) as info:
        data.require_nodes(["a", "there", "b", "a"], "influences")
    assert str(info.value) == "Missing influences: a, b"
    assert info.value.missing == ["a", "b"]
    assert isinstance(info.value, RuntimeError)


# -- DataProduct ------------------------------------------------------------


def test_data_product_is_runnable_versioned_and_named(locators):
    assert locators.runnable and locators.versioned and locators.can_disable
    assert locators.extensions == (".loc",)
    (creator,) = locators.creators
    assert creator.label == "Locators" and creator.choices is None and not creator.open_after


def test_creator_makes_an_empty_file(locators, tmp_path):
    path = locators.creators[0].fn(str(tmp_path), "rig", None)
    assert path == str(tmp_path / "rig.loc")
    assert os.path.getsize(path) == 0
    assert products.product_for(path) is locators
    with pytest.raises(FileExistsError):
        locators.creators[0].fn(str(tmp_path), "rig", None)


def test_empty_file_is_skipped_by_a_build(locators, new_scene, tmp_path):
    path = locators.create(str(tmp_path), "rig")
    assert logic.run_steps([path]) == [path]
    assert locators.run(path) is None


def test_run_applies_the_file_as_one_undo_step(locators, new_scene, tmp_path):
    path = str(tmp_path / "rig.loc")
    data.write(path, "locators", {"names": ["a", "b"]})
    cmds.undoInfo(state=True)
    cmds.flushUndo()
    assert locators.run(path) == "Created 2"
    assert cmds.objExists("a") and cmds.objExists("b")
    cmds.undo()
    assert not cmds.objExists("a") and not cmds.objExists("b")


def test_run_rejects_a_file_of_another_kind(locators, new_scene, tmp_path):
    path = str(tmp_path / "rig.loc")
    data.write(path, "joints", {"joints": []})
    with pytest.raises(data.DataFormatError):
        locators.run(path)


def test_publish_writes_the_selection_as_a_new_version(locators, new_scene, tmp_path):
    path = locators.create(str(tmp_path), "rig")
    cmds.select(cmds.createNode("transform", name="hero"))

    action = versions.publish_action(path)
    assert action.label == "Publish" and action.confirm is None
    assert action.fn() == "Published Locators rig.loc v001"
    assert data.read(path, "locators") == {"names": ["hero"]}

    assert action.fn() == "Published Locators rig.loc v001"  # unchanged: no new version
    cmds.select(cmds.createNode("transform", name="other"))
    assert action.fn() == "Published Locators rig.loc v002"


def test_failed_publish_changes_nothing(locators, new_scene, tmp_path):
    path = locators.create(str(tmp_path), "rig")
    cmds.select(clear=True)
    with pytest.raises(RuntimeError):
        versions.publish_action(path).fn()
    assert os.path.getsize(path) == 0
    assert versions.list_versions(path) == []


def test_publish_problems_come_from_the_selection(locators, new_scene, tmp_path):
    path = locators.create(str(tmp_path), "rig")
    cmds.select(clear=True)
    assert versions.publish_problems(path) == ["Select transforms."]
    cmds.select(cmds.createNode("transform"))
    assert versions.publish_problems(path) == []


def test_panel_describes_the_file(locators, new_scene, tmp_path):
    path = locators.create(str(tmp_path), "rig")
    panel = locators.panel(path)
    assert len(panel.info) == 1 and "empty" in panel.info[0].lower()
    assert panel.actions == []

    data.write(path, "locators", {"names": ["a", "b"]})
    assert locators.panel(path).info == ["2 locators"]

    _raw(path, {"kaiju": "other", "format": 1, "data": {}})
    (line,) = locators.panel(path).info
    assert line.startswith("Can't read rig.loc")
