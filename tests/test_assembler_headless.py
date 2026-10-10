"""Headless build: build an Assembler folder from mayapy with no UI."""

import os
import subprocess
import sys

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import headless, logic

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _script(folder, name, code):
    path = os.path.join(str(folder), name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    return path


def test_build_runs_every_enabled_step_and_reports_each(new_scene, tmp_path):
    _script(tmp_path, "a.py", "from maya import cmds\ncmds.polyCube(name='box')\nprint('made a box')\n")
    _script(tmp_path, "b.py", "from maya import cmds\ncmds.warning('looks odd')\n")
    off = _script(tmp_path, "c.py", "from maya import cmds\ncmds.polySphere(name='ball')\n")
    logic.set_enabled(off, False)

    result = headless.build(str(tmp_path))

    assert result.ok
    assert [(s.name, s.status) for s in result.steps] == [("a.py", logic.SUCCESS), ("b.py", logic.WARNING)]
    assert cmds.objExists("box") and not cmds.objExists("ball")
    assert ("INFO", "made a box") in result.steps[0].messages
    assert any(level == "WARNING" and "looks odd" in text for level, text in result.steps[1].messages)


def test_a_failure_stops_the_build_and_later_steps_are_not_run(new_scene, tmp_path):
    _script(tmp_path, "a.py", "raise ValueError('bad rig')\n")
    _script(tmp_path, "b.py", "from maya import cmds\ncmds.polyCube(name='box')\n")

    result = headless.build(str(tmp_path))

    assert not result.ok
    assert [(s.name, s.status) for s in result.steps] == [("a.py", logic.ERROR), ("b.py", headless.NOT_RUN)]
    assert any("bad rig" in text for level, text in result.steps[0].messages if level == "ERROR")
    assert result.steps[1].messages == []
    assert not cmds.objExists("box")


def test_steps_in_subfolders_are_named_relative_to_the_folder(new_scene, tmp_path):
    os.makedirs(tmp_path / "arms")
    _script(tmp_path / "arms", "l.py", "")

    result = headless.build(str(tmp_path))

    assert [s.name for s in result.steps] == ["arms/l.py"]


def test_new_scene_clears_the_scene_first(new_scene, tmp_path):
    cmds.polySphere(name="old")
    _script(tmp_path, "a.py", "")

    headless.build(str(tmp_path))
    assert not cmds.objExists("old")

    cmds.polySphere(name="kept")
    headless.build(str(tmp_path), new_scene=False)
    assert cmds.objExists("kept")


def test_build_saves_the_scene_when_asked(new_scene, tmp_path):
    folder = tmp_path / "build"
    os.makedirs(folder)
    _script(folder, "a.py", "from maya import cmds\ncmds.polyCube(name='box')\n")
    out = str(tmp_path / "rig.ma")

    result = headless.build(str(folder), save=out)

    assert result.ok and result.saved == out
    cmds.file(new=True, force=True)
    cmds.file(out, open=True, force=True)
    assert cmds.objExists("box")


def test_a_failed_build_is_not_saved(new_scene, tmp_path):
    folder = tmp_path / "build"
    os.makedirs(folder)
    _script(folder, "a.py", "raise ValueError('bad rig')\n")
    out = str(tmp_path / "rig.ma")

    result = headless.build(str(folder), save=out)

    assert result.saved is None
    assert not os.path.exists(out)


def test_missing_folder_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        headless.build(str(tmp_path / "nope"))


def test_main_returns_non_zero_on_error_and_prints_a_report(new_scene, tmp_path, capsys):
    _script(tmp_path, "good.py", "")
    assert headless.main([str(tmp_path)]) == 0
    assert "good.py" in capsys.readouterr().out

    _script(tmp_path, "zbad.py", "raise ValueError('bad rig')\n")
    assert headless.main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "zbad.py" in out and "bad rig" in out


def test_main_returns_2_for_a_missing_folder(tmp_path, capsys):
    assert headless.main([str(tmp_path / "nope")]) == 2


def test_command_line_builds_without_qt(tmp_path):
    """Runs mayapy as a user would (one launch, to keep the suite fast). The
    first step fails if Qt or the widget is loaded; the second fails the build."""
    folder = tmp_path / "build"
    os.makedirs(folder)
    _script(
        folder,
        "a.py",
        "import sys\n"
        "loaded = [m for m in ('PySide6', 'PySide2', 'kaiju_suite.tools.assembler.widget') if m in sys.modules]\n"
        "assert not loaded, loaded\n"
        "print('no qt here')\n",
    )
    _script(folder, "b.py", "raise ValueError('bad rig')\n")
    out = tmp_path / "rig.ma"
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "scripts"))

    proc = subprocess.run(
        [sys.executable, "-m", "kaiju_suite.tools.assembler.headless", str(folder), "--new-scene", "--save", str(out)],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )

    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "[SUCCESS] a.py" in proc.stdout and "no qt here" in proc.stdout
    assert "[ERROR] b.py" in proc.stdout and "bad rig" in proc.stdout
    assert not out.exists()
