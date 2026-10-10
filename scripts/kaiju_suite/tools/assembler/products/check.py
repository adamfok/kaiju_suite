"""Checks (.chk): a build step that looks for rig problems and changes nothing.

The file stores which checks from :mod:`kaiju_suite.core.checks` are on and
their options (e.g. the naming pattern), as a Kaiju data file::

    {"kaiju": "check", "format": 1, "data": {"checks": {"naming": {"enabled": true, ...}, ...}}}

An empty file runs every check with its defaults. **Run** runs the turned-on
checks and logs each one's findings as a run-log warning, so the step ends
with the Warning status and the build goes on. Double-click opens a window
that lists the checks and turns them on or off, or sets the naming pattern.
**Publish** saves the settings as they are as the next version.
"""

import os

from maya import cmds

from kaiju_suite.core import checks, datafile
from kaiju_suite.tools.assembler import runlog, versions
from kaiju_suite.tools.assembler.products import Action, Creator, Panel, Product, is_empty, new_path

EXTENSION = ".chk"
KIND = "check"


def create_check(directory, name):
    """Create a Check item with every check turned on and return its path."""
    path = new_path(directory, name, EXTENSION)
    return write_settings(path, checks.defaults())


def read_settings(path):
    """The settings stored at ``path``, with missing ones filled in from the
    defaults. Raises ``ValueError`` if the file or its settings are wrong."""
    if is_empty(path):
        return checks.defaults()
    payload = datafile.read(path, KIND)
    settings = payload.get("checks", {}) if isinstance(payload, dict) else payload
    problems = checks.settings_problems(settings)
    if problems:
        raise ValueError(f"{os.path.basename(path)}: {'; '.join(problems)}")
    return checks.complete(settings)


def write_settings(path, settings):
    """Store ``settings`` at ``path``, after checking them; returns ``path``."""
    problems = checks.settings_problems(settings)
    if problems:
        raise ValueError("; ".join(problems))
    return datafile.write(path, KIND, {"checks": checks.complete(settings)})


def ask_pattern(current):
    """Ask for a naming pattern, starting from ``current``. Returns the new
    pattern, or ``None`` if cancelled. GUI Maya only."""
    answer = cmds.promptDialog(
        title="Naming Pattern",
        message="Names (without namespace) must match this regular expression:",
        text=current,
        button=["OK", "Cancel"],
        defaultButton="OK",
        cancelButton="Cancel",
        dismissString="Cancel",
    )
    if answer != "OK":
        return None
    return cmds.promptDialog(query=True, text=True)


def _set(path, key, **values):
    settings = read_settings(path)
    settings[key].update(values)
    write_settings(path, settings)


def _toggle(path, check):
    def fn():
        on = not read_settings(path)[check.key]["enabled"]
        _set(path, check.key, enabled=on)
        return f"Turned {'on' if on else 'off'} {check.label} in {os.path.basename(path)}"

    return fn


def _set_pattern(path, check):
    def fn():
        pattern = ask_pattern(read_settings(path)[check.key]["pattern"])
        if pattern is None:
            return None
        _set(path, check.key, pattern=pattern)
        return f"Set the naming pattern of {os.path.basename(path)} to {pattern}"

    return fn


class CheckProduct(Product):
    name = "Check"
    extensions = (EXTENSION,)
    order = 145
    menu_slot = (6, 0)
    runnable = True
    versioned = True
    creators = (Creator("Check", lambda directory, name, _ext: create_check(directory, name)),)

    def run(self, path):
        results = checks.run(read_settings(path))
        if not results:
            return "No checks turned on"
        total = 0
        for check, problems in results:
            if problems:
                total += len(problems)
                runlog.warning(f"{check.label}: {len(problems)} found\n" + "\n".join(problems))
        found = f"{total} problems found" if total else "no problems found"
        return f"Ran {len(results)} checks: {found}"

    def to_plan(self, path):
        return {"checks": read_settings(path)}

    def plan_problems(self, item):
        return checks.settings_problems(item.get("checks", {}))

    def from_plan(self, path, item):
        write_settings(path, item.get("checks", {}))

    def panel(self, path):
        try:
            settings = read_settings(path)
        except ValueError as e:
            return Panel([str(e)], [])
        info, actions = [], []
        for check in checks.CHECKS:
            on = settings[check.key]["enabled"]
            info.append(f"{check.label}: {'on' if on else 'off'} - {check.description}")
            actions.append(Action(f"Turn {'Off' if on else 'On'} {check.label}", _toggle(path, check)))
            if "pattern" in check.options:
                info.append(f"    Pattern: {settings[check.key]['pattern']}")
                actions.append(Action(f"Set {check.label} Pattern...", _set_pattern(path, check)))
        info.append(versions.summary(path))
        return Panel(info, actions)


PRODUCT = CheckProduct()
