"""Animation (.anim): keyframes saved as data and put back on the same attributes.

:func:`gather` saves the time-based anim curves (``animCurveTL/TA/TU/TT``)
wired straight into the given nodes' attributes: for each animated attribute
the curve type, pre/post infinity and weighted tangents, and for each key its
time, value, tangent types, angles and weights, breakdown flag and tangent
and weight locks. Driven keys (``animCurveU*``) aren't saved (Set Driven Keys
saves those), nor are curves reaching an attribute through another node (a
pairBlend, say).

Nodes are saved by their shortest unique name and found by it again.
Times and values are in the scene's current units, as ``cmds.keyframe``
gives them (frames at the current frame rate, degrees or radians as set), and
:func:`apply` reads them back in the units of the scene it runs in. There's
no time offset: keys go back on their saved frames.

:func:`apply` skips, with a warning, the curves whose node or attribute is
missing. Then, on each other attribute in the file, it removes the existing
keys and rebuilds them. Attributes not in the file keep their keys.

The ``.anim`` extension is also used by Maya's animImportExport plug-in,
whose format is different: these files hold JSON and that plug-in can't read
them.

:data:`CHECKS` are QC checks on given nodes (not animated, unsaved
animation, duplicate names), run by the Animation Tool's QC tab and before
Scripter publishes. They change nothing.
"""

from maya import cmds

from kaiju_suite import datatypes
from kaiju_suite.core import keys
from kaiju_suite.core.checks import Check, Problem
from kaiju_suite.core.selection import short_name
from kaiju_suite.datatypes import plural, report, short

KIND = "animation"
EXTENSION = ".anim"

CURVE_TYPES = ("animCurveTL", "animCurveTA", "animCurveTU", "animCurveTT")
DRIVEN_TYPES = ("animCurveUL", "animCurveUA", "animCurveUU", "animCurveUT")


def _number(value):
    """``value`` as an int when it's whole (frame 4 rather than 4.0)."""
    return int(value) if float(value).is_integer() else value


def _inputs(node):
    """``(attribute, source node)`` for each connection into ``node``."""
    found = cmds.listConnections(
        node, source=True, destination=False, connections=True, plugs=True, skipConversionNodes=False
    ) or []
    return [(destination.split(".", 1)[1], source.split(".", 1)[0]) for destination, source in zip(found[::2], found[1::2])]


def _animated(node):
    """``(attribute, curve)`` for each time-based curve wired straight into
    ``node``, sorted by attribute so publishing is deterministic."""
    return sorted((attribute, source) for attribute, source in _inputs(node) if cmds.nodeType(source) in CURVE_TYPES)


def _record(name, plug, attribute, curve):
    # setInfinity only answers queries through the animated plug, not the curve.
    return {
        "node": name,
        "attribute": attribute,
        "type": cmds.nodeType(curve),
        "preInfinity": cmds.setInfinity(plug, query=True, preInfinite=True)[0],
        "postInfinity": cmds.setInfinity(plug, query=True, postInfinite=True)[0],
        "weightedTangents": bool(cmds.keyTangent(curve, query=True, weightedTangents=True)[0]),
        "keys": keys.read_keys(curve),
    }


def _check(records):
    """The records to apply. Those whose node or attribute is missing are
    skipped with a warning; raises, before anything changes, if a node name
    matches several nodes."""
    missing, ambiguous, kept = [], [], []
    for record in records:
        node, plug = record["node"], f"{record['node']}.{record['attribute']}"
        matches = cmds.ls(node) or []
        if not matches:
            missing.append(node)
        elif len(matches) > 1:
            ambiguous.append(node)
        elif not cmds.objExists(plug):
            missing.append(plug)
        else:
            kept.append(record)
    missing = list(dict.fromkeys(missing))
    if missing:
        nodes = any("." not in m for m in missing)
        attrs = any("." in m for m in missing)
        label = "nodes and attributes" if nodes and attrs else "nodes" if nodes else "attributes"
        datatypes.warning(f"Skipped missing {label}: {', '.join(missing)}")
    if ambiguous:
        names = ", ".join(dict.fromkeys(ambiguous))
        raise RuntimeError(f"Several nodes have these names, can't tell which to key: {names}")
    return kept


def _apply_curve(plug, record):
    cmds.cutKey(plug, clear=True)
    saved = record["keys"]
    if not saved:
        return
    for key in saved:
        cmds.setKeyframe(plug, time=key["time"], value=key["value"])
    keys.set_tangents(plug, saved, record["weightedTangents"])
    cmds.setInfinity(plug, preInfinite=record["preInfinity"], postInfinite=record["postInfinity"])


def selection_problems(selection):
    if not selection:
        return ["Nothing selected. Select the animated nodes to publish."]
    if not any(_animated(node) for node in selection):
        return ["Nothing selected has keys. Select nodes with keyframes to publish (driven keys aren't saved)."]
    return []


def gather(nodes):
    records = []
    for node in dict.fromkeys(nodes):
        name = cmds.ls(node)[0]  # shortest unique name
        records.extend(_record(name, f"{node}.{attribute}", attribute, curve) for attribute, curve in _animated(node))
    if not records:
        raise RuntimeError("Nothing selected has keys to publish.")
    return {"curves": records}


def apply(payload, info=None):
    records = _check(payload["curves"])
    for record in records:
        plug = f"{record['node']}.{record['attribute']}"
        _apply_curve(plug, record)
        report(info, f"{plug}: {plural(len(record['keys']), 'key')}")
    count = sum(len(r["keys"]) for r in records)
    return f"Keyed {plural(len(records), 'attribute')} ({plural(count, 'key')})"


def nodes(payload):
    return [r["node"] for r in payload["curves"]]


def describe(payload):
    records = payload["curves"]
    count = len({r["node"] for r in records})
    times = [k["time"] for r in records for k in r["keys"]]
    lines = [
        f"{plural(len(records), 'animated attribute')} on {plural(count, 'node')}, {plural(len(times), 'key')}"
    ]
    if times:
        lines.append(f"Frames {_number(min(times))} to {_number(max(times))}")
    return lines


def compare_view(payload):
    # Curves follow the order the nodes were selected in; by node and attribute, that order doesn't show as a change.
    return {**payload, "curves": sorted(payload["curves"], key=lambda r: (r["node"], r["attribute"]))}


# -- QC checks --------------------------------------------------------------


def _checked(nodes):
    """The nodes among ``nodes`` (long names), each once, in order."""
    return list(dict.fromkeys(cmds.ls(nodes, objectsOnly=True, long=True) or [])) if nodes else []


def _check_not_animated(nodes):
    return [Problem(f"{short(node)}: no keys", [short(node)]) for node in _checked(nodes) if not _animated(node)]


def _unsaved(node):
    """``(attribute, why)`` for each input of ``node`` that's animation
    :func:`gather` won't save: driven keys, or curves through another node."""
    found = []
    for attribute, source in _inputs(node):
        source_type = cmds.nodeType(source)
        if source_type in CURVE_TYPES:
            continue
        if source_type in DRIVEN_TYPES:
            found.append((attribute, "driven keys"))
            continue
        upstream = cmds.listConnections(source, source=True, destination=False, type="animCurve") or []
        if not upstream:
            continue
        if all(cmds.nodeType(curve) in DRIVEN_TYPES for curve in upstream):
            found.append((attribute, f"driven keys through {short(source)}"))
        else:
            found.append((attribute, f"keys through {short(source)}"))
    return sorted(set(found))


def _check_unsaved(nodes):
    problems = []
    for node in _checked(nodes):
        name = short(node)
        problems.extend(Problem(f"{name}.{attribute}: {why}", [name]) for attribute, why in _unsaved(node))
    return problems


def _check_duplicate_names(nodes):
    problems = []
    for node in _checked(nodes):
        name = short_name(node)
        same = sorted(cmds.ls(name) or [])
        if len(same) > 1:
            problems.append(Problem(f"{short(node)}: {len(same)} nodes are called {name}", same))
    return problems


CHECKS = (
    Check(
        "not_animated",
        "Not animated",
        "Nodes with no keys (time-based anim curves wired straight in); driven keys don't count.",
        _check_not_animated,
    ),
    Check(
        "unsaved",
        "Unsaved animation",
        "Animation an Animation item won't save: driven keys, and keys reaching an attribute through "
        "another node (a pairBlend, say).",
        _check_unsaved,
    ),
    Check(
        "duplicate_names",
        "Duplicate names",
        "Nodes whose name another node also has; Animation items find nodes by name.",
        _check_duplicate_names,
    ),
)
