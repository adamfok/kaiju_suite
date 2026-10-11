import os
import time

import pytest

from kaiju_suite.core import datafile, settings
from kaiju_suite.tools.asset_library import logic


@pytest.fixture
def clean_settings():
    for name in ("libraries", "current_asset"):
        settings.remove(logic.SETTINGS_KEY, name)
    old = os.environ.pop("ASSET", None)
    yield
    for name in ("libraries", "current_asset"):
        settings.remove(logic.SETTINGS_KEY, name)
    os.environ.pop("ASSET", None)
    if old is not None:
        os.environ["ASSET"] = old


def _norm(path):
    return os.path.normcase(os.path.normpath(path))


# -- creating and reading assets ------------------------------------------------


def test_create_asset_makes_the_folder_layout(tmp_path):
    asset = logic.create_asset(str(tmp_path), "hero", asset_type="character", tags=["biped"], notes="Main guy")
    folder = tmp_path / "hero"
    assert asset.path == str(folder)
    for sub in logic.FOLDERS:
        assert (folder / sub).is_dir()
    assert datafile.read(str(folder / logic.ASSET_FILE), logic.KIND) == {
        "type": "character",
        "tags": ["biped"],
        "notes": "Main guy",
    }


def test_read_asset_gives_its_fields_and_name_from_the_folder(tmp_path):
    logic.create_asset(str(tmp_path), "crate", asset_type="prop", tags=["wood", "box"])
    asset = logic.read_asset(str(tmp_path / "crate"))
    assert asset.name == "crate"
    assert asset.type == "prop"
    assert asset.tags == ["wood", "box"]
    assert asset.notes == ""


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


def test_update_asset_changes_only_the_given_fields(tmp_path):
    logic.create_asset(str(tmp_path), "hero", asset_type="character", tags=["biped"], notes="old")
    asset = logic.update_asset(str(tmp_path / "hero"), notes="new")
    assert (asset.type, asset.tags, asset.notes) == ("character", ["biped"], "new")
    assert logic.read_asset(str(tmp_path / "hero")).notes == "new"


def test_tags_are_trimmed_and_deduplicated(tmp_path):
    asset = logic.create_asset(str(tmp_path), "hero", tags=[" biped ", "biped", "", "hero"])
    assert asset.tags == ["biped", "hero"]


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


def _assets(tmp_path):
    logic.create_asset(str(tmp_path), "hero", asset_type="character", tags=["biped"], notes="Main guy")
    logic.create_asset(str(tmp_path), "dragon", asset_type="character", tags=["quadruped", "wings"])
    logic.create_asset(str(tmp_path), "crate", asset_type="prop", tags=["wood"])
    return logic.scan(str(tmp_path))


def test_filter_by_text_matches_name_tags_and_notes_ignoring_case(tmp_path):
    assets = _assets(tmp_path)
    assert [a.name for a in logic.filter_assets(assets, text="HER")] == ["hero"]
    assert [a.name for a in logic.filter_assets(assets, text="wing")] == ["dragon"]
    assert [a.name for a in logic.filter_assets(assets, text="main")] == ["hero"]


def test_filter_by_type_and_tag(tmp_path):
    assets = _assets(tmp_path)
    assert [a.name for a in logic.filter_assets(assets, asset_type="character")] == ["dragon", "hero"]
    assert [a.name for a in logic.filter_assets(assets, tag="wood")] == ["crate"]
    assert [a.name for a in logic.filter_assets(assets, asset_type="prop", tag="biped")] == []


def test_types_and_tags_in_use(tmp_path):
    assets = _assets(tmp_path)
    assert logic.types_in_use(assets) == ["character", "prop"]
    assert logic.tags_in_use(assets) == ["biped", "quadruped", "wings", "wood"]


# -- published files ------------------------------------------------------------


def test_latest_publish_is_the_newest_maya_or_fbx_file(tmp_path):
    asset = logic.create_asset(str(tmp_path), "hero")
    publish = tmp_path / "hero" / "publish"
    assert logic.latest_publish(asset.path) is None
    for i, name in enumerate(["hero_v001.ma", "notes.txt", "hero_v002.mb", "hero.fbx"]):
        (publish / name).write_text("x")
        os.utime(publish / name, (time.time() + i, time.time() + i))
    os.utime(publish / "hero_v002.mb", (time.time() + 10, time.time() + 10))
    assert _norm(logic.latest_publish(asset.path)) == _norm(str(publish / "hero_v002.mb"))


def test_build_folder_is_known_only_when_it_has_items(tmp_path):
    asset = logic.create_asset(str(tmp_path), "hero")
    assert _norm(logic.build_folder(asset.path)) == _norm(str(tmp_path / "hero" / "build"))
    assert not logic.has_build(asset.path)
    (tmp_path / "hero" / "build" / "model.scene").write_text("{}")
    assert logic.has_build(asset.path)


# -- libraries ------------------------------------------------------------------


def test_libraries_are_remembered_in_order_without_duplicates(tmp_path, clean_settings):
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    assert logic.libraries() == []
    logic.add_library(a)
    logic.add_library(b)
    logic.add_library(a)
    assert [_norm(p) for p in logic.libraries()] == [_norm(a), _norm(b)]
    logic.remove_library(a)
    assert [_norm(p) for p in logic.libraries()] == [_norm(b)]


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
    model = os.path.join(asset.path, "files", "model.ma")
    build = logic.build_folder(asset.path)
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


# -- tags typed by the user -----------------------------------------------------


def test_parse_tags_splits_on_commas_and_spaces():
    assert logic.parse_tags(" biped, hero  wings,,biped ") == ["biped", "hero", "wings"]
    assert logic.parse_tags("") == []


def test_format_tags_is_what_parse_tags_reads_back():
    assert logic.parse_tags(logic.format_tags(["a", "b"])) == ["a", "b"]


# -- bringing a published file into the scene -----------------------------------


def _published(tmp_path, name="hero", node="hero_rig"):
    from maya import cmds

    asset = logic.create_asset(str(tmp_path), name)
    cmds.file(new=True, force=True)
    cmds.createNode("transform", name=node)
    path = os.path.join(asset.path, "publish", f"{name}_rig.ma")
    cmds.file(rename=path)
    cmds.file(save=True, type="mayaAscii")
    cmds.file(new=True, force=True)
    return asset


def test_import_asset_brings_in_the_latest_publish(new_scene, tmp_path):
    from maya import cmds

    asset = _published(tmp_path)
    logic.import_asset(asset.path)
    assert cmds.objExists("hero_rig")


def test_reference_asset_uses_the_asset_name_as_namespace(new_scene, tmp_path):
    from maya import cmds

    asset = _published(tmp_path)
    logic.reference_asset(asset.path)
    assert cmds.objExists("hero:hero_rig")
    assert len(cmds.file(query=True, reference=True)) == 1


def test_open_asset_opens_the_latest_publish(new_scene, tmp_path):
    from maya import cmds

    asset = _published(tmp_path)
    logic.open_asset(asset.path)
    assert _norm(cmds.file(query=True, sceneName=True)) == _norm(logic.latest_publish(asset.path))


@pytest.mark.parametrize("action", ["import_asset", "reference_asset", "open_asset"])
def test_actions_on_an_asset_with_nothing_published_say_so(new_scene, tmp_path, action):
    asset = logic.create_asset(str(tmp_path), "hero")
    with pytest.raises(LookupError, match="hero has nothing published"):
        getattr(logic, action)(asset.path)


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
