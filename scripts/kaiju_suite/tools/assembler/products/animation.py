"""Animation (.anim): keyframes saved as data and put back on the same attributes.

Publish saves the time-based anim curves (``animCurveTL/TA/TU/TT``) wired
straight into the selected nodes' attributes: for each animated attribute
the curve type, pre/post infinity and weighted tangents, and for each key its
time, value, tangent types, angles and weights, breakdown flag and tangent
and weight locks. Driven keys (``animCurveU*``) aren't saved, nor are curves
reaching an attribute through another node (a pairBlend, say).

Nodes are saved by their shortest unique name and found by it on Run.
Times and values are in the scene's current units, as ``cmds.keyframe``
gives them (frames at the current frame rate, degrees or radians as set), and
Run reads them back in the units of the scene it runs in. There's no time
offset: keys go back on their saved frames.

Run skips, with a warning, the curves whose node or attribute is missing.
Then, on each other attribute in the file, it removes the existing keys and
rebuilds them.
Attributes not in the file keep their keys.

The ``.anim`` extension is also used by Maya's animImportExport plug-in,
whose format is different: these files hold JSON and that plug-in can't read
them.
"""

from maya import cmds

from kaiju_suite.tools.assembler import data, runlog

CURVE_TYPES = ("animCurveTL", "animCurveTA", "animCurveTU", "animCurveTT")


def _number(value):
    """``value`` as an int when it's whole (frame 4 rather than 4.0)."""
    return int(value) if float(value).is_integer() else value


def _animated(node):
    """``(attribute, curve)`` for each time-based curve wired straight into
    ``node``, sorted by attribute so publishing is deterministic."""
    found = cmds.listConnections(
        node, source=True, destination=False, connections=True, plugs=True, skipConversionNodes=False
    ) or []
    pairs = []
    for destination, source in zip(found[::2], found[1::2]):
        curve = source.split(".", 1)[0]
        if cmds.nodeType(curve) in CURVE_TYPES:
            pairs.append((destination.split(".", 1)[1], curve))
    return sorted(pairs)


def _keys(curve):
    times = cmds.keyframe(curve, query=True, timeChange=True) or []
    values = cmds.keyframe(curve, query=True, valueChange=True) or []
    breakdowns = set(cmds.keyframe(curve, query=True, breakdown=True) or [])
    tangents = {
        flag: cmds.keyTangent(curve, query=True, **{flag: True}) or []
        for flag in (
            "inTangentType",
            "outTangentType",
            "inAngle",
            "outAngle",
            "inWeight",
            "outWeight",
            "lock",
            "weightLock",
        )
    }
    keys = []
    for i, (time, value) in enumerate(zip(times, values)):
        keys.append(
            {
                "time": time,
                "value": value,
                "inTangentType": tangents["inTangentType"][i],
                "outTangentType": tangents["outTangentType"][i],
                "inAngle": tangents["inAngle"][i],
                "outAngle": tangents["outAngle"][i],
                "inWeight": tangents["inWeight"][i],
                "outWeight": tangents["outWeight"][i],
                "breakdown": time in breakdowns,
                "lock": bool(tangents["lock"][i]),
                "weightLock": bool(tangents["weightLock"][i]),
            }
        )
    return keys


def _record(name, plug, attribute, curve):
    # setInfinity only answers queries through the animated plug, not the curve.
    return {
        "node": name,
        "attribute": attribute,
        "type": cmds.nodeType(curve),
        "preInfinity": cmds.setInfinity(plug, query=True, preInfinite=True)[0],
        "postInfinity": cmds.setInfinity(plug, query=True, postInfinite=True)[0],
        "weightedTangents": bool(cmds.keyTangent(curve, query=True, weightedTangents=True)[0]),
        "keys": _keys(curve),
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
        runlog.warning(f"Skipped missing {label}: {', '.join(missing)}")
    if ambiguous:
        names = ", ".join(dict.fromkeys(ambiguous))
        raise RuntimeError(f"Several nodes have these names, can't tell which to key: {names}")
    return kept


def _apply_curve(plug, record):
    cmds.cutKey(plug, clear=True)
    keys = record["keys"]
    if not keys:
        return
    for key in keys:
        cmds.setKeyframe(plug, time=key["time"], value=key["value"])
    # Weighted first: switching it later would reset the weights.
    cmds.keyTangent(plug, edit=True, weightedTangents=record["weightedTangents"])
    for key in keys:
        t = (key["time"], key["time"])
        # Unlocked, so the in and out sides can be set apart; locks go back after.
        cmds.keyTangent(plug, edit=True, time=t, lock=False)
        if record["weightedTangents"]:
            cmds.keyTangent(plug, edit=True, time=t, weightLock=False)
            cmds.keyTangent(
                plug,
                edit=True,
                time=t,
                inAngle=key["inAngle"],
                outAngle=key["outAngle"],
                inWeight=key["inWeight"],
                outWeight=key["outWeight"],
            )
        else:
            cmds.keyTangent(plug, edit=True, time=t, inAngle=key["inAngle"], outAngle=key["outAngle"])
        cmds.keyTangent(
            plug, edit=True, time=t, inTangentType=key["inTangentType"], outTangentType=key["outTangentType"]
        )
        cmds.keyTangent(plug, edit=True, time=t, lock=key["lock"])
        if record["weightedTangents"]:
            cmds.keyTangent(plug, edit=True, time=t, weightLock=key["weightLock"])
        if key["breakdown"]:
            cmds.keyframe(plug, edit=True, time=t, breakdown=True)
    cmds.setInfinity(plug, preInfinite=record["preInfinity"], postInfinite=record["postInfinity"])


class AnimationProduct(data.DataProduct):
    name = "Animation"
    utility = "Animation Tool"
    kind = "animation"
    extension = ".anim"
    order = 110

    def selection_problems(self):
        selection = cmds.ls(selection=True, long=True)
        if not selection:
            return ["Nothing selected. Select the animated nodes to publish."]
        if not any(_animated(node) for node in selection):
            return ["Nothing selected has keys. Select nodes with keyframes to publish (driven keys aren't saved)."]
        return []

    def gather(self, selection):
        records = []
        for node in dict.fromkeys(selection):
            name = cmds.ls(node)[0]  # shortest unique name
            records.extend(_record(name, f"{node}.{attribute}", attribute, curve) for attribute, curve in _animated(node))
        if not records:
            raise RuntimeError("Nothing selected has keys to publish.")
        return {"curves": records}

    def apply(self, payload):
        records = _check(payload["curves"])
        for record in records:
            plug = f"{record['node']}.{record['attribute']}"
            _apply_curve(plug, record)
            runlog.info(f"{plug}: {data.plural(len(record['keys']), 'key')}")
        keys = sum(len(r["keys"]) for r in records)
        return f"Keyed {data.plural(len(records), 'attribute')} ({data.plural(keys, 'key')})"

    def describe(self, payload):
        records = payload["curves"]
        nodes = len({r["node"] for r in records})
        times = [k["time"] for r in records for k in r["keys"]]
        lines = [
            f"{data.plural(len(records), 'animated attribute')} on {data.plural(nodes, 'node')}, "
            f"{data.plural(len(times), 'key')}"
        ]
        if times:
            lines.append(f"Frames {_number(min(times))} to {_number(max(times))}")
        return lines


PRODUCT = AnimationProduct()
