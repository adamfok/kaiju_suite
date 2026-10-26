import os

import pytest

from kaiju_suite.core import paths


def _norm(p):
    return os.path.normcase(os.path.normpath(p))


# -- to_portable ----------------------------------------------------------------


def test_a_path_under_the_root_becomes_relative(tmp_path):
    root = tmp_path / "build"
    assert paths.to_portable(str(root / "files" / "hero.ma"), str(root)) == "files/hero.ma"
    assert paths.to_portable(str(root / "hero.ma"), str(root)) == "hero.ma"


def test_relative_uses_forward_slashes_and_ignores_case_on_windows(tmp_path):
    root = str(tmp_path / "build")
    picked = os.path.join(root, "a", "b", "hero.ma")
    if os.name == "nt":
        picked = picked.upper()
        assert paths.to_portable(picked, root) == "A/B/HERO.MA"
    else:
        assert paths.to_portable(picked, root) == "a/b/hero.ma"


def test_a_path_outside_the_root_stays_absolute(tmp_path, monkeypatch):
    monkeypatch.delenv("ASSET", raising=False)
    root = tmp_path / "build"
    outside = str(tmp_path / "elsewhere" / "hero.ma")
    result = paths.to_portable(outside, str(root))
    assert os.path.isabs(result) and "\\" not in result
    assert _norm(result) == _norm(outside)
    # A sibling folder whose name starts like the root's isn't under it.
    sibling = str(tmp_path / "build2" / "hero.ma")
    assert os.path.isabs(paths.to_portable(sibling, str(root)))


def test_a_path_under_a_variable_uses_the_variable(tmp_path, monkeypatch):
    monkeypatch.setenv("ASSET", str(tmp_path / "assets" / "hero"))
    root = tmp_path / "build"
    picked = str(tmp_path / "assets" / "hero" / "model" / "hero.ma")
    assert paths.to_portable(picked, str(root)) == "$ASSET/model/hero.ma"


def test_the_root_wins_over_a_variable(tmp_path, monkeypatch):
    monkeypatch.setenv("ASSET", str(tmp_path))
    root = tmp_path / "build"
    assert paths.to_portable(str(root / "hero.ma"), str(root)) == "hero.ma"


def test_text_with_a_variable_is_kept_as_written(tmp_path):
    assert paths.to_portable("$ASSET/model/hero.ma", str(tmp_path)) == "$ASSET/model/hero.ma"
    assert paths.to_portable("${ASSET}\\hero.ma", str(tmp_path)) == "${ASSET}/hero.ma"


def test_custom_variables(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOW_ROOT", str(tmp_path / "show"))
    picked = str(tmp_path / "show" / "hero.ma")
    assert paths.to_portable(picked, str(tmp_path / "build"), variables=("SHOW_ROOT",)) == "$SHOW_ROOT/hero.ma"


# -- resolve --------------------------------------------------------------------


def test_relative_resolves_against_the_root(tmp_path):
    root = tmp_path / "build"
    result = paths.resolve("files/hero.ma", str(root))
    assert _norm(result) == _norm(root / "files" / "hero.ma")
    assert "\\" not in result


def test_absolute_paths_are_kept(tmp_path):
    absolute = str(tmp_path / "elsewhere" / "hero.ma")
    assert _norm(paths.resolve(absolute, str(tmp_path / "build"))) == _norm(absolute)


def test_variables_are_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("ASSET", str(tmp_path / "assets"))
    for stored in ("$ASSET/hero.ma", "${ASSET}/hero.ma"):
        assert _norm(paths.resolve(stored, str(tmp_path / "build"))) == _norm(tmp_path / "assets" / "hero.ma")


def test_an_unset_variable_is_left_in_and_not_joined_to_the_root(tmp_path, monkeypatch):
    monkeypatch.delenv("KAIJU_NOT_SET", raising=False)
    assert paths.resolve("$KAIJU_NOT_SET/hero.ma", str(tmp_path)) == "$KAIJU_NOT_SET/hero.ma"


def test_round_trip_survives_moving_the_root(tmp_path):
    old_root, new_root = tmp_path / "old", tmp_path / "new"
    stored = paths.to_portable(str(old_root / "files" / "hero.ma"), str(old_root))
    assert _norm(paths.resolve(stored, str(new_root))) == _norm(new_root / "files" / "hero.ma")


def test_empty_text_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        paths.resolve("", str(tmp_path))
