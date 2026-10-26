"""Check Kaiju Suite's UI in a real Maya, driven through its command port.

Starts a separate Maya that loads the module from a worktree, uses throwaway
preferences and opens a command port on a free localhost port. Scenario
scripts are sent to it and run inside Maya by ``kaiju_ui_agent.py``, which
writes each result to a JSON file; this script reads it and prints a report.

Run it with mayapy (only the standard library is used here):

    mayapy dev/maya_ui/maya_ui.py check [scenario.py ...]   # start, smoke check, scenarios, stop
    mayapy dev/maya_ui/maya_ui.py start                     # prints the session folder
    mayapy dev/maya_ui/maya_ui.py run <session> <scenario.py>
    mayapy dev/maya_ui/maya_ui.py smoke <session>
    mayapy dev/maya_ui/maya_ui.py stop <session>

Maya's windows are kept off the screens and don't take focus; add ``--show``
to ``check`` or ``start`` to watch it. Exits 0 when every check passed with no
errors, warnings or dialogs, else 1.
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SMOKE = os.path.join(HERE, "smoke.py")

BOOT_TIMEOUT = 240  # Maya's first start with fresh preferences is slow
SCRIPT_TIMEOUT = 30
RUN_TIMEOUT = 300


class MayaTimeout(RuntimeError):
    """Maya didn't answer in time."""


class MayaDied(RuntimeError):
    """The test Maya exited while we were waiting for it."""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def maya_exe_for(mayapy):
    """maya.exe sits in the same bin folder as mayapy."""
    name = "maya.exe" if mayapy.lower().endswith(".exe") else "maya"
    return os.path.join(os.path.dirname(mayapy), name)


def maya_env(base, worktree, app_dir, boot_dir):
    """The environment for the test Maya: its own preferences folder, only the
    worktree's module, and ``boot_dir`` (holding userSetup.py) first on PYTHONPATH."""
    env = dict(base)
    env["MAYA_APP_DIR"] = app_dir
    env["MAYA_MODULE_PATH"] = worktree
    env["PYTHONPATH"] = os.pathsep.join(p for p in (boot_dir, base.get("PYTHONPATH")) if p)
    # Skip the start-up screens and pop-ups a fresh preferences folder brings.
    env["MAYA_NO_HOME"] = "1"
    env["MAYA_DISABLE_CIP"] = "1"
    env["MAYA_DISABLE_CER"] = "1"
    env["MAYA_DISABLE_CLIC_IPM"] = "1"
    env["MAYA_DISABLE_ADP"] = "1"
    env["MAYA_CM_DISABLE_ERROR_POPUPS"] = "1"
    env["MAYA_COLOR_MGT_NO_LOGGING"] = "1"
    return env


def write_user_setup(boot_dir, agent_dir, session_dir):
    """Write the userSetup.py that makes the test Maya boot the agent."""
    path = os.path.join(boot_dir, "userSetup.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            "import sys\n"
            f"sys.path.insert(0, {agent_dir!r})\n"
            "import kaiju_ui_agent\n"
            f"kaiju_ui_agent.boot_later({session_dir!r})\n"
        )
    return path


def wait_for_file(path, timeout, alive=lambda: True, poll=0.25):
    """Wait for ``path`` to appear and return its text."""
    deadline = time.monotonic() + timeout
    while True:
        if os.path.exists(path):
            # The agent writes to a temp name and renames, so this is complete.
            with open(path, encoding="utf-8") as f:
                return f.read()
        if not alive():
            raise MayaDied(f"Maya exited before writing {path}")
        if time.monotonic() > deadline:
            raise MayaTimeout(f"No answer from Maya after {timeout}s (waiting for {path})")
        time.sleep(poll)


def pid_alive(pid):
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def run_script(session, script, timeout=SCRIPT_TIMEOUT):
    """Run ``script`` inside the session's Maya and return its result dict."""
    results = os.path.join(session["dir"], "results")
    os.makedirs(results, exist_ok=True)
    result_path = os.path.join(results, f"{time.time_ns()}.json")
    code = f"import kaiju_ui_agent; kaiju_ui_agent.run_file(r'{script}', r'{result_path}')"
    with socket.create_connection(("127.0.0.1", session["port"]), timeout=10) as conn:
        conn.sendall(code.encode())
        text = wait_for_file(result_path, timeout, alive=lambda: pid_alive(session["pid"]))
    return json.loads(text)


def compare_menu(expected, found):
    """Tool names missing from the menu, and menu labels that aren't tools."""
    return [n for n in expected if n not in found], [n for n in found if n not in expected]


def report(result):
    """``(ok, text)`` for a result dict from the agent."""
    lines = []
    ok = True
    for check in result.get("checks", []):
        lines.append(f"{'PASS' if check['ok'] else 'FAIL'}  {check['name']}")
        if not check["ok"]:
            ok = False
        if check.get("detail"):
            lines.extend(f"      {line}" for line in str(check["detail"]).splitlines())
    for key, label in (("errors", "Error"), ("warnings", "Warning")):
        for message in result.get(key, []):
            ok = False
            lines.append(f"{label}: {message}")
    for dialog in result.get("dialogs", []):
        ok = False
        lines.append(f"Dialog appeared: {dialog.get('title', '')}: {dialog.get('text', '')}")
        if dialog.get("screenshot"):
            lines.append(f"      screenshot: {dialog['screenshot']}")
    shots = result.get("screenshots", [])
    if shots:
        lines.append("Screenshots:")
        lines.extend(f"  {path}" for path in shots)
    return ok, "\n".join(lines)


# --- session handling -------------------------------------------------------

def _session_file(session_dir):
    return os.path.join(session_dir, "session.json")


def load_session(session_dir):
    with open(_session_file(session_dir), encoding="utf-8") as f:
        return json.load(f)


def boot_settings(port, worktree, show=False):
    """What the agent reads at start-up (boot.json). Unless ``show``, it keeps
    every Maya window off the screens so the test Maya doesn't get in the way."""
    return {"port": port, "worktree": worktree, "hide": not show}


def start(maya_exe, worktree=REPO, session_dir=None, boot_timeout=BOOT_TIMEOUT, show=False):
    """Start a test Maya and wait until its agent is ready. Returns the session dict.

    Maya now and then crashes while starting up; that gets one retry.
    """
    try:
        return _start_once(maya_exe, worktree, session_dir, boot_timeout, show)
    except MayaDied:
        return _start_once(maya_exe, worktree, None, boot_timeout, show)


def _start_once(maya_exe, worktree, session_dir, boot_timeout, show):
    session_dir = session_dir or tempfile.mkdtemp(prefix="kaiju_maya_ui_")
    app_dir = os.path.join(session_dir, "maya_app_dir")
    boot_dir = os.path.join(session_dir, "boot")
    os.makedirs(app_dir, exist_ok=True)
    os.makedirs(boot_dir, exist_ok=True)
    write_user_setup(boot_dir, HERE, session_dir)

    port = free_port()
    with open(os.path.join(session_dir, "boot.json"), "w", encoding="utf-8") as f:
        json.dump(boot_settings(port, worktree, show), f)

    log = os.path.join(session_dir, "maya.log")
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        [maya_exe, "-noAutoloadPlugins", "-log", log],
        env=maya_env(os.environ, worktree, app_dir, boot_dir),
        cwd=session_dir,
        creationflags=flags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    session = {"port": port, "pid": proc.pid, "dir": session_dir, "log": log}
    with open(_session_file(session_dir), "w", encoding="utf-8") as f:
        json.dump(session, f)

    ready_path = os.path.join(session_dir, "ready.json")
    try:
        ready = json.loads(wait_for_file(ready_path, boot_timeout, alive=lambda: proc.poll() is None))
    except (MayaTimeout, MayaDied):
        stop(session)
        raise
    if ready.get("error"):
        stop(session)
        raise RuntimeError(f"Test Maya failed to boot: {ready['error']}")
    return session


def stop(session, timeout=15, poll=0.25):
    """Close the test Maya this session started, and only that one, and wait
    until it has exited so the next run never overlaps it."""
    pid = session["pid"]
    if not pid_alive(pid):
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        os.kill(pid, 9)
    deadline = time.monotonic() + timeout
    while pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(poll)


def _tail(path, lines=40):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-lines:])
    except OSError:
        return "(no log)"


def check(maya_exe, scenarios, worktree=REPO, keep=False, show=False):
    """Start Maya, run the smoke check and each scenario, stop Maya. Returns ``(ok, text)``."""
    deadline = time.monotonic() + RUN_TIMEOUT
    try:
        session = start(maya_exe, worktree, show=show)
    except (MayaTimeout, MayaDied, RuntimeError) as exc:
        return False, f"Maya didn't start: {exc}"
    out = [f"Session folder: {session['dir']}"]
    ok = True
    try:
        for script in [SMOKE, *scenarios]:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MayaTimeout(f"The whole run took longer than {RUN_TIMEOUT}s")
            # The smoke check opens every tool, so it gets longer than one scenario.
            timeout = min(remaining, RUN_TIMEOUT if script == SMOKE else SCRIPT_TIMEOUT)
            passed, text = report(run_script(session, os.path.abspath(script), timeout))
            out.append(f"\n== {os.path.basename(script)}: {'passed' if passed else 'FAILED'}\n{text}")
            ok = ok and passed
    except (MayaTimeout, MayaDied) as exc:
        ok = False
        keep = False
        out.append(f"\n== ABORTED: {exc}\nLast lines of the Maya log ({session['log']}):\n{_tail(session['log'])}")
    finally:
        if not keep:
            stop(session)
    return ok, "\n".join(out)


def _default_maya():
    if "mayapy" in os.path.basename(sys.executable).lower():
        return maya_exe_for(sys.executable)
    return None


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--maya", default=_default_maya(), help="maya.exe (default: next to this mayapy)")
    parser.add_argument("--worktree", default=REPO, help="module root to load (default: this checkout)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("check")
    p.add_argument("scenarios", nargs="*")
    p.add_argument("--keep", action="store_true", help="leave Maya open afterwards")
    p.add_argument("--show", action="store_true", help="let Maya's windows on screen (they're kept off it by default)")
    p = sub.add_parser("start")
    p.add_argument("--show", action="store_true", help="let Maya's windows on screen")
    p = sub.add_parser("run")
    p.add_argument("session")
    p.add_argument("script")
    p.add_argument("--timeout", type=float, default=SCRIPT_TIMEOUT)
    p = sub.add_parser("smoke")
    p.add_argument("session")
    p = sub.add_parser("stop")
    p.add_argument("session")
    args = parser.parse_args(argv)
    if args.command in ("check", "start") and not args.maya:
        parser.error("can't find maya.exe; run this with mayapy or pass --maya")
    return args


def main(argv=None):
    args = parse_args(argv)

    if args.command == "check":
        ok, text = check(args.maya, args.scenarios, args.worktree, args.keep, args.show)
        print(text)
        return 0 if ok else 1
    if args.command == "start":
        session = start(args.maya, args.worktree, show=args.show)
        print(session["dir"])
        return 0
    session = load_session(args.session)
    if args.command == "stop":
        stop(session)
        return 0
    script, timeout = (SMOKE, RUN_TIMEOUT) if args.command == "smoke" else (args.script, args.timeout)
    ok, text = report(run_script(session, os.path.abspath(script), timeout))
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
