"""Headless build: build an Assembler folder from mayapy, with no UI.

For batch rebuilds and automatic rig checks::

    mayapy -m kaiju_suite.tools.assembler.headless <build_folder> [--new-scene] [--save out.ma]

prints each step's status and messages and exits 0 if every step ran, 1 if
one failed (the build stops there, as Run All does) and 2 if the folder
doesn't exist. From Python (already inside Maya or ``maya.standalone``),
:func:`build` does the same and returns a :class:`BuildResult`.

The steps run through :func:`.logic.run_steps`, exactly as Run All runs
them, so each step's log is saved next to it as usual. Only run as
``__main__`` does this start ``maya.standalone``. No Qt here.
"""

import argparse
import os
import sys
from dataclasses import dataclass, field

# Status of the steps after a failure, which aren't run.
NOT_RUN = "not run"


@dataclass
class StepResult:
    path: str
    name: str  # relative to the build folder, with "/" separators
    status: str = NOT_RUN
    messages: list = field(default_factory=list)  # (level, text) pairs from the step's log


@dataclass
class BuildResult:
    folder: str
    steps: list = field(default_factory=list)
    saved: str = None  # the scene file written, if any

    @property
    def ok(self):
        """Whether no step failed (warnings are fine)."""
        from kaiju_suite.tools.assembler import logic

        return all(step.status != logic.ERROR for step in self.steps)


def build(folder, new_scene=True, save=None):
    """Build ``folder`` like Run All and return a :class:`BuildResult`.

    ``new_scene`` starts from an empty scene first (discarding the current
    one without asking). If ``save`` is a ``.ma`` or ``.mb`` path, the scene
    is saved there after a build with no failed step. A failed step doesn't
    raise: its status is ``error`` and the steps after it are ``not run``.
    """
    from maya import cmds

    from kaiju_suite.tools.assembler import logic

    folder = os.path.normpath(folder)
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"Folder not found: {folder}")
    if new_scene:
        cmds.file(new=True, force=True)

    paths = logic.collect_steps(folder)
    result = BuildResult(folder, [StepResult(p, _relative(p, folder)) for p in paths])
    by_path = {step.path: step for step in result.steps}

    def on_status(path, status):
        by_path[path].status = status

    try:
        logic.run_steps(paths, on_status=on_status)
    except logic.StepError:
        pass
    for step in result.steps:
        if step.status != NOT_RUN:
            step.messages = _messages(step.path)

    if save and result.ok:
        result.saved = save_scene(save)
    return result


def save_scene(path):
    """Save the current scene as ``path`` (``.mb`` binary, else ascii)."""
    from maya import cmds

    file_type = "mayaBinary" if path.lower().endswith(".mb") else "mayaAscii"
    path = os.path.abspath(path)
    cmds.file(rename=path)
    cmds.file(save=True, force=True, type=file_type)
    return path


def _relative(path, folder):
    return os.path.relpath(path, folder).replace(os.sep, "/")


def _messages(path):
    """``path``'s last run log as ``(level, text)`` entries."""
    from kaiju_suite.tools.assembler import runlog

    width = len(runlog.WARNING) + 1  # see runlog.save
    entries = []
    for level, line in runlog.read(path):
        if level is None:
            continue
        if line[:width].rstrip() in runlog.LEVELS:
            entries.append([level, line[width:]])
        elif entries:
            entries[-1][1] += "\n" + line[width:]
    return [tuple(e) for e in entries]


# -- command line ---------------------------------------------------------------


def report(result):
    """``result`` as text: one line per step, then its messages, indented."""
    lines = [f"Assembler build: {result.folder}"]
    for step in result.steps:
        lines.append(f"[{step.status.upper()}] {step.name}")
        for level, text in step.messages:
            for i, line in enumerate(text.split("\n")):
                lines.append(f"    {level + ':' if i == 0 else '':<9}{line}")
    lines.append(f"{len(result.steps)} steps: {'OK' if result.ok else 'FAILED'}")
    if result.saved:
        lines.append(f"Saved: {result.saved}")
    return "\n".join(lines)


def main(argv=None):
    """Command-line entry point; returns the exit code. Needs Maya running
    (``__main__`` starts ``maya.standalone`` first)."""
    parser = argparse.ArgumentParser(
        prog="mayapy -m kaiju_suite.tools.assembler.headless",
        description="Build an Assembler folder with no UI.",
    )
    parser.add_argument("folder", help="the Assembler folder to build")
    parser.add_argument("--new-scene", action="store_true", help="start from an empty scene")
    parser.add_argument("--save", metavar="FILE", help="save the scene here (.ma or .mb) if no step failed")
    args = parser.parse_args(argv)

    try:
        result = build(args.folder, new_scene=args.new_scene, save=args.save)
    except FileNotFoundError as e:
        print(e)
        return 2
    print(report(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    import maya.standalone

    maya.standalone.initialize(name="python")
    # Startup scripts (userSetup.py, plug-ins) run in __main__, which is this
    # module's namespace when run with -m, and can overwrite its names. Use
    # the module imported under its real name instead.
    import sys as _sys

    from kaiju_suite.tools.assembler import headless as _headless

    try:
        _code = _headless.main()
    finally:
        maya.standalone.uninitialize()
    _sys.exit(_code)
