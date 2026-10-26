"""Scene checks: look for common rig problems and report them, changing nothing.

Each :class:`Check` returns a list of problem messages, one per node, each
starting with the node's name (e.g. ``pCube1: doesn't match ...``); an empty
list means it found nothing. A message can be a :class:`Problem`, which also says what to select
to see it (e.g. the vertices whose weights are off). No Qt here.

The settings functions take another list of checks too (``checks=``), e.g.
:data:`kaiju_suite.datatypes.skin.CHECKS`, whose checks take the nodes to
look at: ``run(settings, skin.CHECKS, nodes=[...])``. A tool's QC tab keeps
its settings with :func:`saved_settings` and :func:`save_setting`.

Settings say which checks to run and with what options, keyed by check::

    {"naming": {"enabled": True, "pattern": "..."}, "history": {"enabled": False}}

Missing checks and options take their defaults (see :func:`complete`).
"""

import re
from dataclasses import dataclass, field

from maya import cmds

from kaiju_suite.core import settings as user_settings

# Parts of letters and digits joined by underscores, at least two of them
# (``L_arm_ctrl``, ``body_geo``): flags Maya's defaults (``pCube1``, ``joint1``).
DEFAULT_PATTERN = r"^[A-Za-z][A-Za-z0-9]*(_[A-Za-z0-9]+)+$"

TOLERANCE = 1e-4

_IDENTITY = {"translate": (0, 0, 0), "rotate": (0, 0, 0), "scale": (1, 1, 1), "shear": (0, 0, 0)}

# Shape types whose transforms should be frozen, and whose history is left over.
_SHAPE_TYPES = ("mesh", "nurbsCurve")

# Nodes in a shape's history that aren't modeling history (deformers and their plumbing).
_NOT_HISTORY = ("geometryFilter", "tweak", "groupParts", "groupId", "shadingEngine", "objectSet", "dagPose")

_UNKNOWN_TYPES = ("unknown", "unknownDag", "unknownTransform")


@dataclass(frozen=True)
class Check:
    """One check: ``fn(**options)`` returns problem messages.

    ``options`` holds each option's default; :meth:`run` fills in the ones
    not given. ``fix(nodes)``, if given, repairs what the check finds on
    ``nodes``. ``publish=False`` leaves the check out of the QC that runs
    before Builder publishes (it still runs in the tool).
    """

    key: str
    label: str
    description: str
    fn: object
    options: dict = field(default_factory=dict)
    fix: object = None
    publish: bool = True

    def run(self, **options):
        return self.fn(**{**self.options, **options})


class Problem(str):
    """A problem message that also knows what to select to see it: nodes or
    components, e.g. ``["body_geo.vtx[0:4]"]``. Reads as plain text anywhere
    a message is expected."""

    def __new__(cls, message, select=()):
        problem = super().__new__(cls, message)
        problem.select = list(select)
        return problem


def selection_of(problem):
    """What to select to see ``problem``: its ``select`` if it's a
    :class:`Problem`, else nothing."""
    return list(getattr(problem, "select", []))


def select_problem(problem):
    """Select what ``problem`` points at (see :func:`selection_of`), leaving
    out what's no longer in the scene. Returns what was selected."""
    found = [name for name in selection_of(problem) if cmds.objExists(name)]
    if found:
        cmds.select(found, replace=True)
    else:
        cmds.select(clear=True)
    return cmds.ls(selection=True) if found else []


# -- helpers ----------------------------------------------------------------


def _display(node):
    """The shortest unique name of ``node``."""
    found = cmds.ls(node)
    return found[0] if found else node


def _is_startup_camera(transform):
    shapes = cmds.listRelatives(transform, shapes=True, type="camera", fullPath=True) or []
    return any(cmds.camera(shape, query=True, startupCamera=True) for shape in shapes)


def _transforms():
    """Every DAG transform (joints too) except Maya's startup cameras, by long name."""
    return [t for t in cmds.ls(type="transform", long=True) or [] if not _is_startup_camera(t)]


def _shapes(transform):
    """``transform``'s own mesh and curve shapes, intermediates left out."""
    shapes = cmds.listRelatives(transform, shapes=True, type=_SHAPE_TYPES, fullPath=True, noIntermediate=True)
    return shapes or []


def _with_shapes():
    return [t for t in _transforms() if _shapes(t)]


# -- the checks -------------------------------------------------------------


def _naming(pattern=DEFAULT_PATTERN):
    try:
        regex = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Not a valid naming pattern {pattern!r}: {e}") from e
    problems = []
    for node in _transforms():
        short = node.rsplit("|", 1)[-1].rsplit(":", 1)[-1]
        if not regex.search(short):
            problems.append(f"{_display(node)}: doesn't match {pattern}")
    return problems


def _unfrozen():
    problems = []
    for node in _with_shapes():
        off = [
            attr
            for attr, identity in _IDENTITY.items()
            if any(abs(v - i) > TOLERANCE for v, i in zip(cmds.getAttr(f"{node}.{attr}")[0], identity))
        ]
        if len(off) == 1:
            problems.append(f"{_display(node)}: {off[0]} not at its default")
        elif off:
            problems.append(f"{_display(node)}: {', '.join(off)} not at their defaults")
    return problems


def _history():
    problems = []
    for node in _with_shapes():
        found = []
        for shape in _shapes(node):
            for item in cmds.listHistory(shape, pruneDagObjects=True) or []:
                if item not in found and not any(cmds.objectType(item, isAType=kind) for kind in _NOT_HISTORY):
                    found.append(item)
        if found:
            problems.append(f"{_display(node)}: {', '.join(found)}")
    return problems


def _unknown():
    nodes = cmds.ls(type=_UNKNOWN_TYPES) or []
    return [f"{node} ({cmds.nodeType(node)})" for node in nodes]


CHECKS = (
    Check(
        "naming",
        "Naming",
        "Transforms and joints whose name (without namespace) doesn't match the pattern.",
        _naming,
        {"pattern": DEFAULT_PATTERN},
    ),
    Check(
        "transforms",
        "Unfrozen transforms",
        "Controls and meshes with translate, rotate, scale or shear not at their defaults.",
        _unfrozen,
    ),
    Check(
        "history",
        "Construction history",
        "Meshes and curves with modeling history left on them (deformers don't count).",
        _history,
    ),
    Check("unknown", "Unknown nodes", "Nodes of an unknown type, e.g. from a plug-in that isn't loaded.", _unknown),
)


def get(key, checks=None):
    """The check with ``key`` in ``checks`` (default :data:`CHECKS`); raises
    ``LookupError`` if there's none."""
    for check in checks or CHECKS:
        if check.key == key:
            return check
    raise LookupError(f"No check {key!r}")


# -- settings ---------------------------------------------------------------


def defaults(checks=None):
    """Settings that turn every check on with its default options."""
    return {check.key: {"enabled": True, **check.options} for check in checks or CHECKS}


def complete(settings, checks=None):
    """``settings`` with missing checks and options filled in from :func:`defaults`."""
    result = defaults(checks)
    for key, values in (settings or {}).items():
        result.setdefault(key, {}).update(values)
    return result


def _number_problem(key, option, value, default):
    whole = isinstance(default, int)
    if isinstance(value, bool) or not isinstance(value, int if whole else (int, float)):
        return f"{key}: {option} must be {'a whole number' if whole else 'a number'}, not {value!r}"
    if value < 0:
        return f"{key}: {option} can't be negative"
    return None


def settings_problems(settings, checks=None):
    """What's wrong with ``settings``, as messages. Empty if they can be run."""
    checks = checks or CHECKS
    if not isinstance(settings, dict):
        return [f"checks must be an object of check settings, not {settings!r}"]
    problems = []
    for key, values in settings.items():
        try:
            check = get(key, checks)
        except LookupError:
            problems.append(f"no check {key!r}; use one of {', '.join(c.key for c in checks)}")
            continue
        if not isinstance(values, dict):
            problems.append(f"{key} must be an object, not {values!r}")
            continue
        for option, value in values.items():
            if option == "enabled":
                if not isinstance(value, bool):
                    problems.append(f"{key}: enabled must be true or false")
            elif option not in check.options:
                problems.append(f"{key}: unknown option {option!r}")
            elif option == "pattern":
                if not isinstance(value, str):
                    problems.append(f"{key}: pattern must be text, not {value!r}")
                else:
                    try:
                        re.compile(value)
                    except re.error as e:
                        problems.append(f"{key}: pattern isn't a valid regular expression: {e}")
            elif isinstance(check.options[option], (int, float)):
                problem = _number_problem(key, option, value, check.options[option])
                if problem:
                    problems.append(problem)
    return problems


def run(settings=None, checks=None, **inputs):
    """Run the turned-on checks in ``settings`` (all, if ``None``), in order,
    passing each ``inputs`` (e.g. ``nodes=``) along with its options.

    Returns ``(check, problems)`` pairs, one per check run. Changes nothing.
    """
    checks = checks or CHECKS
    settings = complete(settings, checks)
    found = []
    for check in checks:
        values = dict(settings[check.key])
        if not values.pop("enabled", True):
            continue
        found.append((check, check.run(**inputs, **values)))
    return found


# -- saved settings (a tool's QC tab) ------------------------------------------


def _setting_name(key, option):
    return f"qc_{key}_{option}"


def saved_settings(tool, checks=None):
    """The QC settings ``tool`` saved with :func:`save_setting` (per user, in
    optionVars), each value read back as its default's type; defaults for
    the rest."""
    result = defaults(checks)
    for key, values in result.items():
        for option, default in values.items():
            value = user_settings.get(tool, _setting_name(key, option))
            if value is not None:
                values[option] = type(default)(value)
    return result


def save_setting(tool, key, option, value):
    """Save one QC option of ``tool`` (``"enabled"`` turns the check on or off)."""
    user_settings.set(tool, _setting_name(key, option), value)
