"""Scripter's right-click Edit in VS Code: finding VS Code and opening a script."""

import os

import pytest

from kaiju_suite.tools.scripter import vscode


@pytest.fixture
def no_vscode(monkeypatch, tmp_path):
    """No ``code`` on PATH and no VS Code in the usual install folders."""
    monkeypatch.setattr(vscode.shutil, "which", lambda name: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "programs"))
    return tmp_path


@pytest.fixture
def launched(monkeypatch):
    calls = []
    monkeypatch.setattr(vscode.subprocess, "Popen", lambda args, **kwargs: calls.append(args))
    return calls


def _install(folder):
    code = folder / "Microsoft VS Code" / "bin" / "code.cmd"
    code.parent.mkdir(parents=True)
    code.write_text("")
    return str(code)


def _script(tmp_path):
    path = tmp_path / "rig scripts" / "build.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("print('hi')\n")
    return str(path)


def test_finds_code_on_path(monkeypatch):
    monkeypatch.setattr(vscode.shutil, "which", lambda name: r"C:\bin\code.cmd" if name == "code" else None)
    assert vscode.find_code() == r"C:\bin\code.cmd"


def test_finds_a_per_user_install(no_vscode):
    code = _install(no_vscode / "local" / "Programs")
    assert vscode.find_code() == code


def test_finds_a_system_install(no_vscode):
    code = _install(no_vscode / "programs")
    assert vscode.find_code() == code


def test_finds_nothing_without_vscode(no_vscode):
    assert vscode.find_code() is None


def test_opens_the_script_in_the_open_vscode_window(no_vscode, launched):
    code = _install(no_vscode / "local" / "Programs")
    script = _script(no_vscode)
    vscode.open_in_vscode(script)
    assert launched == [[code, "--reuse-window", os.path.normpath(script)]]


def test_warns_when_vscode_is_missing(no_vscode, launched):
    with pytest.raises(RuntimeError, match="VS Code"):
        vscode.open_in_vscode(_script(no_vscode))
    assert launched == []


def test_refuses_a_missing_file(no_vscode, launched):
    _install(no_vscode / "local" / "Programs")
    with pytest.raises(FileNotFoundError):
        vscode.open_in_vscode(str(no_vscode / "gone.py"))
    assert launched == []
