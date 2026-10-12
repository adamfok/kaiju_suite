import os
import time

import pytest

from kaiju_suite.core import datafile, settings
from kaiju_suite.tools.asset_library import logic


@pytest.fixture
def clean_settings():
    for name in ("library", "current_asset"):
        settings.remove(logic.SETTINGS_KEY, name)
    old = os.environ.pop("ASSET", None)
    yield
    for name in ("library", "current_asset"):
        settings.remove(logic.SETTINGS_KEY, name)
    os.environ.pop("ASSET", None)
    if old is not None:
        os.environ["ASSET"] = old


def _norm(path):
    return os.path.normcase(os.path.normpath(path))


# -- creating and reading assets ------------------------------------------------


def test_create_asset_makes_the_folder_layout(tmp_path):
    asset = logic.create_asset(str(tmp_path), "hero")
    folder = tmp_path / "hero"
    assert asset.path == str(folder)
    for sub in logic.FOLDERS:
        assert (folder / sub).is_dir()
    assert datafile.read(str(folder / logic.ASSET_FILE), logic.KIND) == {}


def test_an_asset_is_only_its_folder_and_name(tmp_path):
    logic.create_asset(str(tmp_path), "crate")
    asset = logic.read_asset(str(tmp_path / "crate"))
    assert asset._fields == ("path", "name")
    assert asset.name == "crate"


def test_an_asset_made_with_type_tags_and_notes_still_reads(tmp_path):
    folder = tmp_path / "old"
    folder.mkdir()
    datafile.write(str(folder / logic.ASSET_FILE), logic.KIND, {"type": "prop", "tags": ["wood"], "notes": "hi"})
    assert logic.read_asset(str(folder)).name == "old"


def test_create_asset_refuses_an_existing_folder(tmp_path):
    (tmp_path / "hero").mkdir()
    with pytest.raises(ValueError, match="already"):
        logic.create_asset(str(tmp_path), "hero")


@pytest.mark.parametrize("name", ["", "my hero", "a/b", "../up", "hé"])
def test_create_asset_refuses_names_that_dont_work_as_folders(tmp_path, name):
    with pytest.raises(ValueError):
        logic.create_asset(str(tmp_path), name)
    assert list(tmp_path.iterdir()) == []


def test_create_asset_refuses_a_missing_library(tmp_path):
    with pytest.raises(FileNotFoundError):
        logic.create_asset(str(tmp_path / "nope"), "hero")


def test_thumbnail_is_found_only_when_there_is_one(tmp_path):
    asset = logic.create_asset(str(tmp_path), "hero")
    assert asset.thumbnail is None
    (tmp_path / "hero" / logic.THUMBNAIL).write_bytes(b"png")
    assert _norm(logic.read_asset(asset.path).thumbnail) == _norm(str(tmp_path / "hero" / logic.THUMBNAIL))


# -- scanning a library ---------------------------------------------------------


def test_scan_lists_asset_folders_by_name_and_ignores_the_rest(tmp_path):
    logic.create_asset(str(tmp_path), "zebra")
    logic.create_asset(str(tmp_path), "Apple")
    (tmp_path / "not_an_asset").mkdir()
    (tmp_path / "readme.txt").write_text("hi")
    assert [a.name for a in logic.scan(str(tmp_path))] == ["Apple", "zebra"]


def test_scan_skips_unreadable_asset_files(tmp_path):
    logic.create_asset(str(tmp_path), "good")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / logic.ASSET_FILE).write_text("not json")
    assert [a.name for a in logic.scan(str(tmp_path))] == ["good"]


def test_scan_of_a_missing_library_is_empty(tmp_path):
    assert logic.scan(str(tmp_path / "nope")) == []


# -- filtering ------------------------------------------------------------------


def test_filter_matches_names_ignoring_case(tmp_path):
    for name in ("hero", "dragon", "crate"):
        logic.create_asset(str(tmp_path), name)
    assets = logic.scan(str(tmp_path))
    assert [a.name for a in logic.filter_assets(assets, "HER")] == ["hero"]
    assert [a.name for a in logic.filter_assets(assets, "  ")] == ["crate", "dragon", "hero"]


def test_type_tag_and_note_helpers_are_gone():
    for name in ("update_asset", "parse_tags", "format_tags", "types_in_use", "tags_in_use"):
        assert not hasattr(logic, name), name


# -- rigs -----------------------------------------------------------------------


def test_a_new_asset_has_no_rigs(tmp_path):
    asset = logic.create_asset(str(tmp_path), "hero")
    assert logic.rigs(asset.path) == []


def test_add_rig_makes_its_build_and_publish_folders_and_lists_it(tmp_path):
    asset = logic.create_asset(str(tmp_path), "hero")
    logic.add_rig(asset.path, "skeleton")
    logic.add_rig(asset.path, "puppet")
    assert logic.rigs(asset.path) == ["skeleton", "puppet"]  # in the order they were added
    for rig in ("skeleton", "puppet"):
        assert (tmp_path / "hero" / "build" / rig).is_dir()
        assert (tmp_path / "hero" / "publish" / rig).is_dir()
    assert _norm(logic.build_folder(asset.path, "puppet")) == _norm(str(tmp_path / "hero" / "build" / "puppet"))
    assert _norm(logic.publish_folder(asset.path, "puppet")) == _norm(str(tmp_path / "hero" / "publish" / "puppet"))


def test_add_rig_keeps_other_fields_in_the_asset_file(tmp_path):
    folder = tmp_path / "old"
    folder.mkdir()
    datafile.write(str(folder / logic.ASSET_FILE), logic.KIND, {"notes": "hi"})
    logic.add_rig(str(folder), "proxy")
    assert datafile.read(str(folder / logic.ASSET_FILE), logic.KIND) == {"notes": "hi", "rigs": ["proxy"]}


def test_add_rig_refuses_a_rig_it_already_has_ignoring_case(tmp_path):
    asset = logic.create_asset(str(tmp_path), "hero")
    logic.add_rig(asset.path, "proxy")
    with pytest.raises(ValueError, match="already"):
        logic.add_rig(asset.path, "Proxy")
    assert logic.rigs(asset.path) == ["proxy"]


@pytest.mark.parametrize("name", ["", "my rig", "a/b", "../up", "h\u00e9"])
def test_add_rig_refuses_names_that_dont_work_as_folders(tmp_path, name):
    asset = logic.create_asset(str(tmp_path), "hero")
    with pytest.raises(ValueError):
        logic.add_rig(asset.path, name)
    assert logic.rigs(asset.path) == []
    assert os.listdir(os.path.join(asset.path, "build")) == []


def test_add_rig_refuses_a_folder_that_isnt_an_asset(tmp_path):
    with pytest.raises(ValueError):
        logic.add_rig(str(tmp_path), "proxy")


def test_add_rig_uses_existing_folders(tmp_path):
    asset = logic.create_asset(str(tmp_path), "hero")
    (tmp_path / "hero" / "build" / "hero").mkdir()
    (tmp_path / "hero" / "build" / "hero" / "a.py").write_text("")
    logic.add_rig(asset.path, "hero")
    # A build folder that already has items is left as it is.
    assert os.listdir(tmp_path / "hero" / "build" / "hero") == ["a.py"]
    assert logic.rigs(asset.path) == ["hero"]


def test_add_rig_starts_the_build_with_a_build_folder_and_an_output_to_publish(tmp_path, clean_settings):
    asset = logic.create_asset(str(tmp_path), "hero")
    logic.set_current(asset.path)
    logic.add_rig(asset.path, "proxy")
    build = tmp_path / "hero" / "build" / "proxy"
    assert (build / "build" / "output.out").is_file()
    assert sorted(os.listdir(build)) == [".assembler.json", "build"]  # nothing beside the folder
    out = datafile.read(str(build / "build" / "output.out"), "output")
    # Stored with the variable, so it follows the asset if it moves.
    assert out["path"] == "$ASSET/publish/proxy/hero_proxy.ma"


def test_add_rig_output_is_absolute_when_another_asset_is_current(tmp_path, clean_settings):
    other = logic.create_asset(str(tmp_path), "other")
    logic.set_current(other.path)
    asset = logic.create_asset(str(tmp_path), "hero")
    logic.add_rig(asset.path, "proxy")
    out = datafile.read(os.path.join(logic.build_folder(asset.path, "proxy"), "build", "output.out"), "output")
    assert _norm(out["path"]) == _norm(os.path.join(logic.publish_folder(asset.path, "proxy"), "hero_proxy.ma"))


def test_add_rig_without_the_assembler_still_adds_the_rig(tmp_path, monkeypatch):
    from kaiju_suite import registry

    monkeypatch.setattr(registry, "find", lambda name: None)
    asset = logic.create_asset(str(tmp_path), "hero")
    logic.add_rig(asset.path, "proxy")
    assert logic.rigs(asset.path) == ["proxy"]
    assert os.listdir(logic.build_folder(asset.path, "proxy")) == []


def test_an_old_flat_asset_has_no_rigs(tmp_path):
    """Old assets keep build/ and publish/ flat; their folders aren't rigs."""
    asset = logic.create_asset(str(tmp_path), "hero")
    (tmp_path / "hero" / "build" / "skeleton").mkdir()  # an Assembler folder item
    (tmp_path / "hero" / "publish" / "hero.ma").write_text("x")
    assert logic.rigs(asset.path) == []


def test_rigs_skips_bad_entries_in_the_asset_file(tmp_path):
    asset = logic.create_asset(str(tmp_path), "hero")
    path = os.path.join(asset.path, logic.ASSET_FILE)
    datafile.write(path, logic.KIND, {"rigs": ["proxy", 3, "../up", "Proxy", "hero"]})
    assert logic.rigs(asset.path) == ["proxy", "hero"]
    datafile.write(path, logic.KIND, {"rigs": "proxy"})
    assert logic.rigs(asset.path) == []


def test_latest_publish_is_the_newest_maya_or_fbx_file_of_the_rig(tmp_path):
    asset = logic.create_asset(str(tmp_path), "hero")
    logic.add_rig(asset.path, "proxy")
    logic.add_rig(asset.path, "puppet")
    publish = tmp_path / "hero" / "publish" / "proxy"
    assert logic.latest_publish(asset.path, "proxy") is None
    for i, name in enumerate(["hero_v001.ma", "notes.txt", "hero_v002.mb", "hero.fbx"]):
        (publish / name).write_text("x")
        os.utime(publish / name, (time.time() + i, time.time() + i))
    os.utime(publish / "hero_v002.mb", (time.time() + 10, time.time() + 10))
    assert _norm(logic.latest_publish(asset.path, "proxy")) == _norm(str(publish / "hero_v002.mb"))
    assert logic.latest_publish(asset.path, "puppet") is None


# -- libraries ------------------------------------------------------------------


def test_no_library_until_one_is_set(clean_settings):
    assert logic.library() == ""


def test_set_library_remembers_one_library(tmp_path, clean_settings):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    logic.set_library(str(a))
    logic.set_library(str(b))
    assert _norm(logic.library()) == _norm(str(b))


def test_set_library_refuses_a_missing_folder_and_keeps_the_old_one(tmp_path, clean_settings):
    logic.set_library(str(tmp_path))
    with pytest.raises(FileNotFoundError):
        logic.set_library(str(tmp_path / "nope"))
    assert _norm(logic.library()) == _norm(str(tmp_path))


def test_a_library_folder_that_is_gone_is_forgotten(tmp_path, clean_settings):
    folder = tmp_path / "lib"
    folder.mkdir()
    logic.set_library(str(folder))
    folder.rmdir()
    assert logic.library() == ""


def test_the_list_of_libraries_is_gone():
    for name in ("libraries", "add_library", "remove_library", "create_library"):
        assert not hasattr(logic, name), name


# -- the current asset ----------------------------------------------------------


def test_set_current_sets_asset_variable_and_remembers_it(tmp_path, clean_settings):
    asset = logic.create_asset(str(tmp_path), "hero")
    logic.set_current(asset.path)
    assert _norm(os.environ["ASSET"]) == _norm(asset.path)
    assert _norm(logic.current().path) == _norm(asset.path)


def test_set_current_refuses_a_folder_that_isnt_an_asset(tmp_path, clean_settings):
    with pytest.raises(ValueError):
        logic.set_current(str(tmp_path))
    assert "ASSET" not in os.environ


def test_restore_current_sets_the_variable_again_after_a_restart(tmp_path, clean_settings):
    asset = logic.create_asset(str(tmp_path), "hero")
    logic.set_current(asset.path)
    del os.environ["ASSET"]  # a new Maya session
    assert logic.restore_current().name == "hero"
    assert _norm(os.environ["ASSET"]) == _norm(asset.path)


def test_restore_current_forgets_an_asset_that_is_gone(tmp_path, clean_settings):
    asset = logic.create_asset(str(tmp_path), "hero")
    logic.set_current(asset.path)
    del os.environ["ASSET"]
    os.remove(os.path.join(asset.path, logic.ASSET_FILE))
    assert logic.restore_current() is None
    assert "ASSET" not in os.environ
    assert logic.current() is None


def test_clear_current_unsets_the_variable(tmp_path, clean_settings):
    asset = logic.create_asset(str(tmp_path), "hero")
    logic.set_current(asset.path)
    logic.clear_current()
    assert "ASSET" not in os.environ
    assert logic.current() is None


def test_a_scene_path_under_the_current_asset_is_stored_with_the_variable(tmp_path, clean_settings):
    from kaiju_suite.core import paths

    asset = logic.create_asset(str(tmp_path), "hero")
    logic.set_current(asset.path)
    logic.add_rig(asset.path, "proxy")
    model = os.path.join(asset.path, "files", "model.ma")
    build = logic.build_folder(asset.path, "proxy")
    assert paths.to_portable(model, build) == "$ASSET/files/model.ma"


# -- the tool and its startup hook ----------------------------------------------


def test_asset_library_is_in_the_menu_with_a_startup_hook():
    from kaiju_suite import registry

    tool = registry.find("Asset Library")
    assert tool is not None and tool.get("menu", True)
    assert callable(tool["startup"])


def test_startup_hook_sets_asset_again(tmp_path, clean_settings):
    from kaiju_suite import registry

    asset = logic.create_asset(str(tmp_path), "hero")
    logic.set_current(asset.path)
    del os.environ["ASSET"]  # a new Maya session
    registry.find("Asset Library")["startup"]()
    assert _norm(os.environ["ASSET"]) == _norm(asset.path)


# -- bringing a published file into the scene -----------------------------------


def _published(tmp_path, name="hero", rig="proxy", node="hero_rig"):
    from maya import cmds

    asset = logic.create_asset(str(tmp_path), name)
    logic.add_rig(asset.path, rig)
    cmds.file(new=True, force=True)
    cmds.createNode("transform", name=node)
    path = os.path.join(logic.publish_folder(asset.path, rig), f"{name}_{rig}.ma")
    cmds.file(rename=path)
    cmds.file(save=True, type="mayaAscii")
    cmds.file(new=True, force=True)
    return asset


def test_import_asset_brings_in_the_rigs_latest_publish(new_scene, tmp_path):
    from maya import cmds

    asset = _published(tmp_path)
    logic.import_asset(asset.path, "proxy")
    assert cmds.objExists("hero_rig")


def test_reference_asset_uses_asset_and_rig_as_namespace(new_scene, tmp_path):
    from maya import cmds

    asset = _published(tmp_path)
    logic.reference_asset(asset.path, "proxy")
    assert cmds.objExists("hero_proxy:hero_rig")
    assert len(cmds.file(query=True, reference=True)) == 1


def test_open_asset_opens_the_rigs_latest_publish(new_scene, tmp_path):
    from maya import cmds

    asset = _published(tmp_path)
    logic.open_asset(asset.path, "proxy")
    assert _norm(cmds.file(query=True, sceneName=True)) == _norm(logic.latest_publish(asset.path, "proxy"))


# -- numbered versions ----------------------------------------------------------


def _publish_version(asset, rig="proxy", node="hero_rig", record=None):
    """Publish the next numbered version of ``rig`` holding ``node``, as a
    versioned Output would, leaving the open scene alone; returns the version."""
    from maya import cmds

    from kaiju_suite.core import publishes

    def save(target):
        made = cmds.createNode("transform", name=node)
        cmds.select(made)
        cmds.file(target, exportSelected=True, type="mayaAscii", force=True)
        cmds.delete(made)

    base = os.path.join(logic.publish_folder(asset.path, rig), f"{asset.name}_{rig}.ma")
    return publishes.publish(base, save, record if record is not None else {"qc": None})


def _versioned(tmp_path, count=2, rig="proxy"):
    asset = logic.create_asset(str(tmp_path), "hero")
    logic.add_rig(asset.path, rig)
    for i in range(count):
        _publish_version(asset, rig, node=f"rig_v{i + 1}")
    return asset


def test_latest_publish_follows_the_latest_pointer_not_the_newest_file(new_scene, tmp_path):
    from kaiju_suite.core import publishes

    asset = _versioned(tmp_path)
    publishes.set_latest(publishes.find(logic.publish_folder(asset.path, "proxy"), 1))
    newer = os.path.join(logic.publish_folder(asset.path, "proxy"), "scratch.ma")
    with open(newer, "w") as f:
        f.write("x")
    os.utime(newer, (time.time() + 100, time.time() + 100))
    assert os.path.basename(logic.latest_publish(asset.path, "proxy")) == "hero_proxy_v001.ma"


def test_publish_versions_lists_the_rigs_versions_newest_first(new_scene, tmp_path):
    asset = _versioned(tmp_path, count=3)
    assert [v.number for v in logic.publish_versions(asset.path, "proxy")] == [3, 2, 1]
    logic.add_rig(asset.path, "puppet")
    assert logic.publish_versions(asset.path, "puppet") == []


def test_reference_stores_the_real_version_file_not_the_pointer(new_scene, tmp_path):
    from maya import cmds

    asset = _versioned(tmp_path)
    path = logic.reference_asset(asset.path, "proxy")
    assert os.path.basename(cmds.referenceQuery(path, filename=True, withoutCopyNumber=True)) == "hero_proxy_v002.ma"
    assert cmds.objExists("hero_proxy:rig_v2")


@pytest.mark.parametrize("action", ["import_asset", "reference_asset", "open_asset"])
def test_actions_can_use_an_older_version(new_scene, tmp_path, action):
    from maya import cmds

    asset = _versioned(tmp_path)
    getattr(logic, action)(asset.path, "proxy", version=1)
    assert cmds.ls("rig_v1", recursive=True) and not cmds.ls("rig_v2", recursive=True)


@pytest.mark.parametrize("action", ["import_asset", "reference_asset", "open_asset"])
def test_actions_on_a_version_that_isnt_there_say_so(new_scene, tmp_path, action):
    asset = _versioned(tmp_path)
    with pytest.raises(LookupError, match="no v009"):
        getattr(logic, action)(asset.path, "proxy", version=9)


def test_version_label_shows_the_date_and_qc(new_scene, tmp_path):
    asset = logic.create_asset(str(tmp_path), "hero")
    logic.add_rig(asset.path, "proxy")
    not_run = _publish_version(asset, record={"qc": None})
    clean = _publish_version(asset, record={"qc": [{"item": "check.qc", "problems": []}]})
    found = _publish_version(
        asset, record={"qc": [{"item": "a.qc", "problems": ["Naming: 2 found"]}, {"item": "b.qc", "problems": ["x"]}]}
    )
    date = not_run.record()["date"][:10]
    assert logic.version_label(not_run).startswith(f"v001  {date}")
    assert logic.version_label(not_run).endswith("QC not run")
    assert logic.version_label(clean).endswith("QC passed")
    assert logic.version_label(found).endswith("QC: 2 problems")


def test_version_label_of_a_version_without_a_record_is_its_tag(tmp_path):
    from kaiju_suite.core import publishes

    (tmp_path / "hero_v004.ma").write_text("x")
    assert logic.version_label(publishes.list_versions(str(tmp_path))[0]) == "v004"


# -- updating referenced rigs ---------------------------------------------------


def test_rig_references_lists_referenced_rig_versions_and_their_latest(new_scene, tmp_path):
    from maya import cmds

    asset = _versioned(tmp_path, count=1)
    logic.reference_asset(asset.path, "proxy")
    other = tmp_path / "plain.ma"
    cmds.file(rename=str(other))
    cmds.file(save=True, type="mayaAscii")
    cmds.file(new=True, force=True)
    logic.reference_asset(asset.path, "proxy")
    cmds.file(str(other), reference=True, namespace="plain")  # not a rig: left out

    (found,) = logic.rig_references()
    assert (found.version, found.latest) == (1, 1) and not found.out_of_date
    assert found.namespace == "hero_proxy"

    _publish_version(asset, node="rig_v2")
    (found,) = logic.rig_references()
    assert (found.version, found.latest) == (1, 2) and found.out_of_date
    assert found.label == "hero_proxy: v001 → v002"


def test_update_to_latest_repoints_the_reference(new_scene, tmp_path):
    from maya import cmds

    asset = _versioned(tmp_path, count=1)
    logic.reference_asset(asset.path, "proxy")
    _publish_version(asset, node="rig_v2")
    (ref,) = logic.rig_references()

    new_path = logic.update_to_latest(ref.node)
    assert os.path.basename(new_path) == "hero_proxy_v002.ma"
    assert cmds.objExists("hero_proxy:rig_v2") and not cmds.objExists("hero_proxy:rig_v1")
    assert len(cmds.file(query=True, reference=True)) == 1
    assert logic.update_to_latest(ref.node) is None  # already the latest


def test_update_all_to_latest_updates_only_out_of_date_rigs(new_scene, tmp_path):
    asset = _versioned(tmp_path, count=1)
    logic.add_rig(asset.path, "puppet")
    _publish_version(asset, rig="puppet", node="puppet_v1")
    logic.reference_asset(asset.path, "proxy")
    logic.reference_asset(asset.path, "puppet")
    _publish_version(asset, node="rig_v2")

    updated = logic.update_all_to_latest()
    assert [ref.namespace for ref in updated] == ["hero_proxy"]
    assert not any(ref.out_of_date for ref in logic.rig_references())


def test_update_to_latest_refuses_a_reference_that_isnt_a_rig_version(new_scene, tmp_path):
    from maya import cmds

    cmds.file(rename=str(tmp_path / "plain.ma"))
    cmds.file(save=True, type="mayaAscii")
    cmds.file(new=True, force=True)
    cmds.file(str(tmp_path / "plain.ma"), reference=True, namespace="plain")
    node = cmds.referenceQuery(cmds.file(query=True, reference=True)[0], referenceNode=True)
    with pytest.raises(LookupError, match="isn't a published rig version"):
        logic.update_to_latest(node)


@pytest.mark.parametrize("action", ["import_asset", "reference_asset", "open_asset"])
def test_actions_on_a_rig_with_nothing_published_say_so(new_scene, tmp_path, action):
    asset = logic.create_asset(str(tmp_path), "hero")
    logic.add_rig(asset.path, "proxy")
    with pytest.raises(LookupError, match="hero proxy has nothing published"):
        getattr(logic, action)(asset.path, "proxy")


@pytest.mark.parametrize("action", ["import_asset", "reference_asset", "open_asset"])
def test_actions_on_a_rig_the_asset_doesnt_have_say_so(new_scene, tmp_path, action):
    asset = logic.create_asset(str(tmp_path), "hero")
    with pytest.raises(LookupError, match="hero has no rig called proxy"):
        getattr(logic, action)(asset.path, "proxy")


# -- opening a rig's build in the Assembler -------------------------------------


def test_the_assembler_can_be_opened_on_a_folder():
    from kaiju_suite import registry

    assert callable(registry.find("Assembler")["open"])


def test_open_in_assembler_makes_the_asset_current_and_opens_the_rigs_build(tmp_path, clean_settings, monkeypatch):
    from kaiju_suite import registry

    opened = []
    monkeypatch.setattr(registry, "find", lambda name: {"name": name, "open": opened.append} if name == "Assembler" else None)
    asset = logic.create_asset(str(tmp_path), "hero")
    logic.add_rig(asset.path, "proxy")
    logic.open_in_assembler(asset.path, "proxy")
    assert [_norm(p) for p in opened] == [_norm(logic.build_folder(asset.path, "proxy"))]
    assert _norm(os.environ["ASSET"]) == _norm(asset.path)


def test_open_in_assembler_makes_a_missing_build_folder(tmp_path, clean_settings, monkeypatch):
    import shutil

    from kaiju_suite import registry

    monkeypatch.setattr(registry, "find", lambda name: {"name": name, "open": lambda path: None})
    asset = logic.create_asset(str(tmp_path), "hero")
    logic.add_rig(asset.path, "proxy")
    shutil.rmtree(logic.build_folder(asset.path, "proxy"))
    logic.open_in_assembler(asset.path, "proxy")
    assert os.path.isdir(logic.build_folder(asset.path, "proxy"))


def test_open_in_assembler_refuses_a_rig_the_asset_doesnt_have(tmp_path, clean_settings, monkeypatch):
    from kaiju_suite import registry

    opened = []
    monkeypatch.setattr(registry, "find", lambda name: {"name": name, "open": opened.append})
    asset = logic.create_asset(str(tmp_path), "hero")
    with pytest.raises(LookupError, match="no rig called proxy"):
        logic.open_in_assembler(asset.path, "proxy")
    assert opened == []
    assert "ASSET" not in os.environ


def test_open_in_assembler_without_the_assembler_says_so_and_changes_nothing(tmp_path, clean_settings, monkeypatch):
    from kaiju_suite import registry

    monkeypatch.setattr(registry, "find", lambda name: None)
    asset = logic.create_asset(str(tmp_path), "hero")
    logic.add_rig(asset.path, "proxy")
    with pytest.raises(LookupError, match="Assembler"):
        logic.open_in_assembler(asset.path, "proxy")
    assert "ASSET" not in os.environ


# -- thumbnails -----------------------------------------------------------------


def _image(path, width, height, kind="png"):
    from maya.api import OpenMaya as om

    image = om.MImage()
    image.create(width, height)
    image.writeToFile(str(path), kind)
    return str(path)


def _size(path):
    from maya.api import OpenMaya as om

    image = om.MImage()
    image.readFromFile(str(path))
    return image.getSize()


def test_thumbnail_from_file_saves_a_png_that_fits_the_thumbnail_size(tmp_path):
    asset = logic.create_asset(str(tmp_path), "hero")
    picked = _image(tmp_path / "shot.jpg", 1024, 512, "jpg")
    path = logic.set_thumbnail_from_file(asset.path, picked)
    assert _norm(path) == _norm(os.path.join(asset.path, logic.THUMBNAIL))
    assert _size(path) == [logic.THUMBNAIL_SIZE, logic.THUMBNAIL_SIZE // 2]
    with open(path, "rb") as f:
        assert f.read(8) == b"\x89PNG\r\n\x1a\n"


def test_a_small_image_is_not_scaled_up(tmp_path):
    asset = logic.create_asset(str(tmp_path), "hero")
    path = logic.set_thumbnail_from_file(asset.path, _image(tmp_path / "small.png", 64, 32))
    assert _size(path) == [64, 32]


def test_thumbnail_replaces_the_old_one(tmp_path):
    asset = logic.create_asset(str(tmp_path), "hero")
    logic.set_thumbnail_from_file(asset.path, _image(tmp_path / "a.png", 64, 64))
    logic.set_thumbnail_from_file(asset.path, _image(tmp_path / "b.png", 32, 16))
    assert _size(logic.read_asset(asset.path).thumbnail) == [32, 16]


def test_thumbnail_from_a_file_that_isnt_an_image_changes_nothing(tmp_path):
    asset = logic.create_asset(str(tmp_path), "hero")
    logic.set_thumbnail_from_file(asset.path, _image(tmp_path / "a.png", 64, 64))
    bad = tmp_path / "notes.txt"
    bad.write_text("not an image")
    with pytest.raises(ValueError, match="notes.txt"):
        logic.set_thumbnail_from_file(asset.path, str(bad))
    assert _size(logic.read_asset(asset.path).thumbnail) == [64, 64]


def test_thumbnail_refuses_a_folder_that_isnt_an_asset(tmp_path):
    with pytest.raises(ValueError):
        logic.set_thumbnail_from_file(str(tmp_path), _image(tmp_path / "a.png", 8, 8))


def test_capture_thumbnail_playblasts_the_current_frame_into_the_thumbnail(tmp_path, monkeypatch):
    from maya import cmds

    asset = logic.create_asset(str(tmp_path), "hero")
    calls = []

    def fake_playblast(**kwargs):
        calls.append(kwargs)
        _image(kwargs["completeFilename"], 600, 600)
        return kwargs["completeFilename"]

    monkeypatch.setattr(cmds, "playblast", fake_playblast)
    path = logic.capture_thumbnail(asset.path)
    assert _size(path) == [logic.THUMBNAIL_SIZE, logic.THUMBNAIL_SIZE]
    (kwargs,) = calls
    frame = cmds.currentTime(query=True)
    assert kwargs["frame"] == [frame]
    assert kwargs["format"] == "image"
    assert kwargs["viewer"] is False
    assert kwargs["showOrnaments"] is False
    # The temporary playblast file is cleaned up.
    assert not os.path.exists(kwargs["completeFilename"])
