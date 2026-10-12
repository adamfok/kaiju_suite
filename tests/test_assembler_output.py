import json
import os

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import logic, plan, products, runlog, versions
from kaiju_suite.tools.assembler.products import output


def _touch(path):
    path.write_bytes(b"")
    return str(path)


def _rig():
    """A small "built rig": a mesh, a joint, and an unused shader."""
    cmds.polyCube(name="body")
    cmds.select(clear=True)
    joint = cmds.joint(name="root_jnt")
    shader = cmds.shadingNode("lambert", asShader=True, name="unused_mat")
    return joint, shader


def _open_saved(path):
    cmds.file(str(path), open=True, force=True)


@pytest.fixture
def picked(monkeypatch):
    """Stand-in for the save-file browser: returns ``picked.answer``."""

    class Picker:
        answer = None
        opened_in = []

        def __call__(self, start_dir):
            self.opened_in.append(start_dir)
            return self.answer

    picker = Picker()
    picker.opened_in = []
    monkeypatch.setattr(output, "pick_output_file", picker)
    return picker


# -- the entry --------------------------------------------------------------


def test_output_items_are_out_files(tmp_path):
    assert output.PRODUCT.name == "Output"
    assert output.PRODUCT.extensions == (".out",)
    assert products.product_for(_touch(tmp_path / "rig.out")) is output.PRODUCT


def test_output_is_a_plain_runnable_versioned_product():
    from kaiju_suite.tools.assembler import data

    assert not isinstance(output.PRODUCT, data.DataProduct)
    assert output.PRODUCT.runnable and output.PRODUCT.versioned and output.PRODUCT.can_disable
    assert output.PRODUCT.utility is None


def test_type_column_shows_output(tmp_path):
    _touch(tmp_path / "rig.out")
    (entry,) = logic.scan(str(tmp_path))
    assert entry.label == "rig" and entry.type_label == "Output"


def test_new_output_is_an_empty_entry(tmp_path):
    path = output.create_output(str(tmp_path), "rig")
    assert path == str(tmp_path / "rig.out")
    assert os.path.getsize(path) == 0
    assert output.settings(path) is None
    with pytest.raises(FileExistsError):
        output.create_output(str(tmp_path), "rig")


def test_output_is_last_in_the_new_menu_after_check():
    labels = [None if e is None else e[1].label for e in products.new_menu()]
    assert labels[-3:] == [None, "QC", "Output"]
    (creator,) = output.PRODUCT.creators
    assert creator.choices is None and not creator.open_after


def test_creator_makes_an_entry(tmp_path):
    (creator,) = output.PRODUCT.creators
    assert creator.fn(str(tmp_path), "rig", None) == str(tmp_path / "rig.out")


# -- settings ---------------------------------------------------------------


def test_set_output_saves_settings_as_a_version_with_a_header(tmp_path):
    path = output.create_output(str(tmp_path), "rig")
    message = output.set_output(path, "D:/deliver/hero_rig.mb", delete_unused=True, hide_joints=False)

    assert message == "Published Output rig.out v001"
    assert output.settings(path) == {
        "path": "D:/deliver/hero_rig.mb",
        "delete_unused": True,
        "hide_joints": False,
        "versioned": False,
    }
    with open(path, encoding="utf-8") as f:
        content = json.load(f)
    assert content["kaiju"] == "output" and content["format"] == 1
    assert [v.number for v in versions.list_versions(path)] == [1]


def test_relative_text_is_stored_as_given(tmp_path):
    path = output.create_output(str(tmp_path), "rig")
    output.set_output(path, "out/hero.ma")
    assert output.settings(path)["path"] == "out/hero.ma"
    assert output.target(path) == (tmp_path / "out" / "hero.ma").as_posix()


def test_a_path_in_the_build_folder_is_stored_relative(tmp_path):
    path = output.create_output(str(tmp_path), "rig")
    output.set_output(path, str(tmp_path / "deliver" / "hero.mb"))
    assert output.settings(path)["path"] == "deliver/hero.mb"


def test_a_path_under_asset_is_stored_with_the_variable(tmp_path, monkeypatch):
    asset = tmp_path / "asset"
    monkeypatch.setenv("ASSET", str(asset))
    (tmp_path / "build").mkdir()
    path = output.create_output(str(tmp_path / "build"), "rig")
    output.set_output(path, str(asset / "rigs" / "hero.ma"))
    assert output.settings(path)["path"] == "$ASSET/rigs/hero.ma"
    assert output.target(path) == (asset / "rigs" / "hero.ma").as_posix()


def test_run_saves_next_to_a_moved_build_folder(new_scene, tmp_path):
    _rig()
    build = tmp_path / "build"
    build.mkdir()
    path = output.create_output(str(build), "rig")
    output.set_output(path, str(build / "deliver" / "hero.ma"))
    moved = tmp_path / "moved"
    os.rename(build, moved)

    output.PRODUCT.run(str(moved / "rig.out"))

    assert (moved / "deliver" / "hero.ma").is_file()
    assert not (build / "deliver").exists()


@pytest.mark.parametrize("bad", ("hero.obj", "hero", ""))
def test_set_output_rejects_unknown_formats_and_changes_nothing(tmp_path, bad):
    path = output.create_output(str(tmp_path), "rig")
    with pytest.raises(ValueError):
        output.set_output(path, bad)
    assert os.path.getsize(path) == 0 and versions.list_versions(path) == []


@pytest.mark.parametrize("ext, fmt", ((".ma", "Maya ASCII"), (".MB", "Maya Binary"), (".fbx", "FBX")))
def test_format_comes_from_the_extension(ext, fmt):
    assert output.format_name("a/b" + ext) == fmt


def test_toggling_an_option_publishes_a_new_version(tmp_path):
    path = output.create_output(str(tmp_path), "rig")
    output.set_output(path, "D:/x.ma")
    output.set_option(path, "hide_joints", True)
    assert output.settings(path)["hide_joints"] is True
    assert sorted(v.number for v in versions.list_versions(path)) == [1, 2]
    with pytest.raises(ValueError):
        output.set_option(path, "bogus", True)


def test_set_option_needs_a_path_first(tmp_path):
    path = output.create_output(str(tmp_path), "rig")
    with pytest.raises(ValueError):
        output.set_option(path, "hide_joints", True)


def test_a_file_of_another_kind_is_refused(tmp_path):
    path = tmp_path / "rig.out"
    path.write_text('{"kaiju": "joints", "format": 1, "data": {}}')
    with pytest.raises(ValueError):
        output.settings(str(path))


# -- publish (file browser) ---------------------------------------------------


def test_publish_picks_a_path_and_keeps_the_options(tmp_path, picked):
    path = output.create_output(str(tmp_path), "rig")
    output.set_output(path, str(tmp_path / "a.ma"), hide_joints=True)
    picked.answer = str(tmp_path / "deliver" / "b.fbx")

    message = output.PRODUCT.publish(path).fn()

    assert message == "Published Output rig.out v002"
    assert output.settings(path) == {
        "path": "deliver/b.fbx",
        "delete_unused": False,
        "hide_joints": True,
        "versioned": False,
    }
    assert picked.opened_in == [str(tmp_path)]


def test_cancelling_the_browser_changes_nothing(tmp_path, picked):
    path = output.create_output(str(tmp_path), "rig")
    assert output.PRODUCT.publish(path).fn() is None
    assert os.path.getsize(path) == 0


# -- run --------------------------------------------------------------------


def test_run_on_an_empty_entry_saves_nothing_with_a_warning(new_scene, tmp_path):
    path = output.create_output(str(tmp_path), "rig")
    with runlog.capture() as log:
        output.PRODUCT.run(path)
    assert any("no output" in m.lower() for m in log.warnings)


@pytest.mark.parametrize("ext, file_type", ((".ma", "mayaAscii"), (".mb", "mayaBinary")))
def test_run_saves_the_scene_in_the_chosen_format(new_scene, tmp_path, ext, file_type):
    _rig()
    cmds.file(rename=str(tmp_path / "work.ma"))
    target = tmp_path / "deliver" / f"hero{ext}"  # folder doesn't exist yet
    path = output.create_output(str(tmp_path), "rig")
    output.set_output(path, str(target))

    output.PRODUCT.run(path)

    assert target.is_file()
    # The open scene keeps its own name: Output exports, it doesn't "Save As".
    assert os.path.basename(cmds.file(query=True, sceneName=True)) == "work.ma"
    _open_saved(target)
    assert cmds.objExists("body") and cmds.objExists("root_jnt")
    assert cmds.file(query=True, type=True) == [file_type]


def test_run_without_cleanup_leaves_the_scene_alone(new_scene, tmp_path):
    joint, shader = _rig()
    path = output.create_output(str(tmp_path), "rig")
    output.set_output(path, str(tmp_path / "hero.ma"))
    output.PRODUCT.run(path)
    assert cmds.objExists(shader)
    assert cmds.getAttr(joint + ".drawStyle") == 0


def test_hide_joints_sets_draw_style_none(new_scene, tmp_path):
    joint, _ = _rig()
    target = tmp_path / "hero.ma"
    path = output.create_output(str(tmp_path), "rig")
    output.set_output(path, str(target), hide_joints=True)

    output.PRODUCT.run(path)

    assert cmds.getAttr(joint + ".drawStyle") == 2
    _open_saved(target)
    assert cmds.getAttr("root_jnt.drawStyle") == 2


def test_hide_joints_skips_locked_draw_style_with_a_warning(new_scene, tmp_path):
    joint, _ = _rig()
    cmds.setAttr(joint + ".drawStyle", lock=True)
    path = output.create_output(str(tmp_path), "rig")
    output.set_output(path, str(tmp_path / "hero.ma"), hide_joints=True)
    with runlog.capture() as log:
        output.PRODUCT.run(path)
    assert any("root_jnt" in m for m in log.warnings)
    assert (tmp_path / "hero.ma").is_file()


def test_delete_unused_removes_unused_shading_nodes(new_scene, tmp_path):
    _, shader = _rig()
    target = tmp_path / "hero.mb"
    path = output.create_output(str(tmp_path), "rig")
    output.set_output(path, str(target), delete_unused=True)

    output.PRODUCT.run(path)

    assert not cmds.objExists(shader)
    assert cmds.objExists("body")
    _open_saved(target)
    assert not cmds.objExists("unused_mat") and cmds.objExists("body")


def test_cleanup_is_one_undo_step(new_scene, tmp_path):
    joint, shader = _rig()
    path = output.create_output(str(tmp_path), "rig")
    output.set_output(path, str(tmp_path / "hero.ma"), delete_unused=True, hide_joints=True)
    output.PRODUCT.run(path)
    assert not cmds.objExists(shader)

    cmds.undo()

    assert cmds.objExists(shader)
    assert cmds.getAttr(joint + ".drawStyle") == 0


def test_fbx_export(new_scene, tmp_path):
    try:
        cmds.loadPlugin("fbxmaya", quiet=True)
    except RuntimeError:
        pytest.skip("fbxmaya plug-in doesn't load under this mayapy")
    _rig()
    target = tmp_path / "hero.fbx"
    path = output.create_output(str(tmp_path), "rig")
    output.set_output(path, str(target))

    output.PRODUCT.run(path)

    assert target.is_file() and target.stat().st_size > 0


def test_fbx_plugin_that_wont_load_is_a_clear_error(new_scene, tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("plug-in not found")

    monkeypatch.setattr(output, "_plugin_loaded", lambda name: False)
    monkeypatch.setattr(output.cmds, "loadPlugin", fail)
    path = output.create_output(str(tmp_path), "rig")
    output.set_output(path, str(tmp_path / "hero.fbx"))

    with pytest.raises(RuntimeError, match="fbxmaya"):
        output.PRODUCT.run(path)
    assert not (tmp_path / "hero.fbx").exists()


# -- info window --------------------------------------------------------------


def test_panel_for_an_empty_entry(tmp_path):
    path = output.create_output(str(tmp_path), "rig")
    panel = output.PRODUCT.panel(path)
    assert "Not set up" in panel.info[0]


def test_panel_shows_settings_and_toggles_options(tmp_path):
    path = output.create_output(str(tmp_path), "rig")
    output.set_output(path, "D:/deliver/hero.fbx")
    panel = output.PRODUCT.panel(path)
    text = "\n".join(panel.info)
    assert "D:/deliver/hero.fbx" in text and "FBX" in text
    assert "Delete unused nodes: off" in text and "Hide joints: off" in text

    labels = [a.label for a in panel.actions]
    assert labels == ["Turn On Delete Unused Nodes", "Turn On Hide Joints", "Turn On Numbered Versions"]
    panel.actions[1].fn()
    assert output.settings(path)["hide_joints"] is True
    assert [a.label for a in output.PRODUCT.panel(path).actions][1] == "Turn Off Hide Joints"


# -- build plans --------------------------------------------------------------


def test_build_plan_round_trip(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    path = output.create_output(str(src), "rig")
    output.set_output(path, "D:/deliver/hero.mb", hide_joints=True)

    item = output.PRODUCT.to_plan(path)
    assert item == {"path": "D:/deliver/hero.mb", "delete_unused": False, "hide_joints": True, "versioned": False}
    assert output.PRODUCT.plan_problems(item) == []

    dst = str(tmp_path / "dst.out")
    output.PRODUCT.from_plan(dst, item)
    assert output.settings(dst) == output.settings(path)


def test_empty_entry_plans_as_empty(tmp_path):
    path = output.create_output(str(tmp_path), "rig")
    assert output.PRODUCT.to_plan(path) == {}
    dst = str(tmp_path / "dst.out")
    output.PRODUCT.from_plan(dst, {})
    assert os.path.getsize(dst) == 0


@pytest.mark.parametrize(
    "item",
    ({"path": 3}, {"path": "a.obj"}, {"path": "a.ma", "hide_joints": "yes"}, {"delete_unused": True}),
)
def test_plan_problems(item):
    assert output.PRODUCT.plan_problems(item)


def test_plan_export_includes_output_settings(tmp_path):
    path = output.create_output(str(tmp_path), "rig")
    output.set_output(path, "D:/deliver/hero.ma")
    exported = plan.export_plan(str(tmp_path))
    assert json.dumps(exported).count("D:/deliver/hero.ma") == 1


# -- numbered versions --------------------------------------------------------


def _upstream(folder, node="skeleton_root"):
    """A published upstream rig: ``folder/hero_skeleton_v001.ma`` holding ``node``."""
    from kaiju_suite.core import publishes

    def save(target):
        cmds.file(new=True, force=True)
        cmds.createNode("transform", name=node)
        cmds.file(rename=target)
        cmds.file(save=True, type="mayaAscii")
        cmds.file(new=True, force=True)

    os.makedirs(folder, exist_ok=True)
    return publishes.publish(os.path.join(folder, "hero_skeleton.ma"), save, {})


def test_numbered_versions_are_off_unless_asked(tmp_path):
    path = output.create_output(str(tmp_path), "rig")
    output.set_output(path, "D:/deliver/hero.ma")
    assert output.settings(path)["versioned"] is False
    output.set_output(path, "D:/deliver/hero.ma", versioned=True)
    assert output.settings(path)["versioned"] is True


def test_an_entry_written_before_numbered_versions_reads_as_off(tmp_path):
    from kaiju_suite.core import datafile

    path = str(tmp_path / "rig.out")
    datafile.write(path, output.KIND, {"path": "hero.ma", "delete_unused": False, "hide_joints": False})
    assert output.settings(path)["versioned"] is False


def test_numbered_versions_toggle_is_a_new_version(tmp_path):
    path = output.create_output(str(tmp_path), "rig")
    output.set_output(path, "D:/deliver/hero.ma")
    output.set_option(path, "versioned", True)
    assert output.settings(path)["versioned"] is True
    assert versions.list_versions(path)[0].description == "Output: numbered versions on"


def test_first_publish_turns_numbered_versions_on(tmp_path, picked):
    path = output.create_output(str(tmp_path), "rig")
    picked.answer = str(tmp_path / "hero.ma")
    output.publish_from_browser(path)
    assert output.settings(path)["versioned"] is True
    # Later publishes keep what was chosen.
    output.set_option(path, "versioned", False)
    output.publish_from_browser(path)
    assert output.settings(path)["versioned"] is False


def test_a_new_rig_build_saves_numbered_versions(tmp_path):
    plan.start_build(str(tmp_path), str(tmp_path / "publish" / "hero_puppet.ma"))
    assert output.settings(str(tmp_path / "build" / "output.out"))["versioned"] is True


def test_versioned_run_saves_the_next_version_and_points_latest_at_it(new_scene, tmp_path):
    from kaiju_suite.core import publishes

    publish = tmp_path / "publish"
    path = output.create_output(str(tmp_path), "rig")
    output.set_output(path, str(publish / "hero_puppet.ma"), versioned=True)
    _rig()
    first = output.run_output(path)
    second = output.run_output(path)

    assert os.path.basename(first) == "hero_puppet_v001.ma"
    assert os.path.basename(second) == "hero_puppet_v002.ma"
    assert not (publish / "hero_puppet.ma").exists()  # never overwritten in place
    assert publishes.latest(str(publish)).number == 2
    _open_saved(second)
    assert cmds.objExists("root_jnt")


def test_versioned_run_logs_which_version_it_saved(new_scene, tmp_path):
    path = output.create_output(str(tmp_path), "rig")
    output.set_output(path, str(tmp_path / "publish" / "hero.ma"), versioned=True)
    with runlog.capture() as run:
        output.run_output(path)
    assert any("v001" in message for _, message in run.entries)


def test_an_output_run_on_its_own_records_no_build(new_scene, tmp_path):
    from kaiju_suite.core import publishes

    path = output.create_output(str(tmp_path), "rig")
    output.set_output(path, str(tmp_path / "publish" / "hero.ma"), versioned=True)
    output.run_output(path)
    record = publishes.latest(str(tmp_path / "publish")).record()
    assert record["build"] is None and record["qc"] is None and record["inputs"] == []
    assert record["maya_version"] == cmds.about(version=True)
    assert record["output_item"] == {"item": "rig.out", "version": "v001"}


def test_the_build_record_holds_the_build_qc_and_upstream_versions(new_scene, tmp_path, monkeypatch):
    from kaiju_suite.core import publishes
    from kaiju_suite.tools.assembler.products import qc, scene

    asset = tmp_path / "hero"
    monkeypatch.setenv("ASSET", str(asset))
    upstream = _upstream(str(asset / "publish" / "skeleton"))

    root = asset / "build" / "puppet"
    root.mkdir(parents=True)
    scene_item = scene.create_scene(str(root), "skeleton")
    scene.point_to(scene_item, upstream.path)
    check = qc.create_qc(str(root), "check")
    versions.publish(check)
    out = output.create_output(str(root), "rig")
    output.set_output(out, str(asset / "publish" / "puppet" / "hero_puppet.ma"), versioned=True)
    versions.publish(str(root))

    logic.run_steps([scene_item, check, out], root=str(root))

    record = publishes.latest(str(asset / "publish" / "puppet")).record()
    assert record["build"] == {"folder": "$ASSET/build/puppet", "version": "v001"}
    assert [entry["item"] for entry in record["qc"]] == ["check.qc"]
    assert record["qc"][0]["status"] in (logic.SUCCESS, logic.WARNING)
    assert record["qc"][0]["summary"].startswith("Ran ")
    assert isinstance(record["qc"][0]["problems"], list)
    assert record["inputs"] == [{"file": "$ASSET/publish/skeleton/hero_skeleton_v001.ma", "version": 1}]
    assert cmds.objExists("skeleton_root")


def test_the_build_record_marks_a_build_with_unpublished_changes(new_scene, tmp_path):
    from kaiju_suite.core import publishes

    root = tmp_path / "build"
    root.mkdir()
    out = output.create_output(str(root), "rig")
    output.set_output(out, str(tmp_path / "publish" / "hero.ma"), versioned=True)
    versions.publish(str(root))
    (root / "extra.py").write_text("")

    logic.run_steps([out], root=str(root))
    record = publishes.latest(str(tmp_path / "publish")).record()
    assert record["build"]["version"] == "v001*"
    assert record["qc"] == []  # the build ran, with no QC step


def test_a_never_published_build_has_no_build_version(new_scene, tmp_path):
    from kaiju_suite.core import publishes

    out = output.create_output(str(tmp_path), "rig")
    output.set_output(out, str(tmp_path / "publish" / "hero.ma"), versioned=True)
    logic.run_steps([out], root=str(tmp_path))
    record = publishes.latest(str(tmp_path / "publish")).record()
    assert record["build"]["version"] is None


def test_unversioned_run_still_overwrites_one_file(new_scene, tmp_path):
    path = output.create_output(str(tmp_path), "rig")
    output.set_output(path, str(tmp_path / "publish" / "hero.ma"))
    output.run_output(path)
    output.run_output(path)
    assert os.listdir(tmp_path / "publish") == ["hero.ma"]


def test_panel_shows_numbered_versions_and_the_latest(new_scene, tmp_path):
    path = output.create_output(str(tmp_path), "rig")
    output.set_output(path, str(tmp_path / "publish" / "hero.ma"), versioned=True)
    text = "\n".join(output.PRODUCT.panel(path).info)
    assert "Numbered versions: on" in text and "Latest: none yet" in text
    output.run_output(path)
    text = "\n".join(output.PRODUCT.panel(path).info)
    assert "Latest: v001" in text and "hero_v001.ma" in text
