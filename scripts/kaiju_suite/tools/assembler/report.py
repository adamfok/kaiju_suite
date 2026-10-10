"""Build report: each step's status, time taken and log, after a run.

A :class:`Recorder` is passed to :func:`.logic.run_steps` as its
``on_status`` callback; it times each step from its ``running`` call to its
result. :attr:`Recorder.results` then gives one :class:`StepResult` per
step, steps never reached after a failure as :data:`SKIPPED`, and
:func:`summary` turns them into plain text. No Qt here.
"""

import dataclasses
import os
import time

from kaiju_suite.tools.assembler import logic, runlog

OK = "OK"
WARNING = "Warning"
ERROR = "Error"
SKIPPED = "Skipped"
STATUSES = (OK, WARNING, ERROR, SKIPPED)

_FROM_RUN = {logic.SUCCESS: OK, logic.WARNING: WARNING, logic.ERROR: ERROR}


@dataclasses.dataclass
class StepResult:
    path: str
    status: str
    seconds: float = None  # None if the step didn't run

    @property
    def name(self):
        return os.path.basename(self.path)

    @property
    def log_path(self):
        return runlog.log_path(self.path)

    @property
    def has_log(self):
        return self.status != SKIPPED and runlog.exists(self.path)


class Recorder:
    """``on_status`` callback for :func:`.logic.run_steps` that records each
    step's result and time. ``forward(path, status)``, if given, is called
    with every status too (the window colors steps with it)."""

    def __init__(self, paths, forward=None):
        self._paths = list(paths)
        self._forward = forward
        self._started = {}
        self._done = {}

    def __call__(self, path, status):
        if status == logic.RUNNING:
            self._started[path] = time.perf_counter()
        else:
            start = self._started.get(path, time.perf_counter())
            self._done[path] = StepResult(path, _FROM_RUN.get(status, ERROR), time.perf_counter() - start)
        if self._forward:
            self._forward(path, status)

    @property
    def results(self):
        """One :class:`StepResult` per step, in run order. A step that started
        but never finished counts as an error; one never started, skipped."""
        found = []
        for path in self._paths:
            if path in self._done:
                found.append(self._done[path])
            elif path in self._started:
                found.append(StepResult(path, ERROR, time.perf_counter() - self._started[path]))
            else:
                found.append(StepResult(path, SKIPPED))
        return found


def total_seconds(results):
    return sum(r.seconds for r in results if r.seconds is not None)


def counts(results):
    """How many steps ended with each status."""
    found = dict.fromkeys(STATUSES, 0)
    for r in results:
        found[r.status] += 1
    return found


def format_seconds(seconds):
    if seconds is None:
        return "-"
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes)}m {rest:.1f}s"


def count_line(results):
    """E.g. ``3 OK, 1 Warning, 0 Error, 0 Skipped``."""
    return ", ".join(f"{n} {status}" for status, n in counts(results).items())


def summary(results):
    """The report as plain text: one line per step, then the totals."""
    if not results:
        return "No steps were run."
    width = max(len(r.name) for r in results)
    lines = [f"{r.name:<{width}}  {r.status:<7}  {format_seconds(r.seconds):>9}" for r in results]
    lines += ["", count_line(results), f"Total: {format_seconds(total_seconds(results))}"]
    return "\n".join(lines)
