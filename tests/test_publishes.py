import os

import pytest

import kaiju_suite
from kaiju_suite.core import datafile, publishes


def _norm(path):
    return os.path.normcase(os.path.normpath(path))


def _save(text="x"):
    def save(target):
        with open(target, "w") as f:
            f.write(text)

    return save


def test_version_path_puts_the_number_before_the_extension(tmp_path):
    base = str(tmp_path / "hero_puppet.ma")
    assert _norm(publishes.version_path(base, 3)) == _norm(str(tmp_path / "hero_puppet_v003.ma"))
    assert publishes.version_path(base, 1234).endswith("hero_puppet_v1234.ma")


def test_an_empty_folder_has_no_versions_and_starts_at_one(tmp_path):
    assert publishes.list_versions(str(tmp_path)) == []
    assert publishes.list_versions(str(tmp_path / "missing")) == []
    assert publishes.next_number(str(tmp_path)) == 1
    assert publishes.latest(str(tmp_path)) is None


def test_publish_saves_a_numbered_file_a_record_and_points_latest_at_it(tmp_path):
    base = str(tmp_path / "hero_puppet.ma")
    first = publishes.publish(base, _save("one"), {"qc": None})
    second = publishes.publish(base, _save("two"), {"qc": None})

    assert (first.number, second.number) == (1, 2)
    assert second.tag == "v002"
    assert open(second.path).read() == "two"
    assert sorted(os.listdir(tmp_path)) == [
        "hero_puppet_v001.json",
        "hero_puppet_v001.ma",
        "hero_puppet_v002.json",
        "hero_puppet_v002.ma",
        "latest.json",
    ]
    # Nothing replaces the base file: "latest" is a pointer, not a copy.
    assert not os.path.exists(base)
    assert publishes.latest(str(tmp_path)).number == 2
    assert datafile.read(str(tmp_path / "latest.json"), publishes.LATEST_KIND) == {
        "version": 2,
        "file": "hero_puppet_v002.ma",
    }


def test_the_record_holds_the_given_fields_and_when_who_and_which_kaiju(tmp_path):
    version = publishes.publish(str(tmp_path / "hero_puppet.ma"), _save(), {"qc": [], "inputs": []})
    record = version.record()
    assert record["version"] == 1 and record["file"] == "hero_puppet_v001.ma"
    assert record["kaiju_version"] == kaiju_suite.__version__
    assert record["date"][:4].isdigit() and "T" in record["date"]
    assert record["user"]
    assert record["qc"] == [] and record["inputs"] == []


def test_numbers_run_on_across_base_names_so_a_rig_has_one_sequence(tmp_path):
    publishes.publish(str(tmp_path / "hero_puppet.ma"), _save(), {})
    renamed = publishes.publish(str(tmp_path / "kaiju_puppet.mb"), _save(), {})
    assert renamed.number == 2 and renamed.path.endswith("kaiju_puppet_v002.mb")


def test_versions_are_listed_newest_first_and_other_files_are_ignored(tmp_path):
    for name in ["hero_v001.ma", "hero_v003.ma", "hero_v002.fbx", "notes_v9.txt.bak", "hero.ma", "hero_v004.json"]:
        (tmp_path / name).write_text("x")
    found = publishes.list_versions(str(tmp_path))
    assert [(v.number, os.path.basename(v.path)) for v in found] == [
        (3, "hero_v003.ma"),
        (2, "hero_v002.fbx"),
        (1, "hero_v001.ma"),
    ]
    assert found[0].record() is None  # made by hand: no record


def test_a_failed_save_leaves_latest_and_the_records_alone(tmp_path):
    base = str(tmp_path / "hero.ma")
    publishes.publish(base, _save(), {})

    def broken(target):
        raise RuntimeError("disk full")

    with pytest.raises(RuntimeError, match="disk full"):
        publishes.publish(base, broken, {})
    assert publishes.latest(str(tmp_path)).number == 1
    assert sorted(os.listdir(tmp_path)) == ["hero_v001.json", "hero_v001.ma", "latest.json"]


def test_latest_is_none_when_the_pointer_is_broken_or_its_file_is_gone(tmp_path):
    base = str(tmp_path / "hero.ma")
    version = publishes.publish(base, _save(), {})
    os.remove(version.path)
    assert publishes.latest(str(tmp_path)) is None
    (tmp_path / "latest.json").write_text("not json")
    assert publishes.latest(str(tmp_path)) is None


def test_set_latest_points_at_an_older_version(tmp_path):
    base = str(tmp_path / "hero.ma")
    first = publishes.publish(base, _save(), {})
    publishes.publish(base, _save(), {})
    publishes.set_latest(first)
    assert publishes.latest(str(tmp_path)).number == 1


def test_version_of_knows_a_published_version_from_its_path(tmp_path):
    version = publishes.publish(str(tmp_path / "hero.ma"), _save(), {})
    found = publishes.version_of(version.path.replace("\\", "/"))
    assert found.number == 1 and _norm(found.folder) == _norm(str(tmp_path))
    assert publishes.version_of(str(tmp_path / "hero.ma")) is None
    # A numbered file in a folder that was never published to isn't a version.
    other = tmp_path / "other"
    other.mkdir()
    (other / "hero_v001.ma").write_text("x")
    assert publishes.version_of(str(other / "hero_v001.ma")) is None


def test_find_version_by_number(tmp_path):
    base = str(tmp_path / "hero.ma")
    publishes.publish(base, _save(), {})
    publishes.publish(base, _save(), {})
    assert publishes.find(str(tmp_path), 1).path.endswith("hero_v001.ma")
    with pytest.raises(LookupError, match="no v007"):
        publishes.find(str(tmp_path), 7)
