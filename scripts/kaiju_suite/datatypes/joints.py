"""Joints (.jnt): a skeleton saved as data and rebuilt as new joints.

:func:`gather` saves the given joints and every joint below them. :func:`apply`
always creates new joints and never changes existing ones: a name that's
taken gets the next free one (``spine_jnt`` → ``spine_jnt1``). A joint whose
parent isn't in the file goes under the scene's node of that name, if there
is one, otherwise under the world.

:data:`CHECKS` are QC checks on given joints and every joint below them
(rotate not zero, scale not one, end joint orient, overlapping joints,
duplicate names, unmatched mirror), run by the Joint Tool's QC tab and
before Builder publishes. They change nothing.
"""

import math

from maya import cmds

from kaiju_suite.core.checks import Check, Problem
from kaiju_suite.core.naming import opposite_name
from kaiju_suite.core.selection import short_name
from kaiju_suite.datatypes import create_node, node_path, outside_parents, parent_of, short

KIND = "joints"
EXTENSION = ".jnt"

_VECTORS = ("translate", "rotate", "jointOrient", "scale", "preferredAngle")
_INTS = ("rotateOrder", "side", "type")


def _joints_under(selection):
    """The selected joints and their descendant joints, parents first, each
    root's joints together, roots in selection order."""
    selected = cmds.ls(selection, type="joint", long=True) or []
    members = set()
    for joint in selected:
        members.add(joint)
        members.update(cmds.listRelatives(joint, allDescendents=True, type="joint", fullPath=True) or [])

    ordered = []

    def walk(joint):
        ordered.append(joint)
        for child in cmds.listRelatives(joint, children=True, type="joint", fullPath=True) or []:
            walk(child)

    for joint in dict.fromkeys(selected):
        if parent_of(joint) not in members:
            walk(joint)
    return ordered


def _record(path, index_of):
    parent = parent_of(path)
    record = {
        "name": short_name(path),
        "parent": short_name(parent) if parent else None,
        "parent_index": index_of.get(parent),
    }
    for attr in _VECTORS:
        record[attr] = list(cmds.getAttr(f"{path}.{attr}")[0])
    for attr in _INTS:
        record[attr] = int(cmds.getAttr(f"{path}.{attr}"))
    record["segmentScaleCompensate"] = bool(cmds.getAttr(f"{path}.segmentScaleCompensate"))
    record["radius"] = float(cmds.getAttr(f"{path}.radius"))
    record["otherType"] = cmds.getAttr(f"{path}.otherType") or ""
    return record


def _set_values(path, record):
    for attr in _VECTORS:
        cmds.setAttr(f"{path}.{attr}", *record[attr])
    for attr in _INTS:
        cmds.setAttr(f"{path}.{attr}", record[attr])
    cmds.setAttr(f"{path}.segmentScaleCompensate", record["segmentScaleCompensate"])
    cmds.setAttr(f"{path}.radius", record["radius"])
    cmds.setAttr(f"{path}.otherType", record["otherType"], type="string")


def selection_problems(selection):
    if not selection:
        return ["Nothing selected. Select the root joints to publish."]
    if not cmds.ls(selection, type="joint"):
        return ["No joints selected. Select the root joints to publish."]
    return []


def gather(nodes):
    paths = _joints_under(nodes)
    if not paths:
        raise RuntimeError("No joints selected to publish.")
    index_of = {}
    records = []
    for path in paths:
        records.append(_record(path, index_of))
        index_of[path] = len(records) - 1
    return {"joints": records}


def apply(payload, info=None):
    records = payload["joints"]
    outside = outside_parents(records)
    uuids, renamed = [], []
    for record in records:
        index = record["parent_index"]
        parent = node_path(uuids[index]) if index is not None else outside.get(record["parent"])
        uuid = create_node("joint", record["name"], parent)
        path = node_path(uuid)
        _set_values(path, record)
        uuids.append(uuid)
        if short_name(path) != record["name"]:
            renamed.append(f"{record['name']} → {short_name(path)}")
    message = f"Created {len(records)} joint{'s' if len(records) != 1 else ''}"
    if renamed:
        message += f" (names taken, renamed: {', '.join(renamed)})"
    return message


def nodes(payload):
    return [r["name"] for r in payload["joints"]]


def describe(payload):
    records = payload["joints"]
    roots = [r["name"] for r in records if r["parent_index"] is None]
    return [f"{len(records)} joint{'s' if len(records) != 1 else ''}", f"Roots: {', '.join(roots)}"]


def compare_view(payload):
    # parent_index shifts whenever joints are added or removed; the parent's name says enough.
    return {**payload, "joints": [{k: v for k, v in r.items() if k != "parent_index"} for r in payload["joints"]]}


# -- QC checks --------------------------------------------------------------

# How far from zero (or one) a rotate, scale or joint orient value may be.
_VALUE_TOLERANCE = 1e-4


def vector_text(values):
    """``(10, 0, -5.5)``: values rounded to 3 decimals, without trailing zeros."""
    return "(" + ", ".join(f"{round(v, 3) + 0:g}" for v in values) + ")"


def _checked(nodes):
    """The joints among ``nodes`` and every joint below them, long names."""
    return _joints_under(cmds.ls(nodes, type="joint", long=True) or []) if nodes else []


def _off(values, target):
    return any(abs(v - target) > _VALUE_TOLERANCE for v in values)


def _value_check(attr, target, what):
    def run(nodes):
        problems = []
        for joint in _checked(nodes):
            values = cmds.getAttr(f"{joint}.{attr}")[0]
            if _off(values, target):
                problems.append(Problem(f"{short(joint)}: {what} {vector_text(values)}", [short(joint)]))
        return problems

    return run


def _check_end_orient(nodes):
    problems = []
    for joint in _checked(nodes):
        if cmds.listRelatives(joint, children=True, type="joint"):
            continue
        values = cmds.getAttr(f"{joint}.jointOrient")[0]
        if _off(values, 0):
            problems.append(Problem(f"{short(joint)}: end joint has joint orient {vector_text(values)}", [short(joint)]))
    return problems


def _position(node):
    return cmds.xform(node, query=True, worldSpace=True, translation=True)


def _check_overlapping(nodes, tolerance=0.001):
    problems = []
    for joint in _checked(nodes):
        parent = parent_of(joint)
        if not parent or cmds.nodeType(parent) != "joint":
            continue
        if math.dist(_position(joint), _position(parent)) <= tolerance:
            problems.append(
                Problem(f"{short(joint)}: at the same position as {short(parent)}", [short(joint), short(parent)])
            )
    return problems


def _check_duplicate_names(nodes):
    problems = []
    for joint in _checked(nodes):
        name = short_name(joint)
        same = sorted(cmds.ls(name) or [])
        if len(same) > 1:
            problems.append(Problem(f"{short(joint)}: {len(same)} nodes are called {name}", same))
    return problems


def _check_mirror(nodes, tolerance=0.01):
    problems, seen = [], set()
    for joint in _checked(nodes):
        name = short_name(joint)
        opposite = opposite_name(name)
        if opposite is None or joint in seen:
            continue
        found = cmds.ls(opposite, type="joint", long=True) or []
        if not found:
            problems.append(Problem(f"{short(joint)}: no {opposite}", [short(joint)]))
            continue
        seen.update((joint, found[0]))
        x, y, z = _position(joint)
        off = math.dist((-x, y, z), _position(found[0]))
        if off > tolerance:
            problems.append(
                Problem(
                    f"{short(joint)}: {short(found[0])} isn't at its mirrored position (off by {off:.3g})",
                    [short(joint), short(found[0])],
                )
            )
    return problems


CHECKS = (
    Check(
        "rotate",
        "Rotate not zero",
        "Joints with rotate values: a joint's orientation belongs in its joint orient.",
        _value_check("rotate", 0, "rotate is"),
    ),
    Check("scale", "Scale not one", "Joints whose scale isn't 1.", _value_check("scale", 1, "scale is")),
    Check(
        "end_orient",
        "End joint orient",
        "End joints (no child joint) with a joint orient; they usually take their parent's orientation.",
        _check_end_orient,
    ),
    Check(
        "overlapping",
        "Overlapping joints",
        "Joints at the same position as their parent joint, give or take the tolerance.",
        _check_overlapping,
        {"tolerance": 0.001},
    ),
    Check(
        "duplicate_names",
        "Duplicate names",
        "Joints whose name another node also has; Joints items and skins find joints by name.",
        _check_duplicate_names,
    ),
    Check(
        "mirror",
        "Unmatched mirror",
        "Left or right joints whose other-side joint is missing, or isn't at the mirrored position across X.",
        _check_mirror,
        {"tolerance": 0.01},
    ),
)
