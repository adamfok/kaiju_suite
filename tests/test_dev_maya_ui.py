"""dev/maya_ui/maya_ui.py: starts a test Maya, sends it scripts and reports the results.

Only the parts that run outside Maya are tested here; a fake command port
(a socket server in a thread) stands in for Maya.
"""

import json
import os
import socket
import sys
import threading

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "dev", "maya_ui"))

import maya_ui  # noqa: E402


def test_free_port_can_be_bound():
    port = maya_ui.free_port()
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))


def test_maya_exe_sits_next_to_mayapy():
    mayapy = os.path.join("D:", os.sep, "Maya2026", "bin", "mayapy.exe")
    assert maya_ui.maya_exe_for(mayapy) == os.path.join("D:", os.sep, "Maya2026", "bin", "maya.exe")


def test_maya_env_isolates_prefs_and_loads_the_worktree(tmp_path):
    base = {"PYTHONPATH": "C:/elsewhere", "MAYA_MODULE_PATH": "C:/user/modules", "OTHER": "1"}
    env = maya_ui.maya_env(base, worktree="W", app_dir="A", boot_dir="B")

    assert env["MAYA_APP_DIR"] == "A"
    assert env["MAYA_MODULE_PATH"] == "W"  # the user's own modules are left out
    assert env["PYTHONPATH"].split(os.pathsep) == ["B", "C:/elsewhere"]
    assert env["MAYA_NO_HOME"] == "1"
    assert env["OTHER"] == "1"
    assert base["PYTHONPATH"] == "C:/elsewhere"  # the input is not changed


def test_user_setup_boots_the_agent(tmp_path):
    path = maya_ui.write_user_setup(str(tmp_path), agent_dir="D:/agent", session_dir="D:/session")

    assert os.path.basename(path) == "userSetup.py"
    source = open(path, encoding="utf-8").read()
    compile(source, path, "exec")
    assert "D:/agent" in source and "D:/session" in source


def test_wait_for_file_returns_its_text(tmp_path):
    path = tmp_path / "ready.json"
    threading.Timer(0.2, path.write_text, args=('{"port": 1}',)).start()
    assert json.loads(maya_ui.wait_for_file(str(path), timeout=5, poll=0.05)) == {"port": 1}


def test_wait_for_file_times_out(tmp_path):
    with pytest.raises(maya_ui.MayaTimeout):
        maya_ui.wait_for_file(str(tmp_path / "never.json"), timeout=0.3, poll=0.05)


def test_wait_for_file_stops_when_maya_dies(tmp_path):
    with pytest.raises(maya_ui.MayaDied):
        maya_ui.wait_for_file(str(tmp_path / "never.json"), timeout=30, alive=lambda: False, poll=0.05)


class FakePort:
    """A command port that records what it receives and, if ``answer`` is set,
    writes it to the result file named in the command, like the agent does."""

    def __init__(self, answer=None):
        self.answer = answer
        self.received = []
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen()
        self.port = self.server.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                code = conn.recv(65536).decode()
                self.received.append(code)
                if self.answer is not None:
                    result_path = code.split("r'")[-1].split("'")[0]
                    with open(result_path, "w", encoding="utf-8") as f:
                        json.dump(self.answer, f)
                conn.sendall(b"\n")

    def close(self):
        self.server.close()


@pytest.fixture
def session(tmp_path):
    return {"port": None, "pid": os.getpid(), "dir": str(tmp_path)}


def test_run_script_sends_it_and_returns_the_result(session, tmp_path):
    answer = {"checks": [{"name": "menu", "ok": True}]}
    port = FakePort(answer)
    session["port"] = port.port
    script = tmp_path / "scenario.py"
    script.write_text("pass")
    try:
        result = maya_ui.run_script(session, str(script), timeout=5)
    finally:
        port.close()

    assert result == answer
    assert len(port.received) == 1
    assert str(script) in port.received[0]


def test_run_script_times_out_when_no_result_comes(session, tmp_path):
    port = FakePort(answer=None)
    session["port"] = port.port
    script = tmp_path / "scenario.py"
    script.write_text("pass")
    try:
        with pytest.raises(maya_ui.MayaTimeout):
            maya_ui.run_script(session, str(script), timeout=0.5)
    finally:
        port.close()


def test_check_reports_a_maya_that_never_started(monkeypatch):
    def dies(*args, **kwargs):
        raise maya_ui.MayaDied("Maya exited before writing ready.json")

    monkeypatch.setattr(maya_ui, "start", dies)
    ok, text = maya_ui.check("maya.exe", [])
    assert not ok
    assert "Maya didn't start" in text and "ready.json" in text


def test_start_retries_once_when_maya_dies_while_booting(monkeypatch):
    calls = []

    def boot_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise maya_ui.MayaDied("crashed")
        return {"pid": 1}

    monkeypatch.setattr(maya_ui, "_start_once", boot_once)
    assert maya_ui.start("maya.exe") == {"pid": 1}
    assert len(calls) == 2


def test_start_gives_up_after_the_second_death(monkeypatch):
    def always_dies(*args, **kwargs):
        raise maya_ui.MayaDied("crashed")

    monkeypatch.setattr(maya_ui, "_start_once", always_dies)
    with pytest.raises(maya_ui.MayaDied):
        maya_ui.start("maya.exe")


def test_stop_waits_until_maya_has_exited(monkeypatch):
    answers = iter([True, True, True, False])
    monkeypatch.setattr(maya_ui, "pid_alive", lambda pid: next(answers))
    monkeypatch.setattr(maya_ui.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(maya_ui.os, "kill", lambda *a: None, raising=False)
    maya_ui.stop({"pid": 123}, poll=0.01)
    assert next(answers, "drained") == "drained"


def test_boot_settings_hide_maya_unless_asked_to_show():
    assert maya_ui.boot_settings(7001, "W") == {"port": 7001, "worktree": "W", "hide": True}
    assert maya_ui.boot_settings(7001, "W", show=True)["hide"] is False


def test_check_and_start_take_a_show_flag():
    parser_args = maya_ui.parse_args(["check", "--show", "a.py"])
    assert parser_args.show and parser_args.scenarios == ["a.py"]
    assert not maya_ui.parse_args(["start"]).show


def test_compare_menu_lists_missing_and_extra():
    missing, extra = maya_ui.compare_menu(["A", "B", "C"], ["A", "C", "Z"])
    assert missing == ["B"]
    assert extra == ["Z"]


def test_report_passes_when_everything_is_clean():
    ok, text = maya_ui.report({"checks": [{"name": "Open Outliner Tool", "ok": True}]})
    assert ok
    assert "PASS  Open Outliner Tool" in text


def test_report_fails_on_a_failed_check_and_shows_why():
    ok, text = maya_ui.report({"checks": [{"name": "Open Joint Tool", "ok": False, "detail": "boom"}]})
    assert not ok
    assert "FAIL  Open Joint Tool" in text and "boom" in text


@pytest.mark.parametrize("key", ["warnings", "errors", "dialogs"])
def test_report_fails_on_warnings_errors_and_dialogs(key):
    entry = {"title": "Oops", "text": "really"} if key == "dialogs" else "something"
    ok, text = maya_ui.report({"checks": [{"name": "x", "ok": True}], key: [entry]})
    assert not ok
    assert ("Oops" if key == "dialogs" else "something") in text


def test_report_lists_screenshots():
    ok, text = maya_ui.report({"checks": [], "screenshots": ["D:/s/joint.png"]})
    assert "D:/s/joint.png" in text
