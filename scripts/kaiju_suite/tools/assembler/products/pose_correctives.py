"""Pose Correctives (.psd): poseInterpolator nodes saved as data and rebuilt by name.

Publish saves the selected poseInterpolators (or every one driven by a
selected joint): their driver nodes with twist axis and Euler twist, the
interpolation settings, every pose (name, the driver rotations and
translations it stores, pose type, falloffs, independent and enabled), and
which attributes each pose's output drives, usually BlendShapes targets
(e.g. ``body_bs.elbow_bend``).

Run skips, with a warning, the interpolators whose drivers are missing and
the outputs whose node or attribute is missing. It raises before changing
anything if a driver, an output node or an interpolator's name matches
several nodes, or the name is taken by something that isn't a
poseInterpolator. Then it replaces each interpolator of the same name by a
new one, writes its poses straight into the node and reconnects its
outputs. The poseInterpolator plug-in is loaded as needed.
"""

from maya import cmds

from kaiju_suite.core.selection import short_name
from kaiju_suite.tools.assembler import data, runlog

PLUGIN = "poseInterpolator"
_DIGITS = 9

# Saved settings, with the type each is stored as.
_SETTINGS = (
    ("regularization", float),
    ("outputSmoothing", float),
    ("interpolation", int),
    ("allowNegativeWeights", bool),
    ("enableRotation", bool),
    ("enableTranslation", bool),
)

# Saved pose attributes: (key in the file, attribute, type).
_POSE_ATTRS = (
    ("type", "poseType", int),
    ("falloff", "poseFalloff", float),
    ("rotation_falloff", "poseRotationFalloff", float),
    ("translation_falloff", "poseTranslationFalloff", float),
    ("independent", "isIndependent", bool),
    ("enabled", "isEnabled", bool),
)

# Driver attributes a poseInterpolator reads: (driver attribute, its attribute).
_DRIVER_LINKS = (
    ("matrix", "driverMatrix"),
    ("jointOrient", "driverOrient"),
    ("rotateAxis", "driverRotateAxis"),
    ("rotateOrder", "driverRotateOrder"),
)


def load_plugin():
    if not cmds.pluginInfo(PLUGIN, query=True, loaded=True):
        cmds.loadPlugin(PLUGIN, quiet=True)


def _value(value, kind):
    value = kind(value)
    return round(value, _DIGITS) if kind is float else value


def _numbers(values):
    return [round(v, _DIGITS) for v in values or []]


# -- finding interpolators ----------------------------------------------------


def _interpolator_shape(node):
    """The poseInterpolator shape of ``node`` (the shape or its transform), or ``None``."""
    if cmds.nodeType(node) == "poseInterpolator":
        return cmds.ls(node, long=True)[0]
    shapes = cmds.listRelatives(node, shapes=True, type="poseInterpolator", fullPath=True)
    return shapes[0] if shapes else None


def _interpolators(selection):
    """The poseInterpolator shapes of the selection, in selection order. A
    selected driver (joint) adds the interpolators it drives, sorted by name."""
    if not cmds.pluginInfo(PLUGIN, query=True, loaded=True):
        return []
    found = []
    for node in cmds.ls(selection, objectsOnly=True, long=True) or []:
        shape = _interpolator_shape(node)
        if shape:
            found.append(shape)
            continue
        driven = cmds.listConnections(f"{node}.matrix", source=False, type="poseInterpolator", shapes=True) or []
        driven = cmds.ls(list(dict.fromkeys(driven)), long=True)
        found.extend(sorted(driven, key=short_name))
    return list(dict.fromkeys(found))


# -- publish ------------------------------------------------------------------


def _drivers(shape):
    drivers = []
    for index in cmds.getAttr(f"{shape}.driver", multiIndices=True) or []:
        plug = f"{shape}.driver[{index}]"
        source = cmds.listConnections(f"{plug}.driverMatrix", source=True, destination=False)
        if not source:
            raise RuntimeError(f"{short_name(shape)} has a driver with no node connected (driver[{index}]).")
        drivers.append(
            {
                "index": index,
                "node": short_name(source[0]),
                "twist_axis": cmds.getAttr(f"{plug}.driverTwistAxis"),
                "euler_twist": bool(cmds.getAttr(f"{plug}.driverEulerTwist")),
            }
        )
    return drivers


def _poses(shape, driver_indices):
    poses = []
    for index in cmds.getAttr(f"{shape}.pose", multiIndices=True) or []:
        plug = f"{shape}.pose[{index}]"
        pose = {"index": index, "name": cmds.getAttr(f"{plug}.poseName") or ""}
        pose["rotations"] = [_numbers(cmds.getAttr(f"{plug}.poseRotation[{d}]")) for d in driver_indices]
        pose["translations"] = [_numbers(cmds.getAttr(f"{plug}.poseTranslation[{d}]")) for d in driver_indices]
        for key, attr, kind in _POSE_ATTRS:
            pose[key] = _value(cmds.getAttr(f"{plug}.{attr}"), kind)
        poses.append(pose)
    return poses


def _outputs(shape):
    outputs = []
    for index in cmds.getAttr(f"{shape}.output", multiIndices=True) or []:
        for plug in cmds.listConnections(f"{shape}.output[{index}]", source=False, plugs=True) or []:
            node, attr = plug.split(".", 1)
            outputs.append({"pose": index, "node": short_name(node), "attr": attr})
    return sorted(outputs, key=lambda o: (o["pose"], o["node"], o["attr"]))


def _record(shape):
    drivers = _drivers(shape)
    transform = cmds.listRelatives(shape, parent=True, fullPath=True)[0]
    return {
        "name": short_name(transform),
        "drivers": [{k: d[k] for k in ("node", "twist_axis", "euler_twist")} for d in drivers],
        "settings": {attr: _value(cmds.getAttr(f"{shape}.{attr}"), kind) for attr, kind in _SETTINGS},
        "poses": _poses(shape, [d["index"] for d in drivers]),
        "outputs": _outputs(shape),
    }


# -- run ------------------------------------------------------------------------


def _check(records):
    """Raise, before anything changes, if a name is ambiguous or taken."""
    names = [r["name"] for r in records]
    names += [d["node"] for r in records for d in r["drivers"]]
    names += [o["node"] for r in records for o in r["outputs"] if cmds.ls(o["node"])]
    data.require_unique(list(dict.fromkeys(names)))
    taken = [r["name"] for r in records if cmds.objExists(r["name"]) and not _interpolator_shape(r["name"])]
    if taken:
        raise RuntimeError(f"Names taken by other nodes, not a poseInterpolator: {', '.join(taken)}")


def _missing_outputs(records):
    """The ``(name, output)`` pairs whose node or attribute is missing, logged as one warning."""
    missing = [
        (r["name"], f"{o['node']}.{o['attr']}")
        for r in records
        for o in r["outputs"]
        if not cmds.objExists(f"{o['node']}.{o['attr']}")
    ]
    if missing:
        runlog.warning(f"Skipped missing outputs: {', '.join(dict.fromkeys(p for _, p in missing))}")
    return set(missing)


def _create(name, drivers):
    """A new poseInterpolator ``name`` on ``drivers``; returns its shape."""
    if cmds.ls(type="poseInterpolatorManager"):
        # Maya's command also files it in the Pose Editor's manager.
        selection = cmds.ls(selection=True, long=True) or []
        cmds.select(drivers, replace=True)
        try:
            transform = cmds.poseInterpolator(name=name)[0]
        finally:
            cmds.select(selection, replace=True) if selection else cmds.select(clear=True)
        return _interpolator_shape(transform)
    transform = cmds.createNode("transform", name=name, skipSelect=True)
    shape = cmds.createNode("poseInterpolator", name=f"{short_name(transform)}Shape", parent=transform, skipSelect=True)
    for index, driver in enumerate(drivers):
        for source, target in _DRIVER_LINKS:
            if cmds.attributeQuery(source, node=driver, exists=True):
                cmds.connectAttr(f"{driver}.{source}", f"{shape}.driver[{index}].{target}")
    return cmds.ls(shape, long=True)[0]


def _build(record, skipped):
    name = record["name"]
    if cmds.objExists(name):
        cmds.delete(cmds.listRelatives(_interpolator_shape(name), parent=True, fullPath=True)[0])
    shape = _create(name, [d["node"] for d in record["drivers"]])
    for attr, _kind in _SETTINGS:
        cmds.setAttr(f"{shape}.{attr}", record["settings"][attr])
    for index, driver in enumerate(record["drivers"]):
        cmds.setAttr(f"{shape}.driver[{index}].driverTwistAxis", driver["twist_axis"])
        cmds.setAttr(f"{shape}.driver[{index}].driverEulerTwist", driver["euler_twist"])
    for pose in record["poses"]:
        plug = f"{shape}.pose[{pose['index']}]"
        cmds.setAttr(f"{plug}.poseName", pose["name"], type="string")
        for index, (rotation, translation) in enumerate(zip(pose["rotations"], pose["translations"])):
            cmds.setAttr(f"{plug}.poseRotation[{index}]", rotation, type="doubleArray")
            cmds.setAttr(f"{plug}.poseTranslation[{index}]", translation, type="doubleArray")
        for key, attr, kind in _POSE_ATTRS:
            # A new pose can hold a value below the attribute's minimum (a
            # translation falloff of 0), which setAttr refuses: only set changes.
            if _value(cmds.getAttr(f"{plug}.{attr}"), kind) != pose[key]:
                cmds.setAttr(f"{plug}.{attr}", pose[key])
    connected = 0
    for output in record["outputs"]:
        target = f"{output['node']}.{output['attr']}"
        if (name, target) not in skipped:
            cmds.connectAttr(f"{shape}.output[{output['pose']}]", target, force=True)
            connected += 1
    return connected


class PoseCorrectivesProduct(data.DataProduct):
    name = "Pose Correctives"
    kind = "pose_correctives"
    extension = ".psd"
    order = 85
    menu_slot = (3, 3)

    def _problems(self, selection):
        if not selection:
            return ["Nothing selected. Select the poseInterpolators to publish, or their driver joints."]
        if not _interpolators(selection):
            return ["No poseInterpolator selected or driven by the selected nodes."]
        return []

    def selection_problems(self):
        return self._problems(cmds.ls(selection=True, long=True) or [])

    def gather(self, selection):
        problems = self._problems(selection)
        if problems:
            raise RuntimeError(problems[0])
        return {"interpolators": [_record(shape) for shape in _interpolators(selection)]}

    def apply(self, payload):
        load_plugin()
        records = payload["interpolators"]
        missing = data.skip_missing([d["node"] for r in records for d in r["drivers"]], "drivers")
        records = [r for r in records if not any(d["node"] in missing for d in r["drivers"])]
        _check(records)
        skipped = _missing_outputs(records)
        poses = connections = 0
        for record in records:
            connected = _build(record, skipped)
            poses += len(record["poses"])
            connections += connected
            runlog.info(
                f"{record['name']}: built on {', '.join(d['node'] for d in record['drivers'])}, "
                f"{data.plural(len(record['poses']), 'pose')}, {data.plural(connected, 'connection')}"
            )
        return (
            f"Built {data.plural(len(records), 'poseInterpolator')} with {data.plural(poses, 'pose')}, "
            f"{data.plural(connections, 'connection')}"
        )

    def describe(self, payload):
        records = payload["interpolators"]
        poses = sum(len(r["poses"]) for r in records)
        lines = [f"{data.plural(len(records), 'poseInterpolator')}, {data.plural(poses, 'pose')}"]
        drivers = list(dict.fromkeys(d["node"] for r in records for d in r["drivers"]))
        lines.append(f"Drivers: {', '.join(drivers)}")
        driven = list(dict.fromkeys(o["node"] for r in records for o in r["outputs"]))
        if driven:
            lines.append(f"Drives: {', '.join(driven)}")
        return lines


PRODUCT = PoseCorrectivesProduct()
