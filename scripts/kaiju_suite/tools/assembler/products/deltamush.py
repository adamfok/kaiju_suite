"""DeltaMush (.dmsh): deltaMush deformers saved as data and rebuilt on their meshes.

Publish saves every deltaMush on the selected meshes: its settings and its
per-vertex weight map (sparse: only weights that aren't 1.0). Run finds the
meshes by name, replaces a deltaMush of the same name, and creates the new one
after the mesh's existing deformers, so it sits on top of skin. Missing
meshes are skipped with a warning.
"""

from maya import cmds
import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma

from kaiju_suite.core.selection import short_name
from kaiju_suite.tools.assembler import data, runlog

# Saved settings, with the type each is stored as.
_SETTINGS = (
    ("smoothingIterations", int),
    ("smoothingStep", float),
    ("inwardConstraint", float),
    ("outwardConstraint", float),
    ("distanceWeight", float),
    ("displacement", float),
    ("pinBorderVertices", bool),
    ("envelope", float),
)
_DIGITS = 6


def _shape(transform):
    """The visible mesh shape of ``transform`` (long name), or ``None``."""
    shapes = cmds.listRelatives(transform, shapes=True, noIntermediate=True, type="mesh", fullPath=True)
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


def _mobject(node):
    return om.MSelectionList().add(node).getDependNode(0)


def _geometry_index(node, shape):
    """The index of ``shape`` in deformer ``node``'s geometry, or ``None``."""
    try:
        return oma.MFnGeometryFilter(_mobject(node)).indexForOutputShape(_mobject(shape))
    except RuntimeError:
        return None


def _deltamushes(shape):
    """The deltaMush nodes deforming ``shape``, first evaluated first."""
    history = cmds.ls(cmds.listHistory(shape) or [], type="deltaMush") or []
    return [n for n in reversed(history) if _geometry_index(n, shape) is not None]


def _weights_plug(node, index):
    fn = om.MFnDependencyNode(_mobject(node))
    return fn.findPlug("weightList", False).elementByLogicalIndex(index).child(fn.attribute("weights"))


def _read_weights(node, index, vertex_count):
    """Sparse ``[vertex, weight]`` pairs of the weights that aren't 1.0."""
    plug = _weights_plug(node, index)
    weights = []
    for i in range(plug.numElements()):
        element = plug.elementByPhysicalIndex(i)
        vertex = element.logicalIndex()
        weight = round(element.asDouble(), _DIGITS)
        if vertex < vertex_count and weight != 1.0:
            weights.append([vertex, weight])
    return sorted(weights)


def _record(node, transform, shape):
    vertex_count = cmds.polyEvaluate(shape, vertex=True)
    record = {"name": node, "mesh": short_name(transform), "vertex_count": vertex_count}
    for attr, kind in _SETTINGS:
        value = kind(cmds.getAttr(f"{node}.{attr}"))
        record[attr] = round(value, _DIGITS) if kind is float else value
    record["weights"] = _read_weights(node, _geometry_index(node, shape), vertex_count)
    return record


def _check(records):
    """Map each mesh name to its transform, raising before anything changes
    if a mesh is ambiguous, a vertex count differs, or a node's name is
    taken by something other than a deltaMush on its meshes."""
    meshes = list(dict.fromkeys(r["mesh"] for r in records))
    transforms, problems = {}, []
    for name in meshes:
        matches = [m for m in cmds.ls(name, long=True) if cmds.objectType(m, isAType="transform") and _shape(m)]
        if len(matches) != 1:
            found = ", ".join(matches) if matches else "no mesh"
            problems.append(f"{name} doesn't name exactly one mesh ({found})")
        else:
            transforms[name] = matches[0]
    for record in records:
        transform = transforms.get(record["mesh"])
        if transform is None:
            continue
        count = cmds.polyEvaluate(_shape(transform), vertex=True)
        if count != record["vertex_count"]:
            problems.append(f"{record['mesh']} has {count} vertices, the file has {record['vertex_count']}")
    if problems:
        raise RuntimeError(f"Can't apply DeltaMush: {'; '.join(dict.fromkeys(problems))}")

    taken = []
    for name, group in _groups(records).items():
        if not cmds.objExists(name):
            continue
        shapes = [_shape(transforms[r["mesh"]]) for r in group]
        is_ours = cmds.nodeType(name) == "deltaMush" and any(_geometry_index(name, s) is not None for s in shapes)
        if not is_ours:
            taken.append(name)
    if taken:
        raise RuntimeError(f"Names taken by other nodes, not a deltaMush on the same mesh: {', '.join(taken)}")
    return transforms


def _groups(records):
    """Records by deltaMush name, in file order: one node may deform several meshes."""
    groups = {}
    for record in records:
        groups.setdefault(record["name"], []).append(record)
    return groups


def _rebuild(name, group, transforms):
    if cmds.objExists(name):
        cmds.delete(name)
    shapes = [_shape(transforms[r["mesh"]]) for r in group]
    # Maya appends a new deformer after the existing ones, so it sits on top
    # of skin. (The ``after`` flag would add a new output shape instead.)
    node = cmds.deltaMush(*shapes, name=name)[0]
    for attr, _kind in _SETTINGS:
        cmds.setAttr(f"{node}.{attr}", group[0][attr])
    for record, shape in zip(group, shapes):
        index = _geometry_index(node, shape)
        for vertex, weight in record["weights"]:
            cmds.setAttr(f"{node}.weightList[{index}].weights[{vertex}]", weight)
    return node


class DeltaMushProduct(data.DataProduct):
    name = "DeltaMush"
    utility = "DeltaMush Tool"
    kind = "deltamush"
    extension = ".dmsh"
    order = 70
    menu_slot = (3, 1)

    def selection_problems(self):
        selection = cmds.ls(selection=True)
        if not selection:
            return ["Nothing selected. Select the meshes with a deltaMush to publish."]
        transforms = _mesh_transforms(selection)
        if not transforms:
            return ["No meshes selected. Select the meshes with a deltaMush to publish."]
        without = [short_name(t) for t in transforms if not _deltamushes(_shape(t))]
        if without:
            return [f"No deltaMush on: {', '.join(without)}"]
        return []

    def gather(self, selection):
        records = []
        for transform in _mesh_transforms(selection):
            shape = _shape(transform)
            records.extend(_record(node, transform, shape) for node in _deltamushes(shape))
        if not records:
            raise RuntimeError("No deltaMush on the selected meshes to publish.")
        return {"deltamush": records}

    def apply(self, payload):
        records = payload["deltamush"]
        missing = data.skip_missing([r["mesh"] for r in records], "meshes")
        records = [r for r in records if r["mesh"] not in missing]
        transforms = _check(records)
        created = []
        for name, group in _groups(records).items():
            created.append(_rebuild(name, group, transforms))
            runlog.info(f"{created[-1]}: created on {', '.join(r['mesh'] for r in group)}")
        if not created:
            return "Created no deltaMush nodes"
        meshes = ", ".join(dict.fromkeys(r["mesh"] for r in records))
        noun = "deltaMush" if len(created) == 1 else "deltaMush nodes"
        return f"Created {noun} {', '.join(created)} on {meshes}"

    def describe(self, payload):
        records = payload["deltamush"]
        count = len(_groups(records))
        meshes = ", ".join(dict.fromkeys(r["mesh"] for r in records))
        return [f"{count} deltaMush node{'s' if count != 1 else ''}", f"Meshes: {meshes}"]


PRODUCT = DeltaMushProduct()
