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


# -- opening an asset's build in the Assembler ----------------------------------


def test_the_assembler_can_be_opened_on_a_folder():
    from kaiju_suite import registry

    assert callable(registry.find("Assembler")["open"])


def test_open_in_assembler_makes_the_asset_current_and_opens_its_build(tmp_path, clean_settings, monkeypatch):
    from kaiju_suite import registry

    opened = []
    monkeypatch.setattr(registry, "find", lambda name: {"name": name, "open": opened.append} if name == "Assembler" else None)
    asset = logic.create_asset(str(tmp_path), "hero")
    logic.open_in_assembler(asset.path)
    assert [_norm(p) for p in opened] == [_norm(logic.build_folder(asset.path))]
    assert _norm(os.environ["ASSET"]) == _norm(asset.path)


def test_open_in_assembler_makes_a_missing_build_folder(tmp_path, clean_settings, monkeypatch):
    import shutil

    from kaiju_suite import registry

    monkeypatch.setattr(registry, "find", lambda name: {"name": name, "open": lambda path: None})
    asset = logic.create_asset(str(tmp_path), "hero")
    shutil.rmtree(logic.build_folder(asset.path))
    logic.open_in_assembler(asset.path)
    assert os.path.isdir(logic.build_folder(asset.path))


def test_open_in_assembler_without_the_assembler_says_so_and_changes_nothing(tmp_path, clean_settings, monkeypatch):
    from kaiju_suite import registry

    monkeypatch.setattr(registry, "find", lambda name: None)
    asset = logic.create_asset(str(tmp_path), "hero")
    with pytest.raises(LookupError, match="Assembler"):
        logic.open_in_assembler(asset.path)
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
