import os

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import logic


def _touch(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return str(path)


def _names(entries):
    return [e.name for e in entries]


# -- scan / filter ----------------------------------------------------------


def test_scan_sorts_and_filters(tmp_path):
    _touch(tmp_path / "b.py")
    _touch(tmp_path / "A.mel")
    _touch(tmp_path / "notes.txt")
    _touch(tmp_path / "rigs" / "arm.ma")
    _touch(tmp_path / "rigs" / "leg.mb")
    (tmp_path / "empty").mkdir()
    _touch(tmp_path / ".git" / "x.py")
    _touch(tmp_path / "__pycache__" / "b.py")

    entries = logic.scan(str(tmp_path))

    assert _names(entries) == ["empty", "rigs", "A.mel", "b.py"]
    rigs = entries[1]
    assert rigs.is_dir and _names(rigs.children) == ["arm.ma", "leg.mb"]
    assert entries[0].children == []


def test_scan_missing_folder_returns_empty(tmp_path):
    assert logic.scan(str(tmp_path / "nope")) == []


def test_matches_is_case_insensitive():
    assert logic.matches("Skin_Tools.py", "skin")
    assert logic.matches("anything", "")
    assert not logic.matches("rig.ma", "skin")


# -- create / delete --------------------------------------------------------


def test_create_script_adds_extension(tmp_path):
    path = logic.create_script(str(tmp_path), "hello", ".py")
    assert path == str(tmp_path / "hello.py") and os.path.isfile(path)
    assert logic.create_script(str(tmp_path), "x.mel", ".mel").endswith("x.mel")


def test_create_script_refuses_overwrite_and_bad_names(tmp_path):
    logic.create_script(str(tmp_path), "hello", ".py")
    with pytest.raises(FileExistsError):
        logic.create_script(str(tmp_path), "hello", ".py")
    with pytest.raises(ValueError):
        logic.create_script(str(tmp_path), "  ", ".py")
    with pytest.raises(ValueError):
        logic.create_script(str(tmp_path), "sub/hello", ".py")
    with pytest.raises(ValueError):
        logic.create_script(str(tmp_path), "hello", ".ma")


def test_create_and_delete_folder(tmp_path):
    folder = logic.create_folder(str(tmp_path), "stuff")
    _touch(os.path.join(folder, "a.py"))
    with pytest.raises(FileExistsError):
        logic.create_folder(str(tmp_path), "stuff")
    logic.delete_path(folder)
    assert not os.path.exists(folder)


def test_delete_file(tmp_path):
    path = _touch(tmp_path / "a.py")
    logic.delete_path(path)
    assert not os.path.exists(path)
    with pytest.raises(FileNotFoundError):
        logic.delete_path(path)


# -- move -------------------------------------------------------------------


def test_move_into_folder(tmp_path):
    src = _touch(tmp_path / "a.py")
    (tmp_path / "sub").mkdir()
    new = logic.move_path(src, str(tmp_path / "sub"))
    assert new == str(tmp_path / "sub" / "a.py") and os.path.isfile(new)


def test_move_onto_file_uses_its_folder(tmp_path):
    src = _touch(tmp_path / "a.py")
    other = _touch(tmp_path / "sub" / "b.py")
    assert logic.move_path(src, other) == str(tmp_path / "sub" / "a.py")


def test_move_folder_into_itself_raises(tmp_path):
    (tmp_path / "f" / "inner").mkdir(parents=True)
    with pytest.raises(ValueError):
        logic.move_path(str(tmp_path / "f"), str(tmp_path / "f"))
    with pytest.raises(ValueError):
        logic.move_path(str(tmp_path / "f"), str(tmp_path / "f" / "inner"))


def test_move_sibling_with_shared_prefix_is_allowed(tmp_path):
    (tmp_path / "f").mkdir()
    (tmp_path / "f2").mkdir()
    assert logic.move_path(str(tmp_path / "f"), str(tmp_path / "f2")) == str(tmp_path / "f2" / "f")


def test_move_name_clash_raises(tmp_path):
    src = _touch(tmp_path / "a.py")
    _touch(tmp_path / "sub" / "a.py")
    with pytest.raises(FileExistsError):
        logic.move_path(src, str(tmp_path / "sub"))
    assert os.path.isfile(src)


def test_move_to_same_folder_is_noop(tmp_path):
    src = _touch(tmp_path / "a.py")
    assert logic.move_path(src, str(tmp_path)) == os.path.normpath(src)


# -- run --------------------------------------------------------------------


def test_run_python_script_is_one_undo_step(new_scene, tmp_path):
    cmds.undoInfo(state=True)
    path = _touch(
        tmp_path / "make.py",
        "from maya import cmds\ncmds.createNode('transform', name='py_a')\n"
        "cmds.createNode('transform', name='py_b')\n",
    )
    logic.run_script(path)
    assert cmds.objExists("py_a") and cmds.objExists("py_b")
    cmds.undo()
    assert not cmds.objExists("py_a") and not cmds.objExists("py_b")


def test_run_mel_script(new_scene, tmp_path):
    path = _touch(tmp_path / "make.mel", 'createNode transform -name "mel_a";\n')
    logic.run_script(path)
    assert cmds.objExists("mel_a")


def test_run_rejects_scene(tmp_path):
    with pytest.raises(ValueError):
        logic.run_script(_touch(tmp_path / "a.ma"))


# -- scenes -----------------------------------------------------------------


@pytest.mark.parametrize("ext", logic.SCENE_EXTS)
def test_export_import_round_trip(new_scene, tmp_path, ext):
    cmds.select(cmds.createNode("transform", name="hero"))
    path = logic.create_scene(str(tmp_path), "hero", ext)
    assert path.endswith(ext) and os.path.isfile(path)

    cmds.file(new=True, force=True)
    logic.import_scene(path)
    assert cmds.objExists("hero")


def test_export_requires_selection(new_scene, tmp_path):
    cmds.select(clear=True)
    with pytest.raises(RuntimeError):
        logic.export_selection(str(tmp_path / "a.ma"))


def test_export_overwrite_guard(new_scene, tmp_path):
    cmds.select(cmds.createNode("transform"))
    path = logic.export_selection(str(tmp_path / "a.mb"))
    with pytest.raises(FileExistsError):
        logic.export_selection(path)
    assert logic.export_selection(path, overwrite=True) == path


def test_import_flushes_undo_but_leaves_it_usable(new_scene, tmp_path):
    # Maya can't undo a file import (it flushes the queue); make sure our
    # undo chunk doesn't leave undo broken for whatever comes next.
    cmds.select([cmds.createNode("transform", name=n) for n in ("one", "two")])
    path = logic.export_selection(str(tmp_path / "pair.ma"))
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True)

    logic.import_scene(path)
    assert cmds.objExists("one") and cmds.objExists("two")

    cmds.createNode("transform", name="after")
    cmds.undo()
    assert not cmds.objExists("after")
    assert cmds.objExists("one")


def test_registry_finds_assembler():
    from kaiju_suite import registry

    assert "Assembler" in [tool["name"] for tool in registry.discover()]
