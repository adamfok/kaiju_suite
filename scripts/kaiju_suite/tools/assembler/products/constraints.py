"""Constraints (.cnst): parent, point, orient, scale, aim and pole vector
constraints saved as data and recreated by name.

Publish saves every constraint driving the selected nodes (or the selected
constraint nodes themselves): its targets and their weights, offsets, skipped
axes, interp type and, for aim constraints, the aim, up and world up settings.
Run finds the constrained nodes and targets by name and replaces a constraint
of the same name. Constraints whose nodes are missing are skipped with a
warning; ambiguous names, and names taken by other nodes, stop the run before
anything changes.
"""

from maya import cmds

from kaiju_suite.core.selection import short_name
from kaiju_suite.tools.assembler import data, runlog

# Constraint type -> (label, the channels it drives as {channel: output attr}).
_TYPES = {
    "parentConstraint": ("parent", {"translate": "constraintTranslate", "rotate": "constraintRotate"}),
    "pointConstraint": ("point", {"translate": "constraintTranslate"}),
    "orientConstraint": ("orient", {"rotate": "constraintRotate"}),
    "scaleConstraint": ("scale", {"scale": "constraintScale"}),
    "aimConstraint": ("aim", {"rotate": "constraintRotate"}),
    "poleVectorConstraint": ("pole vector", {}),
}
_WITH_OFFSET = ("pointConstraint", "orientConstraint", "scaleConstraint", "aimConstraint")
_WITH_INTERP = ("parentConstraint", "orientConstraint")
_AIM_VECTORS = ("aimVector", "upVector", "worldUpVector")
# The aimConstraint command's worldUpType keywords, by the attribute's value.
_WORLD_UP_TYPES = ("scene", "object", "objectrotation", "vector", "none")
_TARGET_OFFSETS = ("targetOffsetTranslate", "targetOffsetRotate")
_DIGITS = 6


def _round(value):
    return round(float(value), _DIGITS)


def _vector(node, attr):
    return [_round(v) for v in cmds.getAttr(f"{node}.{attr}")[0]]


def _long(name):
    return cmds.ls(name, long=True)[0]


def _command(kind):
    return getattr(cmds, kind)


def _driven(constraint):
    """The long name of the node ``constraint`` drives."""
    found = cmds.listConnections(f"{constraint}.constraintParentInverseMatrix", source=True, destination=False)
    if found:
        return _long(found[0])
    return data.parent_of(_long(constraint))


def _constraints_on(node):
    """The supported constraints driving ``node`` (long names), long names."""
    found = cmds.listConnections(f"{node}.parentInverseMatrix", source=False, destination=True) or []
    found = [_long(n) for n in found] + (cmds.listRelatives(node, children=True, fullPath=True) or [])
    node = _long(node)
    return [c for c in dict.fromkeys(found) if cmds.nodeType(c) in _TYPES and _driven(c) == node]


def _selected_constraints(selection):
    """The constraints to publish from ``selection``, and the selected nodes with none."""
    found, without = [], []
    for node in cmds.ls(selection, long=True) or []:
        if cmds.nodeType(node) in _TYPES:
            found.append(node)
            continue
        on = _constraints_on(node)
        if not on:
            without.append(short_name(node))
        found.extend(on)
    return list(dict.fromkeys(found)), without


def _record(constraint):
    kind = cmds.nodeType(constraint)
    command = _command(kind)
    targets = command(constraint, query=True, targetList=True) or []
    aliases = command(constraint, query=True, weightAliasList=True) or []
    indices = cmds.getAttr(f"{constraint}.target", multiIndices=True) or []
    record = {
        "name": short_name(constraint),
        "type": kind,
        "driven": short_name(_driven(constraint)),
        "targets": [],
    }
    for target, alias, index in zip(targets, aliases, indices):
        entry = {"name": short_name(target), "weight": _round(cmds.getAttr(f"{constraint}.{alias}"))}
        if kind == "parentConstraint":
            for attr in _TARGET_OFFSETS:
                entry[attr] = _vector(constraint, f"target[{index}].{attr}")
        record["targets"].append(entry)

    channels = _TYPES[kind][1]
    if channels:
        record["skip"] = {
            channel: [
                axis.lower()
                for axis in "XYZ"
                if not cmds.listConnections(f"{constraint}.{output}{axis}", source=False, destination=True)
            ]
            for channel, output in channels.items()
        }
    if kind in _WITH_OFFSET:
        record["offset"] = _vector(constraint, "offset")
    if kind in _WITH_INTERP:
        record["interpType"] = cmds.getAttr(f"{constraint}.interpType")
    if kind == "aimConstraint":
        for attr in _AIM_VECTORS:
            record[attr] = _vector(constraint, attr)
        record["worldUpType"] = _WORLD_UP_TYPES[cmds.getAttr(f"{constraint}.worldUpType")]
        up = cmds.listConnections(f"{constraint}.worldUpMatrix", source=True, destination=False)
        record["worldUpObject"] = short_name(_long(up[0])) if up else None
    return record


def _node_names(record):
    """Every scene node ``record`` needs, the constrained node first."""
    names = [record["driven"]] + [t["name"] for t in record["targets"]]
    if record.get("worldUpObject"):
        names.append(record["worldUpObject"])
    return list(dict.fromkeys(names))


def _skip_missing(records):
    """The records whose nodes are all in the scene; one warning names the rest."""
    kept, skipped = [], []
    for record in records:
        missing = [n for n in _node_names(record) if not cmds.objExists(n)]
        if missing:
            skipped.append(f"{record['name']} ({', '.join(missing)})")
        else:
            kept.append(record)
    if skipped:
        runlog.warning(f"Skipped constraints with missing nodes: {', '.join(skipped)}")
    return kept


def _check(records):
    """Raise, before anything changes, if a name matches several nodes, a
    constraint's name is taken by another node, or a constrained node already
    has another constraint of the same type (Maya would add the targets to it)."""
    data.require_unique(list(dict.fromkeys(n for r in records for n in _node_names(r))))
    data.require_unique(list(dict.fromkeys(r["name"] for r in records)))
    problems = []
    for record in records:
        name, kind, driven = record["name"], record["type"], _long(record["driven"])
        if cmds.objExists(name):
            node = _long(name)
            if cmds.nodeType(node) != kind or _driven(node) != driven:
                problems.append(f"{name} is taken by another node, not a {kind} on {record['driven']}")
        others = [short_name(c) for c in _constraints_on(driven) if cmds.nodeType(c) == kind and short_name(c) != name]
        if others:
            problems.append(f"{record['driven']} already has {kind} {', '.join(others)}")
    if problems:
        raise RuntimeError(f"Can't apply Constraints: {'; '.join(problems)}")


def _rebuild(record):
    name, kind = record["name"], record["type"]
    if cmds.objExists(name):
        cmds.delete(name)
    flags = {"name": name}
    skip = record.get("skip", {})
    if kind == "parentConstraint":
        for channel, flag in (("translate", "skipTranslate"), ("rotate", "skipRotate")):
            if skip.get(channel):
                flags[flag] = skip[channel]
    else:
        axes = [axis for channel in skip.values() for axis in channel]
        if axes:
            flags["skip"] = axes
    if kind == "aimConstraint":
        for attr in _AIM_VECTORS:
            flags[attr] = record[attr]
        flags["worldUpType"] = record["worldUpType"]
        if record["worldUpObject"]:
            flags["worldUpObject"] = record["worldUpObject"]

    command = _command(kind)
    targets = [t["name"] for t in record["targets"]]
    node = command(*targets, record["driven"], **flags)[0]

    aliases = command(node, query=True, weightAliasList=True)
    indices = cmds.getAttr(f"{node}.target", multiIndices=True)
    for target, alias, index in zip(record["targets"], aliases, indices):
        cmds.setAttr(f"{node}.{alias}", target["weight"])
        if kind == "parentConstraint":
            for attr in _TARGET_OFFSETS:
                cmds.setAttr(f"{node}.target[{index}].{attr}", *target[attr])
    if kind in _WITH_OFFSET:
        cmds.setAttr(f"{node}.offset", *record["offset"])
    if kind in _WITH_INTERP:
        cmds.setAttr(f"{node}.interpType", record["interpType"])
    return node


class ConstraintsProduct(data.DataProduct):
    name = "Constraints"
    utility = "Constraint Tool"
    kind = "constraints"
    extension = ".cnst"
    order = 114
    menu_slot = (4, 3)

    def selection_problems(self):
        selection = cmds.ls(selection=True, long=True)
        if not selection:
            return ["Nothing selected. Select the constrained nodes (or the constraints) to publish."]
        _found, without = _selected_constraints(selection)
        if without:
            return [f"No parent, point, orient, scale, aim or pole vector constraint on: {', '.join(without)}"]
        return []

    def gather(self, selection):
        found, _without = _selected_constraints(selection)
        if not found:
            raise RuntimeError("No constraints on the selected nodes to publish.")
        names = [short_name(c) for c in found]
        repeated = sorted({n for n in names if names.count(n) > 1})
        if repeated:
            raise RuntimeError(f"Several constraints have the same name, rename them first: {', '.join(repeated)}")
        return {"constraints": [_record(c) for c in found]}

    def apply(self, payload):
        records = _skip_missing(payload["constraints"])
        _check(records)
        created = []
        for record in records:
            created.append(_rebuild(record))
            targets = ", ".join(t["name"] for t in record["targets"])
            runlog.info(f"{created[-1]}: {record['type']} on {record['driven']} from {targets}")
        if not created:
            return "Created no constraints"
        return f"Created {data.plural(len(created), 'constraint')}: {', '.join(created)}"

    def describe(self, payload):
        records = payload["constraints"]
        counts = {kind: sum(r["type"] == kind for r in records) for kind in _TYPES}
        kinds = ", ".join(f"{count} {_TYPES[kind][0]}" for kind, count in counts.items() if count)
        driven = ", ".join(dict.fromkeys(r["driven"] for r in records))
        return [f"{data.plural(len(records), 'constraint')}: {kinds}", f"Constrained: {driven}"]


PRODUCT = ConstraintsProduct()
