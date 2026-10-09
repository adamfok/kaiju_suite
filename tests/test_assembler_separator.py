import os

import pytest

from kaiju_suite.tools.assembler import logic, products
from kaiju_suite.tools.assembler.products import separator


def test_new_separator_is_an_empty_file(tmp_path):
    path = separator.create_separator(str(tmp_path), "Skinning")
    assert path == str(tmp_path / "Skinning.sep")
    assert os.path.getsize(path) == 0
    assert products.product_for(path) is separator.PRODUCT
    with pytest.raises(FileExistsError):
        separator.create_separator(str(tmp_path), "Skinning")


def test_new_menu_has_separator_asking_for_a_name_only():
    creator = separator.PRODUCT.creators[0]
    assert creator.label == "Separator"
    assert creator.choices is None
    assert not creator.open_after


def test_separator_is_not_versioned_run_or_disabled():
    product = separator.PRODUCT
    assert not product.versioned
    assert not product.runnable
    assert not product.can_disable


def test_separator_shows_equals_in_version_and_type_columns(tmp_path):
    separator.create_separator(str(tmp_path), "Skinning")
    with open(tmp_path / "rig.py", "w"):
        pass
    by_name = {e.name: e for e in logic.scan(str(tmp_path))}
    sep = by_name["Skinning.sep"]
    assert sep.label == "Skinning"
    assert sep.version_label == "====="
    assert sep.type_label == "====="
    # Other items keep their own type and leave Version to the version history.
    assert by_name["rig.py"].version_label is None
    assert by_name["rig.py"].type_label == "Script(.py)"


def test_build_skips_separators(new_scene, tmp_path):
    sep = separator.create_separator(str(tmp_path), "Skinning")
    assert sep not in logic.collect_steps(str(tmp_path))
    assert logic.run_folder(str(tmp_path)) == []
