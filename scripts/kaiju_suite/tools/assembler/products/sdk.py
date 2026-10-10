"""Set Driven Keys (.sdk): driven key curves saved as data and rebuilt by name.

Publish saves the driven key curves (``animCurveUL/UA/UU/UT``) feeding the
selected (driven) nodes' attributes, straight or through the
``unitConversion`` and ``blendWeighted`` nodes Maya adds: for each curve its
name, the driven node and attribute, the driver node and attribute, the
curve type, pre/post infinity and weighted tangents, and for each key the
driver value, value, tangent types, angles and weights, and tangent and
weight locks. Time-based keys (``animCurveT*``) are left to Animation.

Nodes are saved by their shortest unique name and found by it on Run.
Driver and driven values are in the scene's current units.

Run skips, with a warning, the curves whose driven or driver node or
attribute is missing. It raises, before changing anything, if a name matches
several nodes, or a driven attribute is locked or connected to something
other than driven keys (a constraint, keys, a direct connection). Then, on
each driven attribute in the file, it deletes the driven keys there and
rebuilds them as ``setDrivenKeyframe`` would (several drivers add up
through a ``blendWeighted``), keeping the curves' names where free.
Attributes not in the file keep their driven keys.
"""

from maya import cmds

from kaiju_suite.core import keys
from kaiju_suite.tools.assembler import data, runlog

CURVE_TYPES = ("animCurveUL", "animCurveUA", "animCurveUU", "animCurveUT")


def _driver(curve):
    """The plug driving ``curve``'s input, or ``None``."""
    found = cmds.listConnections(
        f"{curve}.input", source=True, destination=False, plugs=True, skipConversionNodes=True
    )
    return found[0] if found else None


def _curves_from(node):
    """The driven key curves behind ``node``, a node wired into a driven
    attribute: the curve itself, or the curves feeding a blendWeighted."""
    kind = cmds.nodeType(node)
    if kind in CURVE_TYPES:
        candidates = [node]
    elif kind == "blendWeighted":
        candidates = cmds.listConnections(node, source=True, destination=False, skipConversionNodes=True) or []
        candidates = [c for c in dict.fromkeys(candidates) if cmds.nodeType(c) in CURVE_TYPES]
    else:
        return []
    return [c for c in candidates if _driver(c)]


def _incoming(plug):
    """The node wired into ``plug``, skipping unitConversions, or ``None``."""
    found = cmds.listConnections(plug, source=True, destination=False, skipConversionNodes=True)
    return found[0] if found else None


def _driven(node):
    """``(attribute, curve)`` for each driven key curve feeding ``node``,
    sorted by attribute and driver so publishing is deterministic."""
    found = cmds.listConnections(
        node, source=True, destination=False, connections=True, plugs=True, skipConversionNodes=True
    ) or []
    pairs = []
    for destination, source in zip(found[::2], found[1::2]):
        attribute = destination.split(".", 1)[1]
        pairs.extend((attribute, _driver(c), c) for c in _curves_from(source.split(".", 1)[0]))
    return [(attribute, curve) for attribute, _driver_plug, curve in sorted(pairs)]


def _record(name, attribute, curve):
    driver_node, driver_attribute = _driver(curve).split(".", 1)
    pre, post = keys.infinity(curve)
    return {
        "name": curve,
        "node": name,
        "attribute": attribute,
        "driver": cmds.ls(driver_node)[0],  # shortest unique name
        "driverAttribute": driver_attribute,
        "type": cmds.nodeType(curve),
        "preInfinity": pre,
        "postInfinity": post,
        "weightedTangents": bool(cmds.keyTangent(curve, query=True, weightedTangents=True)[0]),
        "keys": keys.read_keys(curve, driven=True),
    }


def _driven_plug(record):
    return f"{record['node']}.{record['attribute']}"


def _driver_plug(record):
    return f"{record['driver']}.{record['driverAttribute']}"


def _check(records):
    """The records to apply. Those whose driven or driver node or attribute
    is missing are skipped with a warning; raises, before anything changes,
    if a node name matches several nodes or a driven attribute can't take
    driven keys."""
    missing, ambiguous, kept = [], [], []
    for record in records:
        problem = False
        for node, plug in ((record["node"], _driven_plug(record)), (record["driver"], _driver_plug(record))):
            matches = cmds.ls(node) or []
            if not matches:
                missing.append(node)
            elif len(matches) > 1:
                ambiguous.append(node)
            elif not cmds.objExists(plug):
                missing.append(plug)
            else:
                continue
            problem = True
        if not problem:
            kept.append(record)
    if ambiguous:
        names = ", ".join(dict.fromkeys(ambiguous))
        raise RuntimeError(f"Several nodes have these names, can't tell which to use: {names}")

    blocked = []
    for plug in dict.fromkeys(_driven_plug(r) for r in kept):
        source = _incoming(plug)
        if cmds.getAttr(plug, lock=True):
            blocked.append(f"{plug} (locked)")
        elif source and not _curves_from(source):
            blocked.append(f"{plug} ({source})")
    if blocked:
        raise RuntimeError(
            "Can't set driven keys on attributes that are locked or driven by something else: "
            + ", ".join(blocked)
        )

    missing = sorted(dict.fromkeys(missing))
    if missing:
        nodes = any("." not in m for m in missing)
        attrs = any("." in m for m in missing)
        label = "nodes and attributes" if nodes and attrs else "nodes" if nodes else "attributes"
        runlog.warning(f"Skipped missing {label}: {', '.join(missing)}")
    return kept


def _clear(plug):
    """Delete the driven key curves feeding ``plug``; Maya deletes the
    blendWeighted and unitConversion nodes left with nothing to do."""
    source = _incoming(plug)
    curves = _curves_from(source) if source else []
    if curves:
        cmds.delete(curves)


def _build(record):
    """Create one driven key curve, keyed and wired to its driver; returns
    its name. Its output is left for :func:`_connect`."""
    curve = cmds.createNode(record["type"], name=data.unique_name(record["name"]), skipSelect=True)
    for key in record["keys"]:
        cmds.setKeyframe(curve, float=key["driverValue"], value=key["value"])
    keys.set_tangents(curve, record["keys"], record["weightedTangents"], driven=True)
    keys.set_infinity(curve, record["preInfinity"], record["postInfinity"])
    cmds.connectAttr(_driver_plug(record), f"{curve}.input")
    return curve


def _connect(curves, plug):
    """Wire ``curves`` into ``plug``: straight for one, through a
    blendWeighted adding them up for several, as setDrivenKeyframe does.

    (Built by hand: undoing a setDrivenKeyframe that adds a blendWeighted
    leaves it and a curve behind.)
    """
    if len(curves) == 1:
        cmds.connectAttr(f"{curves[0]}.output", plug)
        return
    blend = cmds.createNode("blendWeighted", skipSelect=True)
    for i, curve in enumerate(curves):
        cmds.connectAttr(f"{curve}.output", f"{blend}.input[{i}]")
        cmds.setAttr(f"{blend}.weight[{i}]", 1.0)
    cmds.connectAttr(f"{blend}.output", plug)


class SetDrivenKeysProduct(data.DataProduct):
    name = "Set Driven Keys"
    kind = "sdk"
    extension = ".sdk"
    order = 112
    menu_slot = (4, 2)

    def selection_problems(self):
        selection = cmds.ls(selection=True, long=True)
        if not selection:
            return ["Nothing selected. Select the driven nodes to publish."]
        if not any(_driven(node) for node in selection):
            return ["Nothing selected has driven keys. Select the nodes the driven keys drive (not the drivers)."]
        return []

    def gather(self, selection):
        records = []
        for node in dict.fromkeys(selection):
            name = cmds.ls(node)[0]  # shortest unique name
            records.extend(_record(name, attribute, curve) for attribute, curve in _driven(node))
        if not records:
            raise RuntimeError("Nothing selected has driven keys to publish.")
        return {"curves": records}

    def apply(self, payload):
        records = [r for r in _check(payload["curves"]) if r["keys"]]
        plugs = list(dict.fromkeys(_driven_plug(r) for r in records))
        for plug in plugs:
            _clear(plug)
        for plug in plugs:
            curves = []
            for record in (r for r in records if _driven_plug(r) == plug):
                curves.append(_build(record))
                runlog.info(
                    f"{plug} driven by {_driver_plug(record)}: "
                    f"{data.plural(len(record['keys']), 'key')} ({curves[-1]})"
                )
            _connect(curves, plug)
        count = sum(len(r["keys"]) for r in records)
        return (
            f"Set driven keys on {data.plural(len(plugs), 'attribute')} "
            f"({data.plural(len(records), 'curve')}, {data.plural(count, 'key')})"
        )

    def describe(self, payload):
        records = payload["curves"]
        attributes = len({_driven_plug(r) for r in records})
        nodes = len({r["node"] for r in records})
        count = sum(len(r["keys"]) for r in records)
        drivers = sorted({_driver_plug(r) for r in records})
        return [
            f"{data.plural(len(records), 'driven key curve')} on {data.plural(attributes, 'attribute')} "
            f"of {data.plural(nodes, 'node')}, {data.plural(count, 'key')}",
            f"Drivers: {', '.join(drivers)}",
        ]


PRODUCT = SetDrivenKeysProduct()
