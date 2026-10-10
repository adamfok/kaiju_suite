import json
import os

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import logic, products, versions
from kaiju_suite.tools.assembler.products import scene


def _maya_file(path, node):
    """Write a real Maya file holding one transform named ``node``."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cmds.select(cmds.createNode("transform", name=node))
    file_type = "mayaAscii" if str(path).endswith(".ma") else "mayaBinary"
    cmds.file(str(path), exportSelected=True, type=file_type, force=True)
    cmds.file(new=True, force=True)
    return str(path)


def _numbers(path):
    return [v.number for v in versions.list_versions(path)]


@pytest.fixture
def picked(monkeypatch):
    """Stand-in for the file browser: returns ``picked.answer``, records
    the folder it was opened in."""

    class Picker:
        answer = None
        opened_in = []

        def __call__(self, start_dir):
            self.opened_in.append(start_dir)
            return self.answer

    picker = Picker()
    picker.opened_in = []
    monkeypatch.setattr(scene, "pick_scene_file", picker)
    return picker


# -- the entry --------------------------------------------------------------


def test_scene_items_are_scene_pointer_files(tmp_path):
    assert scene.PRODUCT.extensions == (".scene",)
    assert products.product_for(str(_touch(tmp_path / "a.scene"))) is scene.PRODUCT
    # Maya files are what a Scene points to, not Assembler items themselves.
    for name in ("a.ma", "a.mb"):
        assert products.product_for(str(_touch(tmp_path / name))) is None


def test_type_column_shows_scene(tmp_path):
    _touch(tmp_path / "body.scene")
    (entry,) = logic.scan(str(tmp_path))
    assert entry.label == "body" and entry.type_label == "Scene"


def test_new_scene_is_an_empty_entry_needing_no_selection(new_scene, tmp_path):
    cmds.select(clear=True)
    path = scene.create_scene(str(tmp_path), "hero")
    assert path == str(tmp_path / "hero.scene")
    assert os.path.getsize(path) == 0
    assert scene.target(path) is None
    with pytest.raises(FileExistsError):
        scene.create_scene(str(tmp_path), "hero")


def test_scene_is_in_the_new_menu_after_script():
    labels = [None if e is None else e[1].label for e in products.new_menu()]
    assert labels[:3] == ["Script", "Scene", None]
    (creator,) = scene.PRODUCT.creators
    assert creator.choices is None and not creator.open_after


def test_creator_makes_an_entry(tmp_path):
    (creator,) = scene.PRODUCT.creators
    path = creator.fn(str(tmp_path), "hero", None)
    assert path == str(tmp_path / "hero.scene")


def test_scene_is_runnable_and_versioned():
    assert scene.PRODUCT.runnable and scene.PRODUCT.versioned and scene.PRODUCT.can_disable


def test_double_click_shows_info_instead_of_a_tool(tmp_path):
    # With no utility, double-click opens the panel and there's no right-click Info.
    path = scene.create_scene(str(tmp_path), "hero")
    assert scene.PRODUCT.utility is None
    assert scene.PRODUCT.panel(path) is not None


# -- pointing at a file -----------------------------------------------------


@pytest.mark.parametrize("ext", (".ma", ".mb"))
def test_point_to_saves_the_path_as_a_version(new_scene, tmp_path, ext):
    source = _maya_file(tmp_path / "files" / f"hero_v1{ext}", "hero")
    path = scene.create_scene(str(tmp_path), "hero")

    assert scene.point_to(path, source) == "Published Scene hero.scene v001"
    assert os.path.normcase(scene.target(path)) == os.path.normcase(os.path.abspath(source))
    assert _numbers(path) == [1]
    # Under the entry's folder, so it's stored relative to it.
    with open(path, encoding="utf-8") as f:
        assert json.load(f)["path"] == f"files/hero_v1{ext}"


def test_point_to_rejects_non_maya_files_and_changes_nothing(tmp_path):
    path = scene.create_scene(str(tmp_path), "hero")
    with pytest.raises(ValueError):
        scene.point_to(path, _touch(tmp_path / "notes.txt"))
    with pytest.raises(FileNotFoundError):
        scene.point_to(path, str(tmp_path / "missing.mb"))
    assert os.path.getsize(path) == 0
    assert versions.list_versions(path) == []


def test_each_publish_is_a_version_and_restore_points_back(new_scene, tmp_path):
    first = _maya_file(tmp_path / "files" / "a.ma", "first")
    second = _maya_file(tmp_path / "files" / "b.mb", "second")
    path = scene.create_scene(str(tmp_path), "hero")

    scene.point_to(path, first)
    assert scene.point_to(path, second) == "Published Scene hero.scene v002"
    assert _numbers(path) == [2, 1]
    assert scene.target(path).endswith("b.mb")

    versions.restore_version(path, 1)
    assert scene.target(path).endswith("a.ma")
    logic.run_steps([path])
    assert cmds.objExists("first") and not cmds.objExists("second")


# -- run ----------------------------------------------------------------------


def test_run_imports_the_file_it_points_to(new_scene, tmp_path):
    source = _maya_file(tmp_path / "files" / "hero.mb", "hero")
    path = scene.create_scene(str(tmp_path), "hero")
    scene.point_to(path, source)

    logic.run_steps([path])
    assert cmds.objExists("hero")


def test_empty_entry_is_skipped_by_a_build(new_scene, tmp_path):
    empty = scene.create_scene(str(tmp_path), "later")
    after = _touch(tmp_path / "b.py", "from maya import cmds\ncmds.createNode('transform', name='n_b')\n")
    assert logic.run_steps([empty, after]) == [empty, after]
    assert cmds.objExists("n_b")


def test_missing_file_stops_the_build_and_names_it(new_scene, tmp_path):
    source = _maya_file(tmp_path / "files" / "gone.ma", "gone")
    path = scene.create_scene(str(tmp_path), "hero")
    scene.point_to(path, source)
    os.remove(source)

    with pytest.raises(logic.StepError) as info:
        logic.run_steps([path])
    assert info.value.path == path
    assert "gone.ma" in str(info.value.__cause__ or info.value)


def test_run_steps_imports_scenes_between_scripts(new_scene, tmp_path):
    source = _maya_file(tmp_path / "files" / "hero.ma", "hero")
    hero = scene.create_scene(str(tmp_path), "hero")
    scene.point_to(hero, source)
    cmds.undoInfo(state=True)

    first = _touch(tmp_path / "a.py", "from maya import cmds\nassert not cmds.objExists('hero')\n")
    last = _touch(tmp_path / "c.py", "from maya import cmds\ncmds.parent(cmds.createNode('transform', name='kid'), 'hero')\n")

    assert logic.run_steps([first, hero, last]) == [first, hero, last]
    assert cmds.objExists("hero|kid")

    # The import flushed undo, but undo still works for what comes next.
    cmds.createNode("transform", name="after")
    cmds.undo()
    assert not cmds.objExists("after") and cmds.objExists("hero")


def test_double_click_does_not_import(new_scene, tmp_path):
    source = _maya_file(tmp_path / "files" / "hero.ma", "hero")
    path = scene.create_scene(str(tmp_path), "hero")
    scene.point_to(path, source)

    assert scene.PRODUCT.open(path) is None
    assert scene.PRODUCT.actions(path) == []
    assert not cmds.objExists("hero")


# -- publish ------------------------------------------------------------------


def test_publish_needs_no_selection(new_scene, tmp_path):
    path = scene.create_scene(str(tmp_path), "hero")
    cmds.select(clear=True)
    assert versions.publish_problems(path) == []
    assert versions.publish_warnings(path) == []


def test_publish_points_to_the_picked_file(new_scene, tmp_path, picked):
    source = _maya_file(tmp_path / "files" / "hero.mb", "hero")
    path = scene.create_scene(str(tmp_path), "hero")
    picked.answer = source

    action = versions.publish_action(path)
    assert action.label == "Publish" and action.confirm is None
    assert action.fn() == "Published Scene hero.scene v001"
    assert scene.target(path).endswith("hero.mb")
    # With nothing published yet, the browser opens in the entry's folder.
    assert os.path.normcase(picked.opened_in[0]) == os.path.normcase(str(tmp_path))


def test_publish_browser_opens_in_the_current_files_folder(new_scene, tmp_path, picked):
    source = _maya_file(tmp_path / "files" / "hero.mb", "hero")
    path = scene.create_scene(str(tmp_path), "hero")
    scene.point_to(path, source)
    picked.answer = source

    versions.publish_action(path).fn()
    assert os.path.normcase(picked.opened_in[0]) == os.path.normcase(str(tmp_path / "files"))


def test_cancelling_the_browser_changes_nothing(tmp_path, picked):
    path = scene.create_scene(str(tmp_path), "hero")
    picked.answer = None
    assert versions.publish_action(path).fn() is None
    assert os.path.getsize(path) == 0
    assert versions.list_versions(path) == []


# -- portable paths -------------------------------------------------------------


def _stored(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["path"]


def _write(path, stored):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"path": stored}, f)


def test_build_root_is_the_entrys_folder(tmp_path):
    os.makedirs(tmp_path / "build")
    path = scene.create_scene(str(tmp_path / "build"), "hero")
    assert os.path.normcase(scene.build_root(path)) == os.path.normcase(str(tmp_path / "build"))


def test_a_file_outside_the_build_folder_is_stored_absolute(new_scene, tmp_path, monkeypatch):
    monkeypatch.delenv("ASSET", raising=False)
    source = _maya_file(tmp_path / "shared" / "hero.ma", "hero")
    os.makedirs(tmp_path / "build")
    path = scene.create_scene(str(tmp_path / "build"), "hero")
    scene.point_to(path, source)
    assert os.path.isabs(_stored(path))
    assert os.path.normcase(scene.target(path)) == os.path.normcase(os.path.abspath(source))


def test_a_file_under_asset_is_stored_with_the_variable(new_scene, tmp_path, monkeypatch):
    monkeypatch.setenv("ASSET", str(tmp_path / "assets"))
    source = _maya_file(tmp_path / "assets" / "model" / "hero.ma", "hero")
    os.makedirs(tmp_path / "build")
    path = scene.create_scene(str(tmp_path / "build"), "hero")
    scene.point_to(path, source)
    assert _stored(path) == "$ASSET/model/hero.ma"

    # Another machine: same variable name, different place.
    moved = tmp_path / "other_machine"
    os.makedirs(moved)
    os.replace(tmp_path / "assets", moved / "assets")
    monkeypatch.setenv("ASSET", str(moved / "assets"))
    logic.run_steps([path])
    assert cmds.objExists("hero")


def test_point_to_accepts_text_with_a_variable(new_scene, tmp_path, monkeypatch):
    monkeypatch.setenv("ASSET", str(tmp_path / "assets"))
    _maya_file(tmp_path / "assets" / "hero.mb", "hero")
    path = scene.create_scene(str(tmp_path), "hero")
    scene.point_to(path, "$ASSET/hero.mb")
    assert _stored(path) == "$ASSET/hero.mb"
    assert scene.target(path).endswith("hero.mb") and os.path.isfile(scene.target(path))


def test_old_absolute_entries_still_run(new_scene, tmp_path):
    source = _maya_file(tmp_path / "files" / "hero.ma", "hero")
    path = scene.create_scene(str(tmp_path), "hero")
    _write(path, os.path.abspath(source).replace("\\", "/"))
    assert os.path.normcase(scene.target(path)) == os.path.normcase(os.path.abspath(source))
    logic.run_steps([path])
    assert cmds.objExists("hero")


def test_moving_the_build_folder_still_runs(new_scene, tmp_path):
    old = tmp_path / "old_place" / "build"
    source = _maya_file(old / "files" / "hero.ma", "hero")
    path = scene.create_scene(str(old), "hero")
    scene.point_to(path, source)

    new = tmp_path / "new_place" / "build"
    os.makedirs(new.parent)
    os.replace(old, new)
    moved = str(new / "hero.scene")
    assert os.path.normcase(os.path.normpath(scene.target(moved))) == os.path.normcase(str(new / "files" / "hero.ma"))
    logic.run_steps([moved])
    assert cmds.objExists("hero")


def test_versions_keep_the_relative_path(new_scene, tmp_path):
    first = _maya_file(tmp_path / "files" / "a.ma", "first")
    second = _maya_file(tmp_path / "files" / "b.ma", "second")
    path = scene.create_scene(str(tmp_path), "hero")
    scene.point_to(path, first)
    scene.point_to(path, second)
    versions.restore_version(path, 1)
    assert _stored(path) == "files/a.ma"


def test_missing_relative_file_names_both_paths(new_scene, tmp_path):
    path = scene.create_scene(str(tmp_path), "hero")
    _write(path, "files/gone.ma")
    with pytest.raises(logic.StepError) as info:
        logic.run_steps([path])
    message = str(info.value.__cause__ or info.value)
    assert "files/gone.ma" in message and os.path.normcase(str(tmp_path)) in os.path.normcase(message).replace("/", os.sep)


def test_info_shows_the_stored_path_and_where_it_resolves(new_scene, tmp_path):
    source = _maya_file(tmp_path / "files" / "hero.ma", "hero")
    path = scene.create_scene(str(tmp_path), "hero")
    scene.point_to(path, source)
    info = " ".join(scene.PRODUCT.panel(path).info)
    assert "files/hero.ma" in info and scene.target(path) in info


def test_build_plan_keeps_the_stored_path(new_scene, tmp_path):
    source = _maya_file(tmp_path / "files" / "hero.ma", "hero")
    path = scene.create_scene(str(tmp_path), "hero")
    scene.point_to(path, source)
    assert scene.PRODUCT.to_plan(path) == {"path": "files/hero.ma"}


# -- info ---------------------------------------------------------------------


def test_info_shows_the_path(new_scene, tmp_path):
    path = scene.create_scene(str(tmp_path), "hero")
    assert "Not published yet" in " ".join(scene.PRODUCT.panel(path).info)

    source = _maya_file(tmp_path / "files" / "hero.ma", "hero")
    scene.point_to(path, source)
    info = " ".join(scene.PRODUCT.panel(path).info)
    assert scene.target(path) in info and "v001" in info

    os.remove(source)
    assert "not found" in " ".join(scene.PRODUCT.panel(path).info).lower()


def test_info_on_a_broken_entry_says_so(tmp_path):
    path = _touch(tmp_path / "hero.scene", "not json")
    assert "Not a scene entry" in " ".join(scene.PRODUCT.panel(path).info)


def _touch(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return str(path)
