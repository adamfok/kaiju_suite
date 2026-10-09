import os
import sys

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import logic, products, versions
from kaiju_suite.tools.assembler.products import folder, scene, script


def _touch(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return str(path)


def _make_script(path, node):
    return _touch(path, f"from maya import cmds\ncmds.createNode('transform', name='{node}')\n")


class _JsonProduct(products.Product):
    """A made-up product, standing in for one added later."""

    name = "Preset"
    extensions = (".json",)
    order = 500  # after every real product
    runnable = True

    def __init__(self):
        self.ran = []

    def run(self, path):
        self.ran.append(path)


@pytest.fixture
def with_json(monkeypatch):
    json_product = _JsonProduct()
    monkeypatch.setattr(products, "_cache", sorted(products.discover() + [json_product], key=lambda p: p.order))
    return json_product


# -- discovery --------------------------------------------------------------


def test_discover_finds_every_product_in_order():
    found = products.discover()
    assert [p.name for p in found] == [
        "Script", "Folder", "Scene", "Joints", "Mesh", "SkinCluster",
        "DeltaMush", "BlendShapes", "Material", "Pose", "Animation", "ControlShape",
    ]
    exts = [ext for p in found for ext in p.extensions]
    assert len(exts) == len(set(exts)), "two products claim the same extension"


def test_discover_finds_builtin_products_in_order():
    found = products.discover()
    names = [p.name for p in found]
    assert {"Script", "Folder", "Scene"} <= set(names)
    assert names[:3] == ["Script", "Folder", "Scene"]
    assert found == sorted(found, key=lambda p: p.order)
    assert found[1] is folder.PRODUCT


def test_product_for_maps_paths(tmp_path):
    (tmp_path / "dir").mkdir()
    assert products.product_for(str(tmp_path / "dir")) is folder.PRODUCT
    for name in ("a.py", "a.MEL"):
        assert products.product_for(_touch(tmp_path / name)) is script.PRODUCT
    for name in ("a.ma", "a.mb"):
        assert products.product_for(_touch(tmp_path / name)) is scene.PRODUCT
    assert products.product_for(_touch(tmp_path / "a.txt")) is None


def test_only_scripts_and_scenes_are_runnable():
    assert script.PRODUCT.runnable and scene.PRODUCT.runnable
    assert not folder.PRODUCT.runnable


def test_products_have_no_colors():
    # The tree shows the type in its own column instead of color-coding names.
    for product in (script.PRODUCT, scene.PRODUCT, folder.PRODUCT):
        assert not hasattr(product, "color")
        assert not hasattr(product, "color_for")


def test_extensions_lists_every_file_extension():
    found = products.extensions()
    assert found[:4] == [".py", ".mel", ".ma", ".mb"]
    assert len(found) == len(set(found))


def test_conflicting_extension_goes_to_lower_order(monkeypatch, tmp_path):
    class Rival(products.Product):
        name = "Rival"
        extensions = (".py",)
        order = 5

    rival = Rival()
    monkeypatch.setattr(products, "_cache", sorted(products.discover() + [rival], key=lambda p: p.order))
    assert products.product_for(_touch(tmp_path / "a.py")) is rival


def test_broken_product_module_is_skipped(monkeypatch, tmp_path):
    _touch(tmp_path / "broken_product.py", "raise ImportError('nope')\n")
    monkeypatch.setattr(products, "__path__", list(products.__path__) + [str(tmp_path)])
    try:
        names = [p.name for p in products.discover()]
        assert names[:3] == ["Script", "Folder", "Scene"]
        assert f"{products.__name__}.broken_product" not in sys.modules
    finally:
        sys.modules.pop(f"{products.__name__}.broken_product", None)


def test_open_does_nothing_by_default():
    assert products.Product().open("x") is None


def test_double_click_opens_scripts_without_a_menu_entry(monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(script, "open_in_script_editor", opened.append)
    path = _touch(tmp_path / "a.py")

    script.PRODUCT.open(path)

    assert opened == [path]
    assert script.PRODUCT.actions(path) == []


def test_double_click_does_not_import_scenes(new_scene, tmp_path):
    cmds.select(cmds.createNode("transform", name="hero"))
    path = scene.export_selection(str(tmp_path / "hero.ma"))
    cmds.file(new=True, force=True)

    assert scene.PRODUCT.open(path) is None
    assert not cmds.objExists("hero")


# -- a new product only needs its own module -------------------------------


def test_new_product_is_listed_collected_and_run(with_json, new_scene, tmp_path):
    root = str(tmp_path)
    a = _make_script(tmp_path / "a.py", "n_a")
    preset = _touch(tmp_path / "b.json", "{}")
    _touch(tmp_path / "notes.txt")

    entries = logic.scan(root)
    assert [e.name for e in entries] == ["a.py", "b.json"]
    assert entries[1].product is with_json

    assert logic.collect_steps(root) == [a, preset]
    logic.run_steps([preset, a])
    assert with_json.ran == [preset] and cmds.objExists("n_a")


# -- creation helpers -------------------------------------------------------


def test_new_path_validates_names(tmp_path):
    assert products.new_path(str(tmp_path), " hello ", ".py") == str(tmp_path / "hello.py")
    assert products.new_path(str(tmp_path), "x.PY", ".py") == str(tmp_path / "x.PY")
    assert products.new_path(str(tmp_path), "dir", None) == str(tmp_path / "dir")
    _touch(tmp_path / "hello.py")
    with pytest.raises(FileExistsError):
        products.new_path(str(tmp_path), "hello", ".py")
    with pytest.raises(ValueError):
        products.new_path(str(tmp_path), "  ", ".py")
    with pytest.raises(ValueError):
        products.new_path(str(tmp_path), "a\\b", None)


def test_new_menu_lists_script_folder_scene():
    labels = [c.label for p in products.discover() for c in p.creators]
    assert labels[:3] == ["Script", "Folder", "Scene"]
    assert folder.PRODUCT.creators[0].choices is None


def test_script_creator_opens_the_new_file():
    assert script.PRODUCT.creators[0].open_after
    assert not scene.PRODUCT.creators[0].open_after


@pytest.mark.parametrize("ext", scene.EXTENSIONS)
def test_new_scene_is_an_empty_entry_needing_no_selection(new_scene, tmp_path, ext):
    cmds.select(clear=True)
    path = scene.create_scene(str(tmp_path), "hero", ext)
    assert path == str(tmp_path / f"hero{ext}")
    assert os.path.getsize(path) == 0
    with pytest.raises(FileExistsError):
        scene.create_scene(str(tmp_path), "hero", ext)
    with pytest.raises(ValueError):
        scene.create_scene(str(tmp_path), "x", ".py")


def test_empty_scene_is_skipped_by_a_build(new_scene, tmp_path):
    empty = scene.create_scene(str(tmp_path), "later", ".mb")
    after = _make_script(tmp_path / "b.py", "n_b")
    assert logic.run_steps([empty, after]) == [empty, after]
    assert cmds.objExists("n_b")


def test_no_panel_by_default():
    assert products.Product().panel("x") is None
    assert script.PRODUCT.panel("x.py") is None


def test_scenes_have_no_right_click_actions(new_scene, tmp_path):
    path = scene.create_scene(str(tmp_path), "hero", ".ma")
    assert scene.PRODUCT.actions(path) == []


def _export_action(path):
    action = versions.publish_action(path)
    assert action.label == "Publish"
    return action


def test_scene_double_click_opens_an_empty_window(new_scene, tmp_path):
    path = scene.create_scene(str(tmp_path), "hero", ".ma")
    panel = scene.PRODUCT.panel(path)
    assert panel is not None  # a window, not open()
    assert panel.info == [] and panel.actions == []

    cmds.select(cmds.createNode("transform"))
    _export_action(path).fn()
    panel = scene.PRODUCT.panel(path)
    assert panel.info == [] and panel.actions == []


@pytest.mark.parametrize("ext", scene.EXTENSIONS)
def test_publish_fills_a_scene_entry(new_scene, tmp_path, ext):
    path = scene.create_scene(str(tmp_path), "hero", ext)
    action = _export_action(path)

    cmds.select(cmds.createNode("transform", name="hero"))
    assert "hero" in action.fn()
    assert os.path.getsize(path) > 0

    cmds.file(new=True, force=True)
    logic.run_steps([path])
    assert cmds.objExists("hero")


def test_publish_replaces_a_full_scene_without_asking(new_scene, tmp_path):
    cmds.select(cmds.createNode("transform"))
    path = scene.export_selection(str(tmp_path / "full.ma"))
    action = _export_action(path)
    assert action.confirm is None  # the old content is kept as a version


def test_publish_needs_a_selection(new_scene, tmp_path):
    path = scene.create_scene(str(tmp_path), "hero", ".ma")
    cmds.select(clear=True)
    with pytest.raises(RuntimeError):
        _export_action(path).fn()
    assert os.path.getsize(path) == 0


def test_collect_steps_includes_scenes_in_order_skipping_disabled(tmp_path):
    root = str(tmp_path)
    a = _touch(tmp_path / "a.py")
    m = _touch(tmp_path / "m.ma")
    off = _touch(tmp_path / "off.mb")
    inner = _touch(tmp_path / "sub" / "s.mel")
    logic.place([m], root, 0)
    logic.set_enabled(off, False)

    assert logic.collect_steps(root) == [m, inner, a]


def test_run_steps_imports_scenes_between_scripts(new_scene, tmp_path):
    cmds.select(cmds.createNode("transform", name="hero"))
    hero = scene.export_selection(str(tmp_path / "hero.ma"))
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True)

    first = _touch(tmp_path / "a.py", "from maya import cmds\nassert not cmds.objExists('hero')\n")
    last = _touch(tmp_path / "c.py", "from maya import cmds\ncmds.parent(cmds.createNode('transform', name='kid'), 'hero')\n")

    assert logic.run_steps([first, hero, last]) == [first, hero, last]
    assert cmds.objExists("hero|kid")

    # The import flushed undo, but undo still works for what comes next.
    cmds.createNode("transform", name="after")
    cmds.undo()
    assert not cmds.objExists("after") and cmds.objExists("hero")


def test_step_error_names_the_failing_scene(new_scene, tmp_path):
    good = _make_script(tmp_path / "a.py", "n_a")
    bad = _touch(tmp_path / "broken.ma", "not a maya file")
    never = _make_script(tmp_path / "c.py", "n_c")
    with pytest.raises(logic.StepError) as info:
        logic.run_steps([good, bad, never])
    assert info.value.path == bad
    assert cmds.objExists("n_a") and not cmds.objExists("n_c")


def test_run_steps_rejects_unknown_files(tmp_path):
    with pytest.raises(logic.StepError):
        logic.run_steps([_touch(tmp_path / "a.txt")])
