"""Run logs: what each build step did, with its warnings and errors.

While a step runs inside :func:`capture`, everything it reports is kept in a
:class:`RunLog`: lines products add with :func:`info` and :func:`warning`,
Maya's output (``cmds.warning``, MEL ``print`` and ``warning``, errors) and,
outside the Maya UI, Python ``print``. :mod:`.logic` saves each step's log
next to the item, as ``<folder>/.logs/<item name>.log`` (scan() skips
dot-names), so the last run of every item can be read back. No Qt here.
"""

import contextlib
import os
import sys
import time

from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.core.log import get_logger

log = get_logger(__name__)

LOG_DIR = ".logs"

INFO = "INFO"
WARNING = "WARNING"
ERROR = "ERROR"
LEVELS = (INFO, WARNING, ERROR)

# Each entry's first line is "LEVEL   message"; its other lines are indented
# by the same width, so a line starting with a level always begins an entry.
_WIDTH = len(WARNING) + 1

# Maya output kinds kept, and the level each is logged at. Command echoes
# (kHistory) and results (kResult) are left out.
_MAYA_LEVELS = {
    om.MCommandMessage.kDisplay: INFO,
    om.MCommandMessage.kInfo: INFO,
    om.MCommandMessage.kWarning: WARNING,
    om.MCommandMessage.kError: ERROR,
    om.MCommandMessage.kStackTrace: ERROR,
}


class RunLog:
    """The ``(level, message)`` entries of one run, in order."""

    def __init__(self):
        self.entries = []

    def add(self, level, message):
        message = str(message).rstrip()
        if message:
            self.entries.append((level, message))

    def info(self, message):
        self.add(INFO, message)

    def warning(self, message):
        self.add(WARNING, message)

    def error(self, message):
        self.add(ERROR, message)

    @property
    def warnings(self):
        return [message for level, message in self.entries if level == WARNING]

    @property
    def has_problems(self):
        """Whether anything was logged as a warning or an error."""
        return any(level != INFO for level, _ in self.entries)


# -- capturing ----------------------------------------------------------------

_current = []  # the RunLogs being captured into, innermost last
_quiet = [False]  # True while echoing to Maya what is already recorded


def _record(level, message):
    if _current and not _quiet[0]:
        _current[-1].add(level, message)


def info(message):
    """Record ``message`` in the step being run, if any."""
    log.info(message)
    if _current:
        _current[-1].info(message)


def warning(message):
    """Record ``message`` as a warning in the step being run, if any, and show
    it in Maya's output. A step with a warning ends with the warning status."""
    if _current:
        _current[-1].warning(message)
    _quiet[0] = True
    try:
        cmds.warning(f"Kaiju Assembler: {message}")
    finally:
        _quiet[0] = False


class _Tee:
    """Passes writes on to ``stream`` and records each finished line."""

    def __init__(self, stream, level):
        self._stream = stream
        self._level = level
        self._pending = ""

    def write(self, text):
        self._pending += text
        *lines, self._pending = self._pending.split("\n")
        for line in lines:
            _record(self._level, line)
        return self._stream.write(text)

    def flush(self):
        if self._pending:
            _record(self._level, self._pending)
            self._pending = ""
        self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _on_maya_output(message, kind, *_):
    level = _MAYA_LEVELS.get(kind)
    if level:
        _record(level, message)


@contextlib.contextmanager
def capture():
    """Record what runs inside the block; yields the :class:`RunLog`."""
    run = RunLog()
    _current.append(run)
    callback = om.MCommandMessage.addCommandOutputCallback(_on_maya_output)
    # In the Maya UI, Python's print already reaches the output callback.
    interactive = om.MGlobal.mayaState() == om.MGlobal.kInteractive
    streams = None if interactive else (sys.stdout, sys.stderr)
    if streams:
        sys.stdout, sys.stderr = _Tee(sys.stdout, INFO), _Tee(sys.stderr, ERROR)
    try:
        yield run
    finally:
        if streams:
            sys.stdout.flush()
            sys.stderr.flush()
            sys.stdout, sys.stderr = streams
        om.MMessage.removeCallback(callback)
        _current.remove(run)


# -- files ----------------------------------------------------------------------


def log_path(path):
    """Where ``path``'s last run log is kept (it may not exist)."""
    directory, name = os.path.split(os.path.normpath(path))
    return os.path.join(directory, LOG_DIR, f"{name}.log")


def exists(path):
    return os.path.isfile(log_path(path))


def save(path, run, status, product_name, seconds=None):
    """Write ``run`` as ``path``'s log, replacing the one from its last run."""
    target = log_path(path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    took = f" ({seconds:.2f}s)" if seconds is not None else ""
    lines = [
        f"{product_name}: {os.path.basename(path)}",
        f"Ran: {time.strftime('%Y-%m-%d %H:%M:%S')}{took}",
        f"Status: {status}",
        "",
    ]
    for level, message in run.entries:
        first, *rest = message.split("\n")
        lines.append(f"{level:<{_WIDTH}}{first}")
        lines.extend(" " * _WIDTH + line for line in rest)
    with open(target, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return target


def read(path):
    """``path``'s log as ``(level, line)`` pairs; header lines have level
    ``None``, and an entry's other lines take its level. Empty if never run."""
    try:
        with open(log_path(path), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return []
    found, level, in_body = [], None, False
    for line in text.rstrip("\n").split("\n"):
        if not in_body:
            found.append((None, line))
            in_body = not line
            continue
        head = line[:_WIDTH].rstrip()
        if head in LEVELS:
            level = head
        found.append((level, line))
    return found


def move(old_path, new_path):
    """Move ``old_path``'s log to go with the item now at ``new_path``."""
    old, new = log_path(old_path), log_path(new_path)
    if not os.path.isfile(old) or old == new:
        return
    os.makedirs(os.path.dirname(new), exist_ok=True)
    os.replace(old, new)
    _prune(os.path.dirname(old))


def delete(path):
    """Delete ``path``'s log, if it has one."""
    target = log_path(path)
    if os.path.isfile(target):
        os.remove(target)
        _prune(os.path.dirname(target))


def _prune(folder):
    """Remove the ``.logs`` folder once nothing is left in it."""
    try:
        os.rmdir(folder)
    except OSError:
        pass
