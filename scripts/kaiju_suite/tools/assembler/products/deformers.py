"""Deformers (.dfm): cluster, softMod, wire, lattice (ffd) and nonLinear
deformers saved as data and rebuilt on their meshes.

Publish saves every such deformer on the selected meshes, first evaluated
first: its type, settings, the vertices it deforms on each selected mesh
(its members) and its per-vertex weights (sparse: only weights that aren't
1.0). Cluster, softMod and nonLinear also save their handle, lattices their
lattice and base (transforms, divisions, points), and wires their curves'
names, dropoff and base wire shape.

Run finds the meshes by name, replaces a deformer of the same name and
creates each new one after the mesh's existing deformers. Missing meshes are
skipped with a warning, and so is a wire whose curve is missing. Ambiguous
names, changed vertex counts and names taken by other nodes raise before
anything changes.
"""

from maya import cmds

from kaiju_suite.core import deformers as weightmaps
from kaiju_suite.core.selection import short_name
from kaiju_suite.tools.assembler import data, runlog

_TYPES = ("cluster", "softMod", "wire", "ffd", "nonLinear")
_HANDLED = ("cluster", "softMod", "nonLinear")  # types with a handle transform
_DIGITS = 6

# Saved settings per type; nonLinear saves its node's keyable attributes,
# which depend on the kind (bend, twist, ...).
_SETTINGS = {
    "cluster": ("envelope", "relative", "angleInterpolation"),
    "softMod": (
        "envelope", "relative", "falloffMode", "falloffRadius", "falloffCenterX", "falloffCenterY",
        "falloffCenterZ", "falloffInX", "falloffInY", "falloffInZ", "falloffAroundSelection",
        "falloffMasking",
    ),
    "ffd": (
        "envelope", "localInfluenceS", "localInfluenceT", "localInfluenceU", "local", "outsideLattice",
        "outsideFalloffDist", "usePartialResolution", "partialResolution", "freezeGeometry",
    ),
    "wire": ("envelope", "crossingEffect", "tension", "localInfluence", "rotation"),
}
_XFORM = (
    "translate", "rotate", "scale", "shear", "rotatePivot", "scalePivot",
    "rotatePivotTranslate", "scalePivotTranslate",
)


def _round(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return round(value, _DIGITS)
    if isinstance(value, (list, tuple)):
        return [_round(v) for v in value]
    return value


def _shape(transform, node_type="mesh"):
    """The visible shape of ``transform`` (long name), or ``None``."""
    shapes = cmds.listRelatives(transform, shapes=True, noIntermediate=True, type=node_type, fullPath=True)
    return shapes[0] if shapes else None


def _mesh_transforms(selection):
    """The selected transforms that have a mesh, in selection order; a
    selected shape or component counts as its transform."""
    found = []
    for node in cmds.ls(selection, objectsOnly=True, long=True) or []:
        if cmds.nodeType(node) == "mesh":
            node = cmds.listRelatives(node, parent=True, fullPath=True)[0]
        if cmds.objectType(node, isAType="transform") and _shape(node):
            found.append(node)
    return list(dict.fromkeys(found))


def _source(plug):
    """The transform connected into ``plug`` (long name), or ``None``."""
    found = cmds.listConnections(plug, source=True, destination=False) or []
    return cmds.ls(found[0], long=True)[0] if found else None


def _type_label(record):
    return record.get("nonlinear") or record["type"]


# -- reading ------------------------------------------------------------------


def _settings(node, node_type):
    if node_type == "nonLinear":
        attrs = [a for a in cmds.listAttr(node, keyable=True) or [] if "." not in a]
    else:
        attrs = [a for a in _SETTINGS[node_type] if cmds.attributeQuery(a, node=node, exists=True)]
    settings = {}
    for attr in attrs:
        value = cmds.getAttr(f"{node}.{attr}")
        if isinstance(value, (bool, int, float)):
            settings[attr] = _round(value)
    return settings


def _read_xform(transform):
    parent = cmds.listRelatives(transform, parent=True)
    record = {"name": short_name(transform), "parent": parent[0] if parent else None}
    for attr in _XFORM:
        record[attr] = _round(list(cmds.getAttr(f"{transform}.{attr}")[0]))
    record["rotateOrder"] = cmds.getAttr(f"{transform}.rotateOrder")
    return record


def _handle(node):
    return _source(f"{node}.matrix")


def _lattice_parts(node):
    """The lattice and base transforms of ffd ``node`` (long names)."""
    return _source(f"{node}.deformedLatticeMatrix"), _source(f"{node}.baseLatticeMatrix")


def _wire_indices(node):
    return cmds.getAttr(f"{node}.deformedWire", multiIndices=True) or []


def _aux_names(node):
    """Short names of the handle, lattice and base transforms ``node`` owns."""
    node_type = cmds.nodeType(node)
    if node_type in _HANDLED:
        nodes = [_handle(node)]
    elif node_type == "ffd":
        nodes = list(_lattice_parts(node))
    else:
        nodes = []
    return {short_name(n) for n in nodes if n}


def _curve_points(curve):
    flat = cmds.xform(f"{curve}.cv[*]", query=True, worldSpace=True, translation=True)
    return [_round(flat[i:i + 3]) for i in range(0, len(flat), 3)]


def _record(node, meshes):
    """``node`` as data; ``meshes`` are the selected ``(transform, shape)`` it deforms."""
    node_type = cmds.nodeType(node)
    record = {"name": node, "type": node_type, "settings": _settings(node, node_type), "geometry": []}
    for transform, shape in meshes:
        index = weightmaps.geometry_index(node, shape)
        count = cmds.polyEvaluate(shape, vertex=True)
        record["geometry"].append({
            "mesh": short_name(transform),
            "vertex_count": count,
            "members": weightmaps.members(node, index, count),
            "weights": weightmaps.read_weights(node, index, count),
        })
    if node_type in _HANDLED:
        handle = _handle(node)
        record["handle"] = _read_xform(handle)
        shape = cmds.listRelatives(handle, shapes=True, fullPath=True)[0]
        if node_type == "nonLinear":
            record["nonlinear"] = cmds.nodeType(shape)[len("deform"):].lower()
        else:
            record["handle"]["origin"] = _round(list(cmds.getAttr(f"{shape}.origin")[0]))
            if not cmds.listConnections(f"{node}.bindPreMatrix", source=True, destination=False):
                matrix = cmds.getAttr(f"{node}.bindPreMatrix")
                record["bind_pre_matrix"] = _round(list(matrix)) if matrix else None
    elif node_type == "ffd":
        lattice, base = _lattice_parts(node)
        shape = _shape(lattice, "lattice")
        divisions = [cmds.getAttr(f"{shape}.{axis}Divisions") for axis in "stu"]
        count = divisions[0] * divisions[1] * divisions[2]
        record["lattice"] = _read_xform(lattice)
        record["base"] = _read_xform(base)
        record["divisions"] = divisions
        record["points"] = [_round(list(p)) for p in cmds.getAttr(f"{shape}.controlPoints[0:{count - 1}]")]
    elif node_type == "wire":
        record["wires"] = [
            {
                "curve": short_name(_source(f"{node}.deformedWire[{i}]")),
                "dropoff": _round(cmds.getAttr(f"{node}.dropoffDistance[{i}]")),
                "scale": _round(cmds.getAttr(f"{node}.scale[{i}]")),
                "base_points": _curve_points(_source(f"{node}.baseWire[{i}]")),
            }
            for i in _wire_indices(node)
        ]
    return record


# -- checking -----------------------------------------------------------------


def _unique(name, kind):
    """Long names of the ``kind`` transforms (with a ``kind`` shape) named ``name``."""
    return [m for m in cmds.ls(name, long=True) if cmds.objectType(m, isAType="transform") and _shape(m, kind)]


def _skip_missing(records):
    """Drop missing meshes (and deformers left with none) and wires whose
    curves are missing, each with a warning."""
    missing = data.skip_missing([g["mesh"] for r in records for g in r["geometry"]], "meshes")
    kept = []
    for record in records:
        record = dict(record, geometry=[g for g in record["geometry"] if g["mesh"] not in missing])
        if not record["geometry"]:
            continue
        if record["type"] == "wire":
            curves = [w["curve"] for w in record["wires"] if not cmds.objExists(w["curve"])]
            if curves:
                runlog.warning(f"Skipped wire {record['name']}: missing curves {', '.join(curves)}")
                continue
        kept.append(record)
    return kept


def _aux_records(record):
    if record["type"] in _HANDLED:
        return [record["handle"]]
    if record["type"] == "ffd":
        return [record["lattice"], record["base"]]
    return []


def _check(records):
    """Map each mesh and curve name to its node, raising before anything
    changes if a name is ambiguous, a vertex count differs, or a name is
    taken by something other than the same deformer on its meshes."""
    found, problems = {}, []
    names = [("mesh", g["mesh"]) for r in records for g in r["geometry"]]
    names += [("nurbsCurve", w["curve"]) for r in records for w in r.get("wires", ())]
    for kind, name in dict.fromkeys(names):
        matches = _unique(name, kind)
        if len(matches) != 1:
            label = "mesh" if kind == "mesh" else "curve"
            problems.append(f"{name} doesn't name exactly one {label} ({', '.join(cmds.ls(name, long=True)) or 'none'})")
        else:
            found[name] = matches[0]
    parents = [x["parent"] for r in records for x in _aux_records(r) if x["parent"]]
    for name in dict.fromkeys(parents):
        if len(cmds.ls(name, long=True)) > 1:
            problems.append(f"Several nodes are named {name}, can't tell which to parent to")
    for record in records:
        for geometry in record["geometry"]:
            transform = found.get(geometry["mesh"])
            if transform is None:
                continue
            count = cmds.polyEvaluate(_shape(transform), vertex=True)
            if count != geometry["vertex_count"]:
                problems.append(f"{geometry['mesh']} has {count} vertices, the file has {geometry['vertex_count']}")
    if problems:
        raise RuntimeError(f"Can't apply Deformers: {'; '.join(dict.fromkeys(problems))}")

    taken = []
    for record in records:
        name = record["name"]
        owned = set()
        if cmds.objExists(name):
            shapes = [_shape(found[g["mesh"]]) for g in record["geometry"]]
            ours = cmds.nodeType(name) == record["type"] and any(
                weightmaps.geometry_index(name, s) is not None for s in shapes
            )
            if not ours:
                taken.append(name)
                continue
            owned = _aux_names(name)
        taken.extend(x["name"] for x in _aux_records(record) if cmds.objExists(x["name"]) and x["name"] not in owned)
    if taken:
        raise RuntimeError(f"Names taken by other nodes, not the same deformer on the same meshes: {', '.join(taken)}")
    return found


# -- rebuilding -----------------------------------------------------------------


def _apply_xform(transform, record):
    """Rename ``transform`` to the saved name, parent it and set its
    transform. Returns its new long name."""
    if short_name(transform) != record["name"]:
        transform = cmds.ls(cmds.rename(transform, record["name"]), long=True)[0]
    parent = record["parent"]
    if parent:
        if cmds.objExists(parent):
            transform = cmds.ls(cmds.parent(transform, parent)[0], long=True)[0]
        else:
            runlog.warning(f"Skipped missing parents: {parent} ({record['name']} left in the world)")
    cmds.setAttr(f"{transform}.rotateOrder", record["rotateOrder"])
    for attr in _XFORM:
        cmds.setAttr(f"{transform}.{attr}", *record[attr])
    return transform


def _rebuild(record, found):
    name, node_type = record["name"], record["type"]
    if cmds.objExists(name):
        cmds.delete(name)
    shapes = [_shape(found[g["mesh"]]) for g in record["geometry"]]
    members = [c for g, s in zip(record["geometry"], shapes) for c in weightmaps.member_components(s, g["members"])]
    # Maya appends a new deformer after the existing ones.
    if node_type == "cluster":
        node, handle = cmds.cluster(*members, name=name)
    elif node_type == "softMod":
        node, handle = cmds.softMod(*members, name=name)
    elif node_type == "nonLinear":
        node, handle = cmds.nonLinear(*members, type=record["nonlinear"], name=name)
    elif node_type == "ffd":
        divisions = record["divisions"]
        node, lattice, base = cmds.lattice(*members, divisions=divisions, objectCentered=True, name=name)
        lattice = _apply_xform(cmds.ls(lattice, long=True)[0], record["lattice"])
        _apply_xform(cmds.ls(base, long=True)[0], record["base"])
        shape = _shape(lattice, "lattice")
        for i, point in enumerate(record["points"]):
            cmds.setAttr(f"{shape}.controlPoints[{i}]", *point)
    else:  # wire
        curves = [found[w["curve"]] for w in record["wires"]]
        node = cmds.wire(*members, wire=curves, name=name)[0]
        for i, wire in zip(_wire_indices(node), record["wires"]):
            cmds.setAttr(f"{node}.dropoffDistance[{i}]", wire["dropoff"])
            cmds.setAttr(f"{node}.scale[{i}]", wire["scale"])
            base = _source(f"{node}.baseWire[{i}]")
            for cv, point in enumerate(wire["base_points"]):
                cmds.xform(f"{base}.cv[{cv}]", worldSpace=True, translation=point)

    if node_type in _HANDLED:
        handle = _apply_xform(cmds.ls(handle, long=True)[0], record["handle"])
        if "origin" in record["handle"]:
            shape = cmds.listRelatives(handle, shapes=True, fullPath=True)[0]
            cmds.setAttr(f"{shape}.origin", *record["handle"]["origin"])
        if record.get("bind_pre_matrix"):
            cmds.setAttr(f"{node}.bindPreMatrix", record["bind_pre_matrix"], type="matrix")
    for attr, value in record["settings"].items():
        if cmds.attributeQuery(attr, node=node, exists=True) and cmds.getAttr(f"{node}.{attr}", settable=True):
            cmds.setAttr(f"{node}.{attr}", value)
    for geometry, shape in zip(record["geometry"], shapes):
        weightmaps.write_weights(node, weightmaps.geometry_index(node, shape), geometry["weights"])
    return node


class DeformersProduct(data.DataProduct):
    name = "Deformers"
    utility = "Deformer Tool"
    kind = "deformers"
    extension = ".dfm"
    order = 82
    menu_slot = (3, 3)

    def selection_problems(self):
        selection = cmds.ls(selection=True)
        if not selection:
            return ["Nothing selected. Select the meshes with deformers to publish."]
        transforms = _mesh_transforms(selection)
        if not transforms:
            return ["No meshes selected. Select the meshes with deformers to publish."]
        without = [short_name(t) for t in transforms if not weightmaps.deformers_on(_shape(t), _TYPES)]
        if without:
            return [f"No cluster, softMod, wire, lattice or nonLinear deformer on: {', '.join(without)}"]
        return []

    def gather(self, selection):
        meshes = {}  # deformer -> [(transform, shape)], in evaluation order
        for transform in _mesh_transforms(selection):
            shape = _shape(transform)
            for node in weightmaps.deformers_on(shape, _TYPES):
                meshes.setdefault(node, []).append((transform, shape))
        if not meshes:
            raise RuntimeError("No cluster, softMod, wire, lattice or nonLinear deformer on the selected meshes.")
        return {"deformers": [_record(node, found) for node, found in meshes.items()]}

    def apply(self, payload):
        records = _skip_missing(payload["deformers"])
        found = _check(records)
        created = []
        for record in records:
            created.append(_rebuild(record, found))
            meshes = ", ".join(g["mesh"] for g in record["geometry"])
            runlog.info(f"{created[-1]} ({_type_label(record)}): created on {meshes}")
        if not created:
            return "Created no deformers"
        meshes = ", ".join(dict.fromkeys(g["mesh"] for r in records for g in r["geometry"]))
        return f"Created {'deformer' if len(created) == 1 else 'deformers'} {', '.join(created)} on {meshes}"

    def describe(self, payload):
        records = payload["deformers"]
        listed = ", ".join(f"{r['name']} ({_type_label(r)})" for r in records)
        lines = [f"{data.plural(len(records), 'deformer')}: {listed}"]
        lines.append(f"Meshes: {', '.join(dict.fromkeys(g['mesh'] for r in records for g in r['geometry']))}")
        curves = list(dict.fromkeys(w["curve"] for r in records for w in r.get("wires", ())))
        if curves:
            lines.append(f"Wire curves: {', '.join(curves)}")
        return lines


PRODUCT = DeformersProduct()
