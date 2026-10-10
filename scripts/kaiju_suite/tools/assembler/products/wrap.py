"""Wrap (.wrap): wrap and proximityWrap deformers saved as data and rebound by name.

Publish saves every wrap and proximityWrap on the selected meshes: which
meshes they deform, their driver meshes, their settings and per-driver
settings, and (proximityWrap only) the painted weights, sparse. Run finds the
meshes and drivers by name, replaces a deformer of the same name and type,
and binds a new one after the mesh's existing deformers, so it sits on top
of skin. A wrap binds to its drivers as they are when it's created; a
proximityWrap binds to their undeformed shape.

Missing meshes are skipped with a warning; a deformer whose driver is
missing is skipped with a warning. Ambiguous names, a changed vertex count
on a mesh with painted weights, or a name taken by another node stop the
Run before anything changes.
"""

from maya import cmds

from kaiju_suite.core.selection import short_name
from kaiju_suite.tools.assembler import data, runlog
from kaiju_suite.tools.assembler.products.deltamush import _geometry_index, _mesh_transforms, _shape

WRAP, PROXIMITY = "wrap", "proximityWrap"
TYPES = (WRAP, PROXIMITY)

# Deformer settings saved per type.
_SETTINGS = {
    WRAP: (
        "envelope",
        "weightThreshold",
        "maxDistance",
        "autoWeightThreshold",
        "exclusiveBind",
        "falloffMode",
    ),
    PROXIMITY: (
        "envelope",
        "wrapMode",
        "maxDrivers",
        "falloffScale",
        "dropoffRateScale",
        "scaleCompensation",
        "coordinateFrames",
        "smoothNormals",
        "spanSamples",
        "smoothInfluences",
        "softNormalization",
    ),
}
# Per-driver settings: a wrap keeps them in multi attributes indexed like its
# drivers, a proximityWrap in its ``drivers[i]`` compound.
_DRIVER_SETTINGS = {
    WRAP: ("dropoff", "smoothness", "inflType"),
    PROXIMITY: (
        "driverStrength",
        "driverFalloffStart",
        "driverFalloffEnd",
        "driverDropoffRate",
        "driverUseTransformAsDeformation",
        "driverScaleCompensation",
        "driverWrapMode",
        "driverOverrideSmoothNormals",
        "driverSmoothNormals",
        "driverOverrideSpanSamples",
        "driverSpanSamples",
        "driverOverrideSmoothInfluences",
        "driverSmoothInfluences",
    ),
}
_DIGITS = 6


def _value(plug):
    value = cmds.getAttr(plug)
    return round(value, _DIGITS) if isinstance(value, float) else value


def _driver_plug(node, node_type, index, attr):
    if node_type == WRAP:
        return f"{node}.{attr}[{index}]"
    return f"{node}.drivers[{index}].{attr}"


def _geometry_plug(node, node_type, index):
    """The plug a driver's mesh feeds, for driver ``index``."""
    if node_type == WRAP:
        return f"{node}.driverPoints[{index}]"
    return f"{node}.drivers[{index}].driverGeometry"


def _drivers(node):
    """``[(index, shape)]`` of ``node``'s connected drivers, in index order."""
    node_type = cmds.nodeType(node)
    array = f"{node}.driverPoints" if node_type == WRAP else f"{node}.drivers"
    found = []
    for index in cmds.getAttr(array, multiIndices=True) or []:
        source = cmds.listConnections(
            _geometry_plug(node, node_type, index), source=True, destination=False, shapes=True
        )
        if source:
            found.append((index, cmds.ls(source[0], long=True)[0]))
    return found


def _wraps(shape):
    """The wrap and proximityWrap nodes deforming ``shape``, first evaluated first.

    A driver's own deformers are in the history too; only nodes with
    ``shape`` as an output count.
    """
    history = cmds.ls(cmds.listHistory(shape) or [], type=list(TYPES)) or []
    return [n for n in reversed(history) if _geometry_index(n, shape) is not None]


def _read_weights(node, index, vertex_count):
    """Sparse ``[vertex, weight]`` pairs of the weights that aren't 1.0."""
    weights = []
    plug = f"{node}.weightList[{index}].weights"
    for vertex in cmds.getAttr(plug, multiIndices=True) or []:
        weight = round(cmds.getAttr(f"{plug}[{vertex}]"), _DIGITS)
        if vertex < vertex_count and weight != 1.0:
            weights.append([vertex, weight])
    return sorted(weights)


def _record(node):
    node_type = cmds.nodeType(node)
    meshes = []
    for shape in cmds.ls(cmds.deformer(node, query=True, geometry=True) or [], long=True):
        transform = cmds.listRelatives(shape, parent=True, fullPath=True)[0]
        vertex_count = cmds.polyEvaluate(shape, vertex=True)
        mesh = {"mesh": short_name(transform), "vertex_count": vertex_count}
        if node_type == PROXIMITY:
            mesh["weights"] = _read_weights(node, _geometry_index(node, shape), vertex_count)
        meshes.append(mesh)

    drivers = []
    for index, shape in _drivers(node):
        if cmds.nodeType(shape) != "mesh":
            raise RuntimeError(f"{node}: driver {short_name(shape)} isn't a mesh; only mesh drivers can be published.")
        transform = cmds.listRelatives(shape, parent=True, fullPath=True)[0]
        driver = {"mesh": short_name(transform)}
        for attr in _DRIVER_SETTINGS[node_type]:
            driver[attr] = _value(_driver_plug(node, node_type, index, attr))
        drivers.append(driver)
    if not drivers:
        raise RuntimeError(f"{node} has no driver meshes to publish.")

    settings = {attr: _value(f"{node}.{attr}") for attr in _SETTINGS[node_type]}
    return {"name": node, "type": node_type, "meshes": meshes, "drivers": drivers, "settings": settings}


# -- apply ------------------------------------------------------------------


def _check(records):
    """Map each mesh and driver name to its transform, raising before
    anything changes if a name is ambiguous, a painted mesh's vertex count
    differs, or a deformer's name is taken by another node."""
    names = [m["mesh"] for r in records for m in r["meshes"]] + [d["mesh"] for r in records for d in r["drivers"]]
    transforms, problems = {}, []
    for name in dict.fromkeys(names):
        matches = [m for m in cmds.ls(name, long=True) if cmds.objectType(m, isAType="transform") and _shape(m)]
        if len(matches) != 1:
            found = ", ".join(matches) if matches else "no mesh"
            problems.append(f"{name} doesn't name exactly one mesh ({found})")
        else:
            transforms[name] = matches[0]
    for record in records:
        for mesh in record["meshes"]:
            transform = transforms.get(mesh["mesh"])
            if transform is None or not mesh.get("weights"):
                continue
            count = cmds.polyEvaluate(_shape(transform), vertex=True)
            if count != mesh["vertex_count"]:
                problems.append(f"{mesh['mesh']} has {count} vertices, the file has {mesh['vertex_count']}")
    if problems:
        raise RuntimeError(f"Can't apply Wrap: {'; '.join(dict.fromkeys(problems))}")

    taken = []
    for record in records:
        name = record["name"]
        if not cmds.objExists(name):
            continue
        shapes = [_shape(transforms[m["mesh"]]) for m in record["meshes"]]
        is_ours = cmds.nodeType(name) == record["type"] and any(_geometry_index(name, s) is not None for s in shapes)
        if not is_ours:
            taken.append(name)
    if taken:
        noun = "a wrap" if len(taken) == 1 else "wraps"
        raise RuntimeError(f"Names taken by other nodes, not {noun} of the same type on the same mesh: {', '.join(taken)}")
    return transforms


def _delete(node):
    """Delete ``node`` and, for a wrap, the base meshes made for it."""
    bases = []
    if cmds.nodeType(node) == WRAP:
        for index in cmds.getAttr(f"{node}.basePoints", multiIndices=True) or []:
            source = cmds.listConnections(f"{node}.basePoints[{index}]", source=True, destination=False) or []
            bases.extend(cmds.ls(source, long=True))
    cmds.delete(node)
    existing = [b for b in bases if cmds.objExists(b)]
    if existing:
        cmds.delete(existing)


def _base_mesh(driver, shape):
    """A hidden copy of ``shape`` as it is now, in world space, for a wrap
    to bind against (what Maya's Create Wrap names ``<driver>Base``)."""
    transform = data.node_path(data.create_node("transform", f"{short_name(driver)}Base"))
    base = cmds.createNode("mesh", name=f"{short_name(transform)}Shape", parent=transform, skipSelect=True)
    base = cmds.ls(base, long=True)[0]
    cmds.connectAttr(f"{shape}.worldMesh[0]", f"{base}.inMesh")
    cmds.polyEvaluate(base, vertex=True)  # pull the points before letting go
    cmds.disconnectAttr(f"{shape}.worldMesh[0]", f"{base}.inMesh")
    cmds.setAttr(f"{transform}.visibility", False)
    return base


def _rebuild_wrap(record, shapes, drivers):
    node = cmds.deformer(*shapes, type=WRAP, name=record["name"])[0]
    for attr in _SETTINGS[WRAP]:
        cmds.setAttr(f"{node}.{attr}", record["settings"][attr])
    for index, (driver, saved) in enumerate(zip(drivers, record["drivers"])):
        for attr in _DRIVER_SETTINGS[WRAP]:
            cmds.setAttr(_driver_plug(node, WRAP, index, attr), saved[attr])
    cmds.connectAttr(f"{shapes[0]}.worldMatrix[0]", f"{node}.geomMatrix")
    for index, driver in enumerate(drivers):
        shape = _shape(driver)
        cmds.connectAttr(f"{_base_mesh(driver, shape)}.worldMesh[0]", f"{node}.basePoints[{index}]")
        cmds.connectAttr(f"{shape}.worldMesh[0]", f"{node}.driverPoints[{index}]")
    return node


def _rebuild_proximity(record, shapes, drivers):
    node = cmds.proximityWrap(*shapes, name=record["name"])[0]
    for attr in _SETTINGS[PROXIMITY]:
        cmds.setAttr(f"{node}.{attr}", record["settings"][attr])
    driver_shapes = [_shape(d) for d in drivers]
    cmds.proximityWrap(node, edit=True, addDrivers=driver_shapes)
    index_of = {shape: index for index, shape in _drivers(node)}
    for shape, saved in zip(driver_shapes, record["drivers"]):
        for attr in _DRIVER_SETTINGS[PROXIMITY]:
            cmds.setAttr(_driver_plug(node, PROXIMITY, index_of[shape], attr), saved[attr])
    for shape, mesh in zip(shapes, record["meshes"]):
        index = _geometry_index(node, shape)
        for vertex, weight in mesh.get("weights", []):
            cmds.setAttr(f"{node}.weightList[{index}].weights[{vertex}]", weight)
    return node


def _rebuild(record, transforms):
    if cmds.objExists(record["name"]):
        _delete(record["name"])
    shapes = [_shape(transforms[m["mesh"]]) for m in record["meshes"]]
    drivers = [transforms[d["mesh"]] for d in record["drivers"]]
    # Maya appends a new deformer after the existing ones, so it sits on top of skin.
    if record["type"] == WRAP:
        return _rebuild_wrap(record, shapes, drivers)
    return _rebuild_proximity(record, shapes, drivers)


def _counts(records):
    """``"1 wrap, 2 proximityWraps"``."""
    parts = []
    for node_type in TYPES:
        count = sum(1 for r in records if r["type"] == node_type)
        if count:
            parts.append(data.plural(count, node_type))
    return ", ".join(parts) or "no wraps"


class WrapProduct(data.DataProduct):
    name = "Wrap"
    utility = "Wrap Tool"
    kind = "wrap"
    extension = ".wrap"
    order = 84
    menu_slot = (3, 4)

    def selection_problems(self):
        selection = cmds.ls(selection=True)
        if not selection:
            return ["Nothing selected. Select the meshes with a wrap or proximityWrap to publish."]
        transforms = _mesh_transforms(selection)
        if not transforms:
            return ["No meshes selected. Select the meshes with a wrap or proximityWrap to publish."]
        without = [short_name(t) for t in transforms if not _wraps(_shape(t))]
        if without:
            return [f"No wrap or proximityWrap on: {', '.join(without)}"]
        return []

    def gather(self, selection):
        nodes = []
        for transform in _mesh_transforms(selection):
            nodes.extend(_wraps(_shape(transform)))
        nodes = list(dict.fromkeys(nodes))
        if not nodes:
            raise RuntimeError("No wrap or proximityWrap on the selected meshes to publish.")
        return {"deformers": [_record(node) for node in nodes]}

    def apply(self, payload):
        records = payload["deformers"]
        missing = data.skip_missing([m["mesh"] for r in records for m in r["meshes"]], "meshes")
        records = [dict(r, meshes=[m for m in r["meshes"] if m["mesh"] not in missing]) for r in records]
        records = [r for r in records if r["meshes"]]
        missing = data.skip_missing([d["mesh"] for r in records for d in r["drivers"]], "drivers")
        records = [r for r in records if not any(d["mesh"] in missing for d in r["drivers"])]

        transforms = _check(records)
        created = []
        for record in records:
            node = _rebuild(record, transforms)
            created.append(node)
            meshes = ", ".join(m["mesh"] for m in record["meshes"])
            drivers = ", ".join(d["mesh"] for d in record["drivers"])
            runlog.info(f"{node}: {record['type']} on {meshes}, driven by {drivers}")
        if not created:
            return "Created no wraps"
        meshes = ", ".join(dict.fromkeys(m["mesh"] for r in records for m in r["meshes"]))
        return f"Created {', '.join(created)} on {meshes}"

    def describe(self, payload):
        records = payload["deformers"]
        meshes = ", ".join(dict.fromkeys(m["mesh"] for r in records for m in r["meshes"]))
        drivers = ", ".join(dict.fromkeys(d["mesh"] for r in records for d in r["drivers"]))
        return [_counts(records), f"Meshes: {meshes}", f"Drivers: {drivers}"]


PRODUCT = WrapProduct()
