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

The proximityWrap half (recording, checking and rebuilding) is
:mod:`kaiju_suite.datatypes.proximity_wrap`, shared with Scripter's
ProximityWrap items (``.pwrap``); this file format is unchanged.
"""

from maya import cmds

from kaiju_suite.core.selection import short_name
from kaiju_suite.datatypes import proximity_wrap
from kaiju_suite.tools.assembler import data, runlog
from kaiju_suite.tools.assembler.products.deltamush import _geometry_index, _mesh_transforms, _shape

WRAP, PROXIMITY = "wrap", proximity_wrap.PROXIMITY
TYPES = (WRAP, PROXIMITY)

# Wrap settings saved; a proximityWrap's are proximity_wrap.SETTINGS.
_SETTINGS = (
    "envelope",
    "weightThreshold",
    "maxDistance",
    "autoWeightThreshold",
    "exclusiveBind",
    "falloffMode",
)
# A wrap's per-driver settings, in multi attributes indexed like its drivers.
_DRIVER_SETTINGS = ("dropoff", "smoothness", "inflType")


def _drivers(node):
    """``[(index, shape)]`` of wrap ``node``'s connected drivers, in index order."""
    found = []
    for index in cmds.getAttr(f"{node}.driverPoints", multiIndices=True) or []:
        source = cmds.listConnections(f"{node}.driverPoints[{index}]", source=True, destination=False, shapes=True)
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


def _record(node):
    if cmds.nodeType(node) == PROXIMITY:
        return proximity_wrap.record(node)
    meshes = []
    for shape in cmds.ls(cmds.deformer(node, query=True, geometry=True) or [], long=True):
        transform = cmds.listRelatives(shape, parent=True, fullPath=True)[0]
        meshes.append({"mesh": short_name(transform), "vertex_count": cmds.polyEvaluate(shape, vertex=True)})

    drivers = []
    for index, shape in _drivers(node):
        if cmds.nodeType(shape) != "mesh":
            raise RuntimeError(f"{node}: driver {short_name(shape)} isn't a mesh; only mesh drivers can be published.")
        transform = cmds.listRelatives(shape, parent=True, fullPath=True)[0]
        driver = {"mesh": short_name(transform)}
        for attr in _DRIVER_SETTINGS:
            driver[attr] = proximity_wrap.value(f"{node}.{attr}[{index}]")
        drivers.append(driver)
    if not drivers:
        raise RuntimeError(f"{node} has no driver meshes to publish.")

    settings = {attr: proximity_wrap.value(f"{node}.{attr}") for attr in _SETTINGS}
    return {"name": node, "type": WRAP, "meshes": meshes, "drivers": drivers, "settings": settings}


# -- apply ------------------------------------------------------------------


def _delete(node):
    """Delete wrap ``node`` and the base meshes made for it."""
    bases = []
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


def _rebuild_wrap(record, transforms):
    if cmds.objExists(record["name"]):
        _delete(record["name"])
    shapes = [_shape(transforms[m["mesh"]]) for m in record["meshes"]]
    drivers = [transforms[d["mesh"]] for d in record["drivers"]]
    # Maya appends a new deformer after the existing ones, so it sits on top of skin.
    node = cmds.deformer(*shapes, type=WRAP, name=record["name"])[0]
    for attr in _SETTINGS:
        cmds.setAttr(f"{node}.{attr}", record["settings"][attr])
    for index, saved in enumerate(record["drivers"]):
        for attr in _DRIVER_SETTINGS:
            cmds.setAttr(f"{node}.{attr}[{index}]", saved[attr])
    cmds.connectAttr(f"{shapes[0]}.worldMatrix[0]", f"{node}.geomMatrix")
    for index, driver in enumerate(drivers):
        shape = _shape(driver)
        cmds.connectAttr(f"{_base_mesh(driver, shape)}.worldMesh[0]", f"{node}.basePoints[{index}]")
        cmds.connectAttr(f"{shape}.worldMesh[0]", f"{node}.driverPoints[{index}]")
    return node


def _rebuild(record, transforms):
    if record["type"] == WRAP:
        return _rebuild_wrap(record, transforms)
    return proximity_wrap.rebuild(record, transforms)


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
    utility = "ProximityWrap Tool"
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
        records = proximity_wrap.present(payload["deformers"])
        transforms = proximity_wrap.check(records, "Wrap")
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
