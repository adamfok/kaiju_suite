"""Kaiju Scripter Copy and Paste: every item kind, folders, versions and names."""

import os

import pytest
from maya import cmds

from kaiju_suite.tools.scripter import items, logic, versions


def _write(path, text=""):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return str(path)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _names(folder):
    return [e.name for e in logic.scan(str(folder))]


@pytest.fixture
def folders(tmp_path):
    src = logic.create_item(logic.FOLDER, str(tmp_path), "src")
    dst = logic.create_item(logic.FOLDER, str(tmp_path), "dst")
    return src, dst


@pytest.mark.parametrize(
    "kind", [logic.SCRIPT, logic.SEPARATOR, logic.BREAKPOINT, logic.SELECTION, logic.FOLDER]
)
def test_paste_copies_each_simple_kind_into_another_folder(folders, kind):
    src, dst = folders
    path = logic.create_item(kind, src, "thing")
    if kind == logic.SCRIPT:
        _write(path, "print('hi')\n")
    elif kind == logic.SELECTION:
        items.write_entries(path, [{"type": items.PATTERN, "value": "*_geo"}])

    [pasted] = logic.paste([path], dst)

    assert os.path.basename(pasted) == os.path.basename(path)
    assert os.path.dirname(pasted) == dst
    assert logic.kind_of(pasted) == kind
    assert os.path.exists(path)  # the original stays
    if kind != logic.FOLDER:
        assert _read(pasted) == _read(path)


def test_pasting_where_the_name_is_taken_adds_copy(tmp_path):
    a = logic.create_item(logic.SCRIPT, str(tmp_path), "a")
    arms = logic.create_item(logic.FOLDER, str(tmp_path), "arms")

    first = logic.paste([a, arms], str(tmp_path))
    second = logic.paste([a], str(tmp_path))

    assert [os.path.basename(p) for p in first] == ["a_copy.py", "arms_copy"]
    assert [os.path.basename(p) for p in second] == ["a_copy_2.py"]


def test_paste_goes_at_the_index_in_the_given_order(tmp_path):
    a, b, c = (logic.create_item(logic.SCRIPT, str(tmp_path), n) for n in "abc")
    logic.paste([c, a], str(tmp_path), 1)
    assert _names(tmp_path) == ["a.py", "c_copy.py", "a_copy.py", "b.py", "c.py"]


def test_paste_keeps_disabled(folders):
    src, dst = folders
    path = logic.create_item(logic.SCRIPT, src, "off")
    logic.set_enabled([path], False)
    [pasted] = logic.paste([path], dst)
    assert not logic.is_enabled(pasted)


def test_paste_keeps_a_scripts_versions(folders):
    src, dst = folders
    path = logic.create_item(logic.SCRIPT, src, "setup")
    _write(path, "one = 1\n")
    versions.publish(path, "First")
    _write(path, "two = 2\n")

    [pasted] = logic.paste([path], dst)

    assert versions.label(pasted) == "v001*"
    assert [v.description for v in versions.list_versions(pasted)] == ["First"]
    # The copy's history is its own.
    versions.publish(pasted)
    assert versions.count(path) == 1


def test_paste_copies_a_folder_with_its_order_disabled_items_and_versions(folders):
    src, dst = folders
    b = logic.create_item(logic.SCRIPT, src, "b")
    logic.create_item(logic.SCRIPT, src, "a")
    logic.set_enabled([b], False)
    versions.publish(b)

    [pasted] = logic.paste([src], dst)

    assert _names(pasted) == ["b.py", "a.py"]
    assert not logic.is_enabled(os.path.join(pasted, "b.py"))
    assert versions.label(os.path.join(pasted, "b.py")) == "v001"


def test_paste_skips_items_inside_a_pasted_folder(folders):
    src, dst = folders
    inside = logic.create_item(logic.SCRIPT, src, "inside")
    pasted = logic.paste([src, inside], dst)
    assert [os.path.basename(p) for p in pasted] == ["src"]
    assert _names(dst) == ["src"]


def test_paste_refuses_a_folder_into_itself(folders):
    src, _dst = folders
    with pytest.raises(ValueError):
        logic.paste([src], src)
    assert _names(src) == []


def test_paste_of_a_missing_item_pastes_nothing(folders):
    src, dst = folders
    path = logic.create_item(logic.SCRIPT, src, "a")
    gone = os.path.join(src, "gone.py")
    with pytest.raises(FileNotFoundError):
        logic.paste([path, gone], dst)
    assert _names(dst) == []


# -- data and file items ----------------------------------------------------


def test_paste_copies_a_joints_item_with_its_versions(folders, new_scene):
    src, dst = folders
    cmds.select(clear=True)
    hip = cmds.joint(name="hip")
    cmds.joint(name="knee", position=(0, 2, 0))
    path = logic.create_data_item(items.JOINTS, src, "skeleton", cmds.ls(hip, long=True))

    [pasted] = logic.paste([path], dst)

    assert versions.label(pasted) == "v001"
    assert items.describe(pasted) == items.describe(path)


@pytest.mark.parametrize("kind", [logic.IMPORT_FILE, logic.EXPORT_FILE])
def test_pasted_file_item_points_to_the_same_file(folders, kind):
    src, dst = folders
    # Inside the item's folder, so it's stored relative to it.
    target = os.path.join(src, "files", "hero.ma")
    path = logic.create_file_item(kind, src, "hero", target)

    [pasted] = logic.paste([path], dst)

    assert items.target(pasted) == os.path.normpath(target)


def test_file_item_in_a_pasted_folder_points_into_the_copy(folders):
    src, dst = folders
    os.makedirs(os.path.join(src, "files"))
    _write(os.path.join(src, "files", "hero.ma"))
    logic.create_file_item(logic.IMPORT_FILE, src, "hero", os.path.join(src, "files", "hero.ma"))

    [pasted] = logic.paste([src], dst)

    assert items.target(os.path.join(pasted, "hero.import")) == os.path.join(pasted, "files", "hero.ma")


def test_pasting_a_file_item_with_no_file_set_copies_it_as_it_is(folders):
    src, dst = folders
    path = logic.create_item(logic.IMPORT_FILE, src, "empty")
    [pasted] = logic.paste([path], dst)
    assert _read(pasted) == ""


def test_paste_copies_a_build_from_one_library_to_another(tmp_path):
    # Two scripts folders, as picked in Scripter's folder box.
    lib_a = str(tmp_path / "lib_a")
    lib_b = str(tmp_path / "lib_b")
    os.makedirs(lib_a)
    os.makedirs(lib_b)
    logic.create_item(logic.SCRIPT, lib_b, "existing")
    build = logic.create_item(logic.FOLDER, lib_a, "hero_build")
    setup = logic.create_item(logic.SCRIPT, build, "setup")
    versions.publish(setup)
    logic.create_item(logic.BREAKPOINT, build, "check")
    arms = logic.create_item(logic.FOLDER, build, "arms")
    logic.set_enabled([arms], False)
    os.makedirs(os.path.join(build, "files"))
    _write(os.path.join(build, "files", "hero.ma"))
    logic.create_file_item(logic.IMPORT_FILE, build, "hero", os.path.join(build, "files", "hero.ma"))
    outside = _write(tmp_path / "shared.ma")
    logic.create_file_item(logic.IMPORT_FILE, build, "shared", outside)

    [pasted] = logic.paste([build], lib_b)

    assert pasted == os.path.join(lib_b, "hero_build")
    assert _names(lib_b) == ["existing.py", "hero_build"]
    assert _names(pasted) == ["setup.py", "check.brk", "arms", "files", "hero.import", "shared.import"]
    assert versions.label(os.path.join(pasted, "setup.py")) == "v001"
    assert not logic.is_enabled(os.path.join(pasted, "arms"))
    assert items.target(os.path.join(pasted, "hero.import")) == os.path.join(pasted, "files", "hero.ma")
    assert items.target(os.path.join(pasted, "shared.import")) == os.path.normpath(outside)
    assert _names(build) == _names(pasted)  # library A is untouched
