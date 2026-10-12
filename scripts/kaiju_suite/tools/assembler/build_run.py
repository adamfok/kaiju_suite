"""The build being run: its root folder, the steps run so far and the files
they used, so a later step (an Output's build record) can say what went
into it. :func:`.logic.run_steps` opens one with :func:`running`; outside a
run :func:`current` is ``None``. No Qt here.
"""

import contextlib
from dataclasses import dataclass, field


@dataclass
class StepRecord:
    path: str
    product: str
    status: str
    entries: list  # the step's run log, ``(level, message)`` pairs


@dataclass
class BuildRun:
    root: str = None  # the build folder, if the caller named one
    steps: list = field(default_factory=list)
    inputs: list = field(default_factory=list)  # files the steps imported, in order

    def add_step(self, path, product, status, entries):
        self.steps.append(StepRecord(path, product, status, list(entries)))

    def used(self, path):
        if path not in self.inputs:
            self.inputs.append(path)


_runs = []


@contextlib.contextmanager
def running(root=None):
    """Make a :class:`BuildRun` for ``root`` current while the block runs."""
    run = BuildRun(root)
    _runs.append(run)
    try:
        yield run
    finally:
        _runs.remove(run)


def current():
    """The build being run, or ``None``."""
    return _runs[-1] if _runs else None


def used(path):
    """Note that the step being run read the file ``path``, if a build is running."""
    run = current()
    if run is not None:
        run.used(path)
