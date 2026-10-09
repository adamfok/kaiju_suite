import os

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import logic
from kaiju_suite.tools.assembler.products import folder, scene, script


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
    path = script.create_script(str(tmp_path), "hello", ".py")
    assert path == str(tmp_path / "hello.py") and os.path.isfile(path)
    assert script.create_script(str(tmp_path), "x.mel", ".mel").endswith("x.mel")


def test_create_script_refuses_overwrite_and_bad_names(tmp_path):
    script.create_script(str(tmp_path), "hello", ".py")
    with pytest.raises(FileExistsError):
        script.create_script(str(tmp_path), "hello", ".py")
    with pytest.raises(ValueError):
        script.create_script(str(tmp_path), "  ", ".py")
    with pytest.raises(ValueError):
        script.create_script(str(tmp_path), "sub/hello", ".py")
    with pytest.raises(ValueError):
        script.create_script(str(tmp_path), "hello", ".ma")


def test_create_and_delete_folder(tmp_path):
    path = folder.create_folder(str(tmp_path), "stuff")
    _touch(os.path.join(path, "a.py"))
    with pytest.raises(FileExistsError):
        folder.create_folder(str(tmp_path), "stuff")
    logic.delete_path(path)
    assert not os.path.exists(path)


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
    script.run_script(path)
    assert cmds.objExists("py_a") and cmds.objExists("py_b")
    cmds.undo()
    assert not cmds.objExists("py_a") and not cmds.objExists("py_b")


def test_run_mel_script(new_scene, tmp_path):
    path = _touch(tmp_path / "make.mel", 'createNode transform -name "mel_a";\n')
    script.run_script(path)
    assert cmds.objExists("mel_a")


def test_run_rejects_scene(tmp_path):
    with pytest.raises(ValueError):
        script.run_script(_touch(tmp_path / "a.ma"))


# -- scenes -----------------------------------------------------------------


@pytest.mark.parametrize("ext", scene.EXTENSIONS)
def test_export_import_round_trip(new_scene, tmp_path, ext):
    cmds.select(cmds.createNode("transform", name="hero"))
    path = scene.export_selection(str(tmp_path / f"hero{ext}"))
    assert os.path.isfile(path)

    cmds.file(new=True, force=True)
    scene.import_scene(path)
    assert cmds.objExists("hero")


def test_export_requires_selection(new_scene, tmp_path):
    cmds.select(clear=True)
    with pytest.raises(RuntimeError):
        scene.export_selection(str(tmp_path / "a.ma"))


def test_export_overwrite_guard(new_scene, tmp_path):
    cmds.select(cmds.createNode("transform"))
    path = scene.export_selection(str(tmp_path / "a.mb"))
    with pytest.raises(FileExistsError):
        scene.export_selection(path)
    assert scene.export_selection(path, overwrite=True) == path


def test_import_flushes_undo_but_leaves_it_usable(new_scene, tmp_path):
    # Maya can't undo a file import (it flushes the queue); make sure our
    # undo chunk doesn't leave undo broken for whatever comes next.
    cmds.select([cmds.createNode("transform", name=n) for n in ("one", "two")])
    path = scene.export_selection(str(tmp_path / "pair.ma"))
    cmds.file(new=True, force=True)
    cmds.undoInfo(state=True)

    scene.import_scene(path)
    assert cmds.objExists("one") and cmds.objExists("two")

    cmds.createNode("transform", name="after")
    cmds.undo()
    assert not cmds.objExists("after")
    assert cmds.objExists("one")


def test_registry_finds_assembler():
    from kaiju_suite import registry

    assert "Assembler" in [tool["name"] for tool in registry.discover()]


# -- order ------------------------------------------------------------------


def _order_fixture(tmp_path):
    for name in ("a.py", "b.py", "c.py"):
        _touch(tmp_path / name)
    (tmp_path / "sub").mkdir()
    return str(tmp_path)


def test_place_reorders_within_folder_and_persists(tmp_path):
    root = _order_fixture(tmp_path)
    assert _names(logic.scan(root)) == ["sub", "a.py", "b.py", "c.py"]

    logic.place([os.path.join(root, "c.py")], root, 0)

    assert _names(logic.scan(root)) == ["c.py", "sub", "a.py", "b.py"]
    # The order lives in a hidden file in the folder, which scan doesn't list.
    assert os.path.isfile(os.path.join(root, logic.META_FILE))


def test_place_index_counts_positions_before_the_move(tmp_path):
    root = _order_fixture(tmp_path)
    # Dropping a.py "below b.py" means index 3 in the current order.
    logic.place([os.path.join(root, "a.py")], root, 3)
    assert _names(logic.scan(root)) == ["sub", "b.py", "a.py", "c.py"]


def test_place_several_keeps_their_given_order(tmp_path):
    root = _order_fixture(tmp_path)
    logic.place([os.path.join(root, "c.py"), os.path.join(root, "a.py")], root, 1)
    assert _names(logic.scan(root)) == ["sub", "c.py", "a.py", "b.py"]


def test_place_at_end_when_index_is_none(tmp_path):
    root = _order_fixture(tmp_path)
    logic.place([os.path.join(root, "sub")], root, None)
    assert _names(logic.scan(root)) == ["a.py", "b.py", "c.py", "sub"]


def test_place_moves_into_another_folder_at_index(tmp_path):
    root = _order_fixture(tmp_path)
    _touch(tmp_path / "sub" / "x.py")
    _touch(tmp_path / "sub" / "y.py")

    new = logic.place([os.path.join(root, "b.py")], os.path.join(root, "sub"), 1)

    assert new == [os.path.join(root, "sub", "b.py")]
    assert os.path.isfile(new[0])
    entries = logic.scan(root)
    assert _names(entries) == ["sub", "a.py", "c.py"]
    assert _names(entries[0].children) == ["x.py", "b.py", "y.py"]


def test_place_validates_everything_before_moving(tmp_path):
    root = _order_fixture(tmp_path)
    _touch(tmp_path / "sub" / "b.py")
    with pytest.raises(FileExistsError):
        logic.place([os.path.join(root, "a.py"), os.path.join(root, "b.py")], os.path.join(root, "sub"), None)
    # a.py came first in the list but must not have been moved.
    assert os.path.isfile(os.path.join(root, "a.py"))
    with pytest.raises(ValueError):
        logic.place([os.path.join(root, "sub")], os.path.join(root, "sub"), None)


def test_place_skips_items_inside_a_moved_folder(tmp_path):
    root = _order_fixture(tmp_path)
    inner = _touch(tmp_path / "sub" / "x.py")
    (tmp_path / "dest").mkdir()
    new = logic.place([os.path.join(root, "sub"), inner], os.path.join(root, "dest"), None)
    assert new == [os.path.join(root, "dest", "sub")]
    assert os.path.isfile(os.path.join(root, "dest", "sub", "x.py"))


def test_new_files_appear_after_ordered_ones(tmp_path):
    root = _order_fixture(tmp_path)
    logic.place([os.path.join(root, "c.py")], root, 0)
    _touch(tmp_path / "0_new.py")
    (tmp_path / "0_dir").mkdir()
    # Unlisted entries keep the default order (folders, then files) at the end.
    assert _names(logic.scan(root)) == ["c.py", "sub", "a.py", "b.py", "0_dir", "0_new.py"]


def test_corrupt_meta_file_falls_back_to_default(tmp_path):
    root = _order_fixture(tmp_path)
    _touch(tmp_path / logic.META_FILE, "{not json")
    assert _names(logic.scan(root)) == ["sub", "a.py", "b.py", "c.py"]


# -- enable / disable -------------------------------------------------------


def test_disable_script_persists(tmp_path):
    path = _touch(tmp_path / "a.py")
    assert logic.is_enabled(path)
    logic.set_enabled(path, False)
    assert not logic.is_enabled(path)
    assert not logic.scan(str(tmp_path))[0].enabled
    logic.set_enabled(path, True)
    assert logic.is_enabled(path)
    assert logic.scan(str(tmp_path))[0].enabled


def test_disabled_state_follows_a_move(tmp_path):
    path = _touch(tmp_path / "a.py")
    (tmp_path / "sub").mkdir()
    logic.set_enabled(path, False)
    new = logic.place([path], str(tmp_path / "sub"), None)[0]
    assert not logic.is_enabled(new)
    # A new file reusing the old name starts enabled.
    assert logic.is_enabled(_touch(tmp_path / "a.py"))


def test_delete_forgets_disabled_state(tmp_path):
    path = _touch(tmp_path / "a.py")
    logic.set_enabled(path, False)
    logic.delete_path(path)
    assert logic.is_enabled(_touch(tmp_path / "a.py"))


# -- batch run --------------------------------------------------------------


def _make_script(path, node):
    return _touch(path, f"from maya import cmds\ncmds.createNode('transform', name='{node}')\n")


def test_collect_steps_in_display_order_skipping_disabled(tmp_path):
    root = str(tmp_path)
    a = _make_script(tmp_path / "a.py", "a")
    b = _make_script(tmp_path / "b.py", "b")
    m = _touch(tmp_path / "scene.ma")
    s1 = _touch(tmp_path / "sub" / "s1.mel")
    s2 = _make_script(tmp_path / "sub" / "s2.py", "s2")
    logic.place([b], root, 0)
    logic.set_enabled(s2, False)

    assert logic.collect_steps(root) == [b, s1, a, m]


def test_run_steps_is_one_undo_step(new_scene, tmp_path):
    cmds.undoInfo(state=True)
    paths = [_make_script(tmp_path / "a.py", "n_a"), _make_script(tmp_path / "b.py", "n_b")]
    assert logic.run_steps(paths) == paths
    assert cmds.objExists("n_a") and cmds.objExists("n_b")
    cmds.undo()
    assert not cmds.objExists("n_a") and not cmds.objExists("n_b")


def test_run_steps_runs_disabled_ones_when_asked(new_scene, tmp_path):
    path = _make_script(tmp_path / "a.py", "n_a")
    logic.set_enabled(path, False)
    logic.run_steps([path])
    assert cmds.objExists("n_a")


def test_run_steps_stops_at_first_failure(new_scene, tmp_path):
    good = _make_script(tmp_path / "a.py", "n_a")
    bad = _touch(tmp_path / "b.py", "raise RuntimeError('boom')\n")
    never = _make_script(tmp_path / "c.py", "n_c")
    with pytest.raises(logic.StepError) as info:
        logic.run_steps([good, bad, never])
    assert info.value.path == bad
    assert "boom" in str(info.value)
    assert cmds.objExists("n_a") and not cmds.objExists("n_c")


def test_run_steps_reports_each_step_status(new_scene, tmp_path):
    cmds.undoInfo(state=True)
    paths = [_make_script(tmp_path / "a.py", "n_a"), _make_script(tmp_path / "b.py", "n_b")]
    seen = []

    def on_status(path, status):
        # "running" is reported before the step's work happens.
        node = "n_a" if path == paths[0] else "n_b"
        seen.append((path, status, cmds.objExists(node)))

    logic.run_steps(paths, on_status=on_status)

    assert seen == [
        (paths[0], logic.RUNNING, False),
        (paths[0], logic.SUCCESS, True),
        (paths[1], logic.RUNNING, False),
        (paths[1], logic.SUCCESS, True),
    ]
    cmds.undo()
    assert not cmds.objExists("n_a") and not cmds.objExists("n_b")


def test_run_steps_reports_error_and_skips_the_rest(new_scene, tmp_path):
    good = _make_script(tmp_path / "a.py", "n_a")
    bad = _touch(tmp_path / "b.py", "raise RuntimeError('boom')\n")
    never = _make_script(tmp_path / "c.py", "n_c")
    seen = []
    with pytest.raises(logic.StepError):
        logic.run_steps([good, bad, never], on_status=lambda p, s: seen.append((p, s)))
    assert seen == [
        (good, logic.RUNNING),
        (good, logic.SUCCESS),
        (bad, logic.RUNNING),
        (bad, logic.ERROR),
    ]


def test_run_folder_skips_disabled(new_scene, tmp_path):
    cmds.undoInfo(state=True)
    _make_script(tmp_path / "a.py", "n_a")
    off = _make_script(tmp_path / "b.py", "n_b")
    _make_script(tmp_path / "sub" / "c.py", "n_c")
    logic.set_enabled(off, False)

    ran = logic.run_folder(str(tmp_path))

    assert len(ran) == 2
    assert cmds.objExists("n_a") and cmds.objExists("n_c") and not cmds.objExists("n_b")
    cmds.undo()
    assert not cmds.objExists("n_a") and not cmds.objExists("n_c")


# -- nested folders ---------------------------------------------------------


def test_nested_folders_scan_create_and_collect(tmp_path):
    root = str(tmp_path)
    outer = folder.create_folder(root, "outer")
    inner = folder.create_folder(outer, "inner")
    deep = folder.create_folder(inner, "deep")
    a = _touch(os.path.join(outer, "a.py"))
    b = _touch(os.path.join(deep, "b.py"))

    entries = logic.scan(root)
    assert _names(entries) == ["outer"]
    assert _names(entries[0].children) == ["inner", "a.py"]
    assert _names(entries[0].children[0].children[0].children) == ["b.py"]
    assert logic.collect_steps(root) == [b, a]


def test_move_folder_into_another_folder_keeps_contents(tmp_path):
    root = str(tmp_path)
    inner = _touch(tmp_path / "inner" / "x.py")
    (tmp_path / "outer").mkdir()
    new = logic.place([os.path.dirname(inner)], os.path.join(root, "outer"), None)[0]
    assert new == os.path.join(root, "outer", "inner")
    assert os.path.isfile(os.path.join(new, "x.py"))


# -- enable / disable folders -----------------------------------------------


def test_disable_folder_persists(tmp_path):
    sub = str(tmp_path / "sub")
    os.makedirs(sub)
    assert logic.scan(str(tmp_path))[0].enabled
    logic.set_enabled(sub, False)
    assert not logic.is_enabled(sub)
    assert not logic.scan(str(tmp_path))[0].enabled
    logic.set_enabled(sub, True)
    assert logic.scan(str(tmp_path))[0].enabled


def test_folder_product_can_be_disabled():
    assert folder.PRODUCT.can_disable
    assert script.PRODUCT.can_disable and scene.PRODUCT.can_disable


def test_double_click_folder_opens_it_in_file_browser(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(folder, "_launch", opened.append)
    path = folder.create_folder(str(tmp_path), "stuff")
    assert folder.PRODUCT.panel(path) is None  # so double-click calls open()
    folder.PRODUCT.open(path)
    assert opened == [os.path.normpath(path)]


def test_open_in_file_browser_rejects_missing_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(folder, "_launch", lambda p: pytest.fail("launched"))
    with pytest.raises(FileNotFoundError):
        folder.open_in_file_browser(str(tmp_path / "gone"))


def test_collect_steps_skips_everything_in_a_disabled_folder(tmp_path):
    root = str(tmp_path)
    a = _touch(tmp_path / "a.py")
    _touch(tmp_path / "off" / "b.py")
    _touch(tmp_path / "off" / "deeper" / "c.py")
    d = _touch(tmp_path / "on" / "d.py")
    _touch(tmp_path / "on" / "off2" / "e.py")
    logic.set_enabled(os.path.join(root, "off"), False)
    logic.set_enabled(os.path.join(root, "on", "off2"), False)

    assert logic.collect_steps(root) == [d, a]


def test_run_all_on_a_disabled_folder_itself_still_runs_it(tmp_path):
    # Like running a disabled script directly: asking for it explicitly runs it.
    off = str(tmp_path / "off")
    b = _touch(tmp_path / "off" / "b.py")
    _touch(tmp_path / "off" / "inner" / "c.py")
    logic.set_enabled(off, False)
    logic.set_enabled(str(tmp_path / "off" / "inner"), False)
    assert logic.collect_steps(off) == [b]


def test_disabled_folder_state_follows_a_move(tmp_path):
    root = str(tmp_path)
    off = str(tmp_path / "off")
    _touch(tmp_path / "off" / "b.py")
    (tmp_path / "dest").mkdir()
    logic.set_enabled(off, False)
    new = logic.place([off], os.path.join(root, "dest"), None)[0]
    assert not logic.is_enabled(new)
    assert logic.collect_steps(root) == []


def test_run_folder_skips_disabled_subfolder_as_one_undo_step(new_scene, tmp_path):
    cmds.undoInfo(state=True)
    _make_script(tmp_path / "a.py", "n_a")
    _make_script(tmp_path / "off" / "b.py", "n_b")
    logic.set_enabled(str(tmp_path / "off"), False)

    assert len(logic.run_folder(str(tmp_path))) == 1
    assert cmds.objExists("n_a") and not cmds.objExists("n_b")
    cmds.undo()
    assert not cmds.objExists("n_a")


# -- rename / display -------------------------------------------------------


def test_entry_label_hides_extension_and_type_label_names_product(tmp_path):
    _touch(tmp_path / "rig.py")
    _touch(tmp_path / "Build.MEL")
    _touch(tmp_path / "body.mb")
    (tmp_path / "parts.v2").mkdir()
    by_name = {e.name: e for e in logic.scan(str(tmp_path))}
    assert by_name["rig.py"].label == "rig"
    assert by_name["body.mb"].label == "body"
    # Folders keep their full name, dots included, and show no type.
    assert by_name["parts.v2"].label == "parts.v2"
    assert by_name["rig.py"].type_label == "Script(.py)"
    assert by_name["Build.MEL"].type_label == "Script(.mel)"
    assert by_name["body.mb"].type_label == "Scene(.mb)"
    assert by_name["parts.v2"].type_label == ""


def test_rename_keeps_extension(tmp_path):
    path = _touch(tmp_path / "a.mel")
    new = logic.rename_path(path, "build")
    assert new == os.path.join(str(tmp_path), "build.mel")
    assert os.path.isfile(new) and not os.path.exists(path)


def test_rename_does_not_double_a_typed_extension(tmp_path):
    path = _touch(tmp_path / "a.py")
    assert logic.rename_path(path, "b.py") == os.path.join(str(tmp_path), "b.py")


def test_rename_folder_keeps_contents(tmp_path):
    _touch(tmp_path / "sub" / "x.py")
    new = logic.rename_path(str(tmp_path / "sub"), "rig")
    assert os.path.isfile(os.path.join(new, "x.py"))
    assert _names(logic.scan(str(tmp_path))) == ["rig"]


def test_rename_keeps_place_in_order(tmp_path):
    root = _order_fixture(tmp_path)
    logic.place([os.path.join(root, "c.py")], root, 0)
    logic.rename_path(os.path.join(root, "c.py"), "z")
    assert _names(logic.scan(root)) == ["z.py", "sub", "a.py", "b.py"]


def test_rename_keeps_disabled_state(tmp_path):
    path = _touch(tmp_path / "a.py")
    logic.set_enabled(path, False)
    new = logic.rename_path(path, "b")
    assert not logic.is_enabled(new)
    # A new file reusing the old name starts enabled.
    assert logic.is_enabled(_touch(tmp_path / "a.py"))


def test_rename_to_same_name_is_noop(tmp_path):
    path = _touch(tmp_path / "a.py")
    assert logic.rename_path(path, "  a ") == path


def test_rename_changes_case_only(tmp_path):
    path = _touch(tmp_path / "rig.py")
    new = logic.rename_path(path, "Rig")
    assert os.listdir(str(tmp_path)) == ["Rig.py"]
    assert new == os.path.join(str(tmp_path), "Rig.py")


def test_rename_rejects_bad_names(tmp_path):
    path = _touch(tmp_path / "a.py")
    _touch(tmp_path / "b.py")
    with pytest.raises(FileExistsError):
        logic.rename_path(path, "b")
    with pytest.raises(ValueError):
        logic.rename_path(path, "   ")
    with pytest.raises(ValueError):
        logic.rename_path(path, "x/y")
    with pytest.raises(FileNotFoundError):
        logic.rename_path(str(tmp_path / "missing.py"), "c")
    assert os.path.isfile(path)


# -- copy / paste -----------------------------------------------------------


def test_paste_copies_into_another_folder_at_index(tmp_path):
    root = _order_fixture(tmp_path)
    _touch(tmp_path / "a.py", "print('a')")
    _touch(tmp_path / "sub" / "x.py")
    _touch(tmp_path / "sub" / "y.py")

    new = logic.paste_paths([os.path.join(root, "a.py")], os.path.join(root, "sub"), 1)

    assert new == [os.path.join(root, "sub", "a.py")]
    # The original stays where it was.
    assert os.path.isfile(os.path.join(root, "a.py"))
    with open(new[0], encoding="utf-8") as f:
        assert f.read() == "print('a')"
    assert _names(logic.scan(os.path.join(root, "sub"))) == ["x.py", "a.py", "y.py"]


def test_paste_into_same_folder_adds_copy_suffix(tmp_path):
    root = _order_fixture(tmp_path)
    a = os.path.join(root, "a.py")

    first = logic.paste_paths([a], root, 2)
    second = logic.paste_paths([a], root, None)

    assert first == [os.path.join(root, "a_copy.py")]
    assert second == [os.path.join(root, "a_copy2.py")]
    assert _names(logic.scan(root)) == ["sub", "a.py", "a_copy.py", "b.py", "c.py", "a_copy2.py"]


def test_paste_folder_copies_contents_order_and_disabled_state(tmp_path):
    root = _order_fixture(tmp_path)
    _touch(tmp_path / "sub" / "x.py")
    _touch(tmp_path / "sub" / "y.py")
    sub = os.path.join(root, "sub")
    logic.place([os.path.join(sub, "y.py")], sub, 0)
    logic.set_enabled(os.path.join(sub, "x.py"), False)
    logic.set_enabled(sub, False)

    new = logic.paste_paths([sub], root, None)

    assert new == [os.path.join(root, "sub_copy")]
    copy = logic.scan(root)[-1]
    assert copy.name == "sub_copy" and not copy.enabled
    assert _names(copy.children) == ["y.py", "x.py"]
    assert not copy.children[1].enabled
    # The source is untouched.
    assert _names(logic.scan(sub)) == ["y.py", "x.py"]


def test_paste_keeps_order_of_several_and_skips_items_inside_a_copied_folder(tmp_path):
    root = _order_fixture(tmp_path)
    inner = _touch(tmp_path / "sub" / "x.py")
    (tmp_path / "dest").mkdir()
    dest = os.path.join(root, "dest")

    new = logic.paste_paths([os.path.join(root, "c.py"), os.path.join(root, "sub"), inner], dest, None)

    assert new == [os.path.join(dest, "c.py"), os.path.join(dest, "sub")]
    assert _names(logic.scan(dest)) == ["c.py", "sub"]
    assert os.listdir(os.path.join(dest, "sub")) == ["x.py"]


def test_paste_two_items_with_the_same_name_renames_the_second(tmp_path):
    root = _order_fixture(tmp_path)
    other = _touch(tmp_path / "sub" / "a.py")
    (tmp_path / "dest").mkdir()
    dest = os.path.join(root, "dest")

    new = logic.paste_paths([os.path.join(root, "a.py"), other], dest, None)

    assert new == [os.path.join(dest, "a.py"), os.path.join(dest, "a_copy.py")]


def test_paste_validates_everything_before_copying(tmp_path):
    root = _order_fixture(tmp_path)
    (tmp_path / "dest").mkdir()
    dest = os.path.join(root, "dest")
    with pytest.raises(FileNotFoundError):
        logic.paste_paths([os.path.join(root, "a.py"), os.path.join(root, "gone.py")], dest, None)
    assert os.listdir(dest) == []
    sub = os.path.join(root, "sub")
    with pytest.raises(ValueError):
        logic.paste_paths([sub], sub, None)
    with pytest.raises(ValueError):
        logic.paste_paths([root], sub, None)
