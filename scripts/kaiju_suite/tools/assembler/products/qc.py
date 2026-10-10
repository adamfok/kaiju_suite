"""QC (.qc): a build step that looks for rig problems and changes nothing.

The file stores which checks from :mod:`kaiju_suite.core.checks` are on and
their options (e.g. the naming pattern), as a Kaiju data file::

    {"kaiju": "qc", "format": 1, "data": {"checks": {"naming": {"enabled": true, ...}, ...}}}

An empty file runs every check with its defaults. **Run** runs the turned-on
checks and logs each one's findings as a run-log warning, so the step ends
with the Warning status and the build goes on. Double-click opens a window
with a checkbox per check (hover one for what it looks for); a check with
options has a "?" button on its row to edit them (Naming: its pattern), and
Run and Show Log buttons sit at the bottom.
**Publish** saves the settings as they are as the next version.
"""

import os

from maya import cmds

from kaiju_suite.core import checks, datafile
from kaiju_suite.tools.assembler import runlog, versions
from kaiju_suite.tools.assembler.products import Action, Creator, Panel, Product, Toggle, is_empty, new_path

EXTENSION = ".qc"
KIND = "qc"


def create_qc(directory, name):
    """Create a QC item with every check turned on and return its path."""
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
    def fn(on):
        _set(path, check.key, enabled=bool(on))
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


class QCProduct(Product):
    name = "QC"
    extensions = (EXTENSION,)
    order = 145
    menu_slot = (6, 0)
    runnable = True
    versioned = True
    creators = (Creator("QC", lambda directory, name, _ext: create_qc(directory, name)),)

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
        toggles = []
        for check in checks.CHECKS:
            tooltip, edit = check.description, None
            if "pattern" in check.options:
                tooltip += f"\nPattern: {settings[check.key]['pattern']}"
                edit = Action(f"Set {check.label} Pattern...", _set_pattern(path, check))
            toggles.append(Toggle(check.label, settings[check.key]["enabled"], _toggle(path, check), tooltip, edit))
        return Panel([versions.summary(path)], [], toggles, run_buttons=True)


PRODUCT = QCProduct()
