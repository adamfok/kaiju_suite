import os

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import logic, products
from kaiju_suite.tools.assembler.products import new_scene as new_scene_product


def test_new_new_scene_is_an_empty_file(tmp_path):
    path = new_scene_product.create_new_scene(str(tmp_path), "Start")
    assert path == str(tmp_path / "Start.newscene")
    assert os.path.getsize(path) == 0
    assert products.product_for(path) is new_scene_product.PRODUCT
    with pytest.raises(FileExistsError):
        new_scene_product.create_new_scene(str(tmp_path), "Start")


def test_new_menu_has_new_scene_named_new_without_asking():
    (creator,) = new_scene_product.PRODUCT.creators
    assert creator.label == "New Scene"
    assert creator.fixed_name == "new"
    assert creator.choices is None
    assert not creator.open_after


def test_creating_a_new_scene_from_the_menu_names_it_new(tmp_path):
    (creator,) = new_scene_product.PRODUCT.creators
    path = logic.create_item(creator, str(tmp_path), creator.fixed_name, None)
    assert path == str(tmp_path / "new.newscene")
    (entry,) = logic.scan(str(tmp_path))
    assert entry.label == "new"


def test_other_creators_ask_for_a_name():
    fixed = [c.label for p in products.all_products() for c in p.creators if c.fixed_name]
    assert fixed == ["New Scene"]


def test_new_scene_is_run_but_not_versioned():
    product = new_scene_product.PRODUCT
    assert product.runnable
    assert product.can_disable
    assert not product.versioned


def test_new_scene_shows_no_version_and_its_type(tmp_path):
    new_scene_product.create_new_scene(str(tmp_path), "Start")
    (entry,) = logic.scan(str(tmp_path))
    assert entry.label == "Start"
    assert entry.version_label is None
    assert entry.type_label == "New Scene"


def test_running_a_new_scene_empties_the_scene_without_asking(new_scene, tmp_path):
    cmds.polyCube(name="leftover")
    # Unsaved changes: a plain "new scene" would ask to save them.
    assert cmds.file(query=True, modified=True)

    path = new_scene_product.create_new_scene(str(tmp_path), "Start")
    logic.run_steps([path])

    assert not cmds.objExists("leftover")


def test_build_runs_new_scene_in_order(new_scene, tmp_path):
    root = str(tmp_path)
    before = os.path.join(root, "before.py")
    with open(before, "w") as f:
        f.write("from maya import cmds\ncmds.polyCube(name='before')\n")
    start = new_scene_product.create_new_scene(root, "Start")
    after = os.path.join(root, "after.py")
    with open(after, "w") as f:
        f.write("from maya import cmds\ncmds.polyCube(name='after')\n")

    logic.run_steps([before, start, after])

    assert not cmds.objExists("before")
    assert cmds.objExists("after")

