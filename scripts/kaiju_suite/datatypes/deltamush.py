"""DeltaMush (.dmsh): deltaMush deformers saved as data and rebuilt on their meshes.

:func:`gather` saves every deltaMush on the given meshes: its settings and
its per-vertex weight map (sparse: only weights that aren't 1.0).
:func:`apply` finds the meshes by name, replaces a deltaMush of the same
name, and creates the new one after the mesh's existing deformers, so it
sits on top of skin. Missing meshes are skipped with a warning.

Gathering also saves each mesh's rest point positions. If a mesh's vertex
count changed since, applying gives each vertex the weight of the saved
vertex closest to it and warns. Files from before points were saved still
need the same vertex count.

:data:`CHECKS` are QC checks on the deltaMush nodes of given meshes (no
deltaMush, below skin, disabled, empty weights, duplicate mesh names), run
by the DeltaMush Tool's QC tab and before Builder publishes. They change
nothing.
"""

from maya import cmds
import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma

from kaiju_suite import datatypes
from kaiju_suite.core.checks import Check, Problem
from kaiju_suite.core.selection import short_name
from kaiju_suite.datatypes import mesh_shape, plural, short

KIND = "deltamush"
EXTENSION = ".dmsh"

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

# The Assembler's Wrap product imports these three by these names.
_shape = mesh_shape
_mesh_transforms = datatypes.meshes


def _mobject(node):
    return om.MSelectionList().add(node).getDependNode(0)


def _geometry_index(node, shape):
    """The index of ``shape`` in deformer ``node``'s geometry, or ``None``."""
    try:
        return oma.MFnGeometryFilter(_mobject(node)).indexForOutputShape(_mobject(shape))
    except RuntimeError:
        return None


def _deformers(shape, node_types):
    """The deformers of ``node_types`` deforming ``shape``, first evaluated first."""
    history = cmds.ls(cmds.listHistory(shape) or [], type=node_types) or []
    return [n for n in reversed(history) if _geometry_index(n, shape) is not None]


def _deltamushes(shape):
    """The deltaMush nodes deforming ``shape``, first evaluated first."""
    return _deformers(shape, "deltaMush")


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
    record["points"] = datatypes.saved_points(transform)
    return record


def _remapped(record, transform):
    """``record``, or a copy with its weights moved onto the mesh's current
    vertices by closest point if the vertex count changed."""
    mapping = datatypes.vertex_remap(record, transform, _label(record), "deltaMush weights")
    if mapping is None:
        return record
    saved = {vertex: weight for vertex, weight in record["weights"]}
    weights = [[v, saved[m]] for v, m in enumerate(mapping) if m in saved]
    return dict(record, vertex_count=len(mapping), weights=weights)


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
        problem = datatypes.count_problem(record, transform, record["mesh"])
        if problem:
            problems.append(problem)
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


def _label(record):
    return f"{record['name']} on {record['mesh']}"


# -- the datatype -----------------------------------------------------------


def selection_problems(selection):
    """Why ``selection`` can't be gathered, as messages."""
    if not selection:
        return ["Nothing selected. Select the meshes with a deltaMush to publish."]
    transforms = _mesh_transforms(selection)
    if not transforms:
        return ["No meshes selected. Select the meshes with a deltaMush to publish."]
    without = [short_name(t) for t in transforms if not _deltamushes(_shape(t))]
    if without:
        return [f"No deltaMush on: {', '.join(without)}"]
    return []


def gather(nodes):
    """Every deltaMush on the meshes among ``nodes``."""
    records = []
    for transform in _mesh_transforms(nodes):
        shape = _shape(transform)
        records.extend(_record(node, transform, shape) for node in _deltamushes(shape))
    if not records:
        raise RuntimeError("No deltaMush on the selected meshes to publish.")
    return {"deltamush": records}


def apply(payload, info=None):
    """Rebuild each saved deltaMush on its meshes; returns a message."""
    records = payload["deltamush"]
    missing = datatypes.skip_missing([r["mesh"] for r in records], "meshes")
    records = [r for r in records if r["mesh"] not in missing]
    transforms = _check(records)
    records = [_remapped(r, transforms[r["mesh"]]) for r in records]
    created = []
    for name, group in _groups(records).items():
        created.append(_rebuild(name, group, transforms))
        datatypes.report(info, f"{created[-1]}: created on {', '.join(r['mesh'] for r in group)}")
    if not created:
        return "Created no deltaMush nodes"
    meshes = ", ".join(dict.fromkeys(r["mesh"] for r in records))
    noun = "deltaMush" if len(created) == 1 else "deltaMush nodes"
    return f"Created {noun} {', '.join(created)} on {meshes}"


def nodes(payload):
    return [r["mesh"] for r in payload["deltamush"]]


def describe(payload):
    records = payload["deltamush"]
    count = len(_groups(records))
    meshes = ", ".join(dict.fromkeys(r["mesh"] for r in records))
    return [f"{plural(count, 'deltaMush node')}", f"Meshes: {meshes}"]


def compare_view(payload):
    """One weight per vertex (the ones not saved are 1.0), without the rest
    points (saved for remapping after a topology change, not deltaMush data)."""

    def dense(record):
        weights = [1.0] * record["vertex_count"]
        for vertex, weight in record["weights"]:
            weights[vertex] = weight
        return {**{k: v for k, v in record.items() if k != "points"}, "weights": weights}

    return {**payload, "deltamush": [dense(r) for r in payload["deltamush"]]}


# -- QC checks --------------------------------------------------------------


def _mushed(nodes):
    """``(mesh, shape, deltaMush)`` for each deltaMush on the meshes among ``nodes``."""
    found = []
    for mesh in _mesh_transforms(nodes):
        shape = _shape(mesh)
        found.extend((mesh, shape, node) for node in _deltamushes(shape))
    return found


def _on(node, mesh):
    return f"{node} on {short(mesh)}"


def _check_missing(nodes):
    return [Problem(f"{short(m)}: no deltaMush", [short(m)]) for m in _mesh_transforms(nodes) if not _deltamushes(_shape(m))]


def _check_below_skin(nodes):
    problems = []
    for mesh, shape, node in _mushed(nodes):
        order = _deformers(shape, ["skinCluster", "deltaMush"])
        later = [n for n in order[order.index(node) + 1 :] if cmds.nodeType(n) == "skinCluster"]
        if later:
            problems.append(Problem(f"{_on(node, mesh)}: evaluates before {', '.join(later)}", [node]))
    return problems


def _check_disabled(nodes):
    problems = []
    for mesh, _, node in _mushed(nodes):
        why = []
        envelope = cmds.getAttr(f"{node}.envelope")
        if envelope == 0:
            why.append("envelope is 0")
        if cmds.getAttr(f"{node}.nodeState") != 0:
            why.append(f"node state is {cmds.getAttr(f'{node}.nodeState', asString=True)}")
        if why:
            problems.append(Problem(f"{_on(node, mesh)}: {', '.join(why)}", [node]))
    return problems


def _check_empty_weights(nodes):
    problems = []
    for mesh, shape, node in _mushed(nodes):
        count = cmds.polyEvaluate(shape, vertex=True)
        sparse = dict(map(tuple, _read_weights(node, _geometry_index(node, shape), count)))
        # Weights not in ``sparse`` are 1.0.
        if len(sparse) == count and not any(sparse.values()):
            problems.append(Problem(f"{_on(node, mesh)}: every weight is 0", [node]))
    return problems


def _check_duplicate_names(nodes):
    problems = []
    for mesh in _mesh_transforms(nodes):
        name = short_name(mesh)
        same = sorted(cmds.ls(name) or [])
        if len(same) > 1:
            problems.append(Problem(f"{short(mesh)}: {len(same)} nodes are called {name}", same))
    return problems


CHECKS = (
    Check("missing", "No deltaMush", "Selected meshes with no deltaMush.", _check_missing),
    Check(
        "below_skin",
        "Below skin",
        "DeltaMush nodes that evaluate before the mesh's skinCluster; a deltaMush should sit on top of skin.",
        _check_below_skin,
    ),
    Check(
        "disabled",
        "Disabled",
        "DeltaMush nodes with an envelope of 0, or a node state other than Normal.",
        _check_disabled,
    ),
    Check(
        "empty_weights",
        "Empty weights",
        "DeltaMush nodes whose every weight on the mesh is 0, so they do nothing.",
        _check_empty_weights,
    ),
    Check(
        "duplicate_names",
        "Duplicate names",
        "Meshes whose name another node also has; DeltaMush items find meshes by name.",
        _check_duplicate_names,
    ),
)
