"""BlendShapes (.bshp): blendShape nodes saved as data and rebuilt by name.

:func:`gather` saves every blendShape on the given meshes: envelope, base
weights, and per target its name, weight, per-vertex weights and the sparse
deltas of each in-between (item 5000-6000; 6000 is the full target). A target
still connected to a sculpt mesh is saved from that mesh, so the file never
needs target geometry. Pose readers and whatever drives a target's weight
aren't saved.

:func:`apply` skips, with a warning, the blendShapes whose base mesh is
missing. It checks the other base meshes have the saved vertex count, then
replaces any blendShape with the same name by a new one made at the front of
the deformer chain (under a skin, whatever order things run in), and writes
the targets straight into its ``inputTarget`` attributes.

Gathering also saves the base mesh's rest point positions. If its vertex
count changed since, applying gives each vertex the deltas and weights of
the saved vertex closest to it and warns. Files from before points were
saved still need the same vertex count.

:data:`CHECKS` are QC checks on the blendShapes of given meshes (no
blendShape, above skin, empty targets, duplicate names), run by the
BlendShape Tool's QC tab and before Scripter publishes. They change nothing.
"""

import re

from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite import datatypes
from kaiju_suite.core.checks import Check, Problem
from kaiju_suite.core.selection import short_name
from kaiju_suite.datatypes import plural, short

KIND = "blendshape"
EXTENSION = ".bshp"

# Deltas shorter than this, computed from a live sculpt mesh, aren't saved.
_TOLERANCE = 1e-6

_COMPONENT = re.compile(r"\[(\d+)(?::(\d+))?\]")


def _plug(name):
    sel = om.MSelectionList()
    sel.add(name)
    return sel.getPlug(0)


def _shape(node):
    """The visible mesh shape of ``node`` (a mesh transform or shape), or ``None``."""
    if cmds.nodeType(node) == "mesh":
        return None if cmds.getAttr(f"{node}.intermediateObject") else cmds.ls(node, long=True)[0]
    shapes = cmds.listRelatives(node, shapes=True, type="mesh", noIntermediate=True, fullPath=True)
    return shapes[0] if shapes else None


def _selected_meshes(selection):
    """``{shape: transform}`` for the meshes in ``selection``, in order."""
    found = {}
    for node in cmds.ls(selection, objectsOnly=True, long=True) or []:
        shape = _shape(node)
        if shape and shape not in found:
            found[shape] = cmds.listRelatives(shape, parent=True, fullPath=True)[0]
    return found


def blendshapes_on(shape):
    """The blendShape nodes deforming ``shape``, nearest the original first."""
    history = cmds.listHistory(shape, pruneDagObjects=True) or []
    found = []
    for node in reversed(cmds.ls(history, type="blendShape")):
        deformed = cmds.ls(cmds.blendShape(node, query=True, geometry=True) or [], long=True)
        if shape in deformed:
            found.append(node)
    return found


def _sparse(plug_name, default=1.0):
    """``{"index": value}`` for the elements of a float multi that differ from ``default``."""
    plug = _plug(plug_name)
    found = {}
    for i in range(plug.numElements()):
        element = plug.elementByPhysicalIndex(i)
        value = element.asFloat()
        if abs(value - default) > 1e-9:
            found[str(element.logicalIndex())] = value
    return found


def _components(names):
    """Vertex indices from component strings like ``vtx[0:3]``."""
    indices = []
    for name in names or []:
        match = _COMPONENT.search(name)
        if match:
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else start
            indices.extend(range(start, end + 1))
    return indices


def _ranges(indices):
    """Sorted ``indices`` as ``(first, last)`` runs of consecutive numbers."""
    runs = []
    for index in sorted(indices):
        if runs and index == runs[-1][1] + 1:
            runs[-1][1] = index
        else:
            runs.append([index, index])
    return runs


def _mesh_points(mobject_or_path):
    return om.MFnMesh(mobject_or_path).getPoints(om.MSpace.kObject)


def _live_deltas(item_plug, base_points):
    """Sparse deltas of the sculpt mesh connected to an item, or ``None`` if
    nothing is connected."""
    sources = cmds.listConnections(f"{item_plug}.inputGeomTarget", source=True, destination=False, shapes=True)
    if not sources:
        return None
    sel = om.MSelectionList()
    sel.add(sources[0])
    target = _mesh_points(sel.getDagPath(0))
    if len(target) != len(base_points):
        raise RuntimeError(f"Target mesh {sources[0]} doesn't have the same vertex count as its base.")
    indices, deltas = [], []
    for index, (t, b) in enumerate(zip(target, base_points)):
        delta = t - b
        if delta.length() > _TOLERANCE:
            indices.append(index)
            deltas.append([delta.x, delta.y, delta.z])
    return indices, deltas


def _stored_deltas(item_plug):
    indices = _components(cmds.getAttr(f"{item_plug}.inputComponentsTarget"))
    points = cmds.getAttr(f"{item_plug}.inputPointsTarget") or []
    if len(indices) != len(points):
        raise RuntimeError(f"{item_plug} has {len(indices)} components but {len(points)} points.")
    return indices, [list(p[:3]) for p in points]


def _base_points(node, geo):
    return _mesh_points(_plug(f"{node}.input[{geo}].inputGeometry").asMObject())


def _target_name(node, index):
    return cmds.aliasAttr(f"{node}.weight[{index}]", query=True) or f"weight[{index}]"


def _target_items(node, geo, index, base_points):
    """``[{"item", "indices", "deltas"}]`` for target ``index`` of ``node``'s
    geometry ``geo``: each in-between's sparse deltas."""
    group = f"{node}.inputTarget[{geo}].inputTargetGroup[{index}]"
    items = []
    for item in cmds.getAttr(f"{group}.inputTargetItem", multiIndices=True) or []:
        item_plug = f"{group}.inputTargetItem[{item}]"
        found = _live_deltas(item_plug, base_points) or _stored_deltas(item_plug)
        items.append({"item": item, "indices": found[0], "deltas": found[1]})
    return items


def _record(node, transform, shape):
    deformed = cmds.blendShape(node, query=True, geometry=True) or []
    if len(deformed) != 1:
        raise RuntimeError(f"{node} deforms several meshes ({', '.join(deformed)}); only one per blendShape is supported.")
    (geo,) = cmds.blendShape(node, query=True, geometryIndices=True)
    target_root = f"{node}.inputTarget[{geo}]"
    base_points = _base_points(node, geo)

    targets = []
    for index in cmds.getAttr(f"{node}.weight", multiIndices=True) or []:
        group = f"{target_root}.inputTargetGroup[{index}]"
        targets.append(
            {
                "name": _target_name(node, index),
                "index": index,
                "weight": cmds.getAttr(f"{node}.weight[{index}]"),
                "weights": _sparse(f"{group}.targetWeights"),
                "items": _target_items(node, geo, index, base_points),
            }
        )
    return {
        "name": short_name(node),
        "mesh": short_name(transform),
        "vertex_count": cmds.polyEvaluate(shape, vertex=True),
        "points": datatypes.saved_points(transform),
        "envelope": cmds.getAttr(f"{node}.envelope"),
        "base_weights": _sparse(f"{target_root}.baseWeights"),
        "targets": targets,
    }


def _set_sparse(plug_name, values):
    """Set the ``{"index": value}`` elements of a float multi, one setAttr per run."""
    by_index = {int(i): v for i, v in values.items()}
    for first, last in _ranges(by_index):
        cmds.setAttr(f"{plug_name}[{first}:{last}]", *[by_index[i] for i in range(first, last + 1)])


def _find_mesh(name):
    """The single mesh transform called ``name``; raises a message otherwise."""
    matches = cmds.ls(name, long=True) or []
    if len(matches) > 1:
        return None, f"several nodes are called {name} ({', '.join(matches)})"
    if not _shape(matches[0]):
        return None, f"{name} is not a mesh"
    return matches[0], None


def _check(records):
    """Raise, before anything changes, if any record can't be applied."""
    problems = []
    for record in records:
        mesh, problem = _find_mesh(record["mesh"])
        if problem:
            problems.append(problem)
            continue
        problem = datatypes.count_problem(record, mesh, record["mesh"])
        if problem:
            problems.append(problem)
        name = record["name"]
        if cmds.objExists(name) and cmds.nodeType(name) != "blendShape":
            problems.append(f"{name} is already the name of a {cmds.nodeType(name)} node")
    if problems:
        raise RuntimeError(f"Can't apply blendShapes: {'; '.join(problems)}.")


def _remap_sparse(values, mapping):
    """``{"index": value}`` moved onto new vertices: each takes its saved match's value."""
    return {str(v): values[str(m)] for v, m in enumerate(mapping) if str(m) in values}


def _remapped(record):
    """``record``, or a copy with its deltas and weights moved onto the
    mesh's current vertices by closest point if the vertex count changed."""
    mesh, _ = _find_mesh(record["mesh"])
    mapping = datatypes.vertex_remap(record, mesh, f"{record['name']} on {record['mesh']}", "blendShape deltas")
    if mapping is None:
        return record
    targets = []
    for target in record["targets"]:
        items = []
        for item in target["items"]:
            saved = dict(zip(item["indices"], item["deltas"]))
            indices = [v for v, m in enumerate(mapping) if m in saved]
            items.append(dict(item, indices=indices, deltas=[saved[mapping[v]] for v in indices]))
        targets.append(dict(target, items=items, weights=_remap_sparse(target["weights"], mapping)))
    return dict(
        record,
        vertex_count=len(mapping),
        targets=targets,
        base_weights=_remap_sparse(record["base_weights"], mapping),
    )


def _build(record):
    name = record["name"]
    if cmds.objExists(name):
        cmds.delete(name)
    mesh, _ = _find_mesh(record["mesh"])
    node = cmds.blendShape(mesh, frontOfChain=True, name=name)[0]
    root = f"{node}.inputTarget[0]"
    for target in record["targets"]:
        index = target["index"]
        group = f"{root}.inputTargetGroup[{index}]"
        for item in target["items"]:
            item_plug = f"{group}.inputTargetItem[{item['item']}]"
            points = [(x, y, z, 1.0) for x, y, z in item["deltas"]]
            components = [f"vtx[{a}]" if a == b else f"vtx[{a}:{b}]" for a, b in _ranges(item["indices"])]
            cmds.setAttr(f"{item_plug}.inputPointsTarget", len(points), *points, type="pointArray")
            cmds.setAttr(f"{item_plug}.inputComponentsTarget", len(components), *components, type="componentList")
        cmds.setAttr(f"{node}.weight[{index}]", target["weight"])
        if not target["name"].startswith("weight["):
            cmds.aliasAttr(target["name"], f"{node}.weight[{index}]")
        _set_sparse(f"{group}.targetWeights", target["weights"])
    _set_sparse(f"{root}.baseWeights", record["base_weights"])
    cmds.setAttr(f"{node}.envelope", record["envelope"])
    return node


# -- the datatype -----------------------------------------------------------


def selection_problems(selection):
    """Why ``selection`` can't be gathered, as messages."""
    if not selection:
        return ["Nothing selected. Select the meshes whose blendShapes to publish."]
    meshes = _selected_meshes(selection)
    if not meshes:
        return ["No meshes selected. Select the meshes whose blendShapes to publish."]
    without = [short_name(t) for s, t in meshes.items() if not blendshapes_on(s)]
    if without:
        return [f"No blendShape on: {', '.join(without)}"]
    return []


def gather(nodes):
    """The blendShapes on the meshes among ``nodes``."""
    problems = selection_problems(nodes)
    if problems:
        raise RuntimeError(problems[0])
    records, seen = [], set()
    for shape, transform in _selected_meshes(nodes).items():
        for node in blendshapes_on(shape):
            if node not in seen:
                seen.add(node)
                records.append(_record(node, transform, shape))
    return {"blendshapes": records}


def apply(payload, info=None):
    """Build each saved blendShape on its mesh; returns a message."""
    records = payload["blendshapes"]
    missing = datatypes.skip_missing([r["mesh"] for r in records], "meshes")
    records = [r for r in records if r["mesh"] not in missing]
    _check(records)
    for record in records:
        _build(_remapped(record))
        datatypes.report(info, f"{record['name']}: built on {record['mesh']}, {plural(len(record['targets']), 'target')}")
    count = sum(len(r["targets"]) for r in records)
    return f"Built {plural(len(records), 'blendShape')} with {plural(count, 'target')}"


def nodes(payload):
    return [r["mesh"] for r in payload["blendshapes"]]


def describe(payload):
    records = payload["blendshapes"]
    count = sum(len(r["targets"]) for r in records)
    meshes = list(dict.fromkeys(r["mesh"] for r in records))
    return [f"{plural(len(records), 'blendShape')}, {plural(count, 'target')}", f"Meshes: {', '.join(meshes)}"]


def compare_view(payload):
    """Without the rest points (saved for remapping, not blendShape data)."""
    records = [{k: v for k, v in r.items() if k != "points"} for r in payload["blendshapes"]]
    return {**payload, "blendshapes": records}


# -- QC checks --------------------------------------------------------------


def _meshes(nodes):
    """``(shape, transform)`` for the meshes among ``nodes``."""
    return list(_selected_meshes(nodes).items()) if nodes else []


def _check_has_blendshape(nodes):
    return [Problem(f"{short(t)}: no blendShape", [short(t)]) for s, t in _meshes(nodes) if not blendshapes_on(s)]


def _check_order(nodes):
    problems = []
    for shape, transform in _meshes(nodes):
        # History runs from the shape back up the chain: what evaluates last comes first.
        history = cmds.ls(cmds.listHistory(shape, pruneDagObjects=True) or [], type=("blendShape", "skinCluster"))
        skins = [i for i, node in enumerate(history) if cmds.nodeType(node) == "skinCluster"]
        if not skins:
            continue
        for node in history[: skins[-1]]:
            if cmds.nodeType(node) == "blendShape" and node in blendshapes_on(shape):
                skin = history[skins[-1]]
                problems.append(
                    Problem(
                        f"{short(transform)}: {node} evaluates after {skin}; it should be at the front of the chain",
                        [short(transform)],
                    )
                )
    return problems


def _is_empty(items):
    return not any(
        any(sum(c * c for c in delta) > _TOLERANCE * _TOLERANCE for delta in item["deltas"]) for item in items
    )


def _check_empty_targets(nodes):
    problems = []
    for shape, transform in _meshes(nodes):
        for node in blendshapes_on(shape):
            deformed = cmds.ls(cmds.blendShape(node, query=True, geometry=True) or [], long=True)
            geo = cmds.blendShape(node, query=True, geometryIndices=True)[deformed.index(shape)]
            base_points = _base_points(node, geo)
            empty = [
                _target_name(node, index)
                for index in cmds.getAttr(f"{node}.weight", multiIndices=True) or []
                if _is_empty(_target_items(node, geo, index, base_points))
            ]
            if empty:
                problems.append(
                    Problem(
                        f"{short(transform)}: {node} has {plural(len(empty), 'empty target')}: {', '.join(empty)}",
                        [short(transform)],
                    )
                )
    return problems


def _check_duplicate_names(nodes):
    problems = []
    for _, transform in _meshes(nodes):
        name = short_name(transform)
        same = sorted(cmds.ls(name) or [])
        if len(same) > 1:
            problems.append(Problem(f"{short(transform)}: {len(same)} nodes are called {name}", same))
    return problems


CHECKS = (
    Check("blendshape", "No blendShape", "Selected meshes with no blendShape.", _check_has_blendshape),
    Check(
        "order",
        "Above skin",
        "BlendShapes that evaluate after the skinCluster; they should be at the front of the deformer chain.",
        _check_order,
    ),
    Check("empty_targets", "Empty targets", "Targets with no deltas: they don't move any vertex.", _check_empty_targets),
    Check(
        "duplicate_names",
        "Duplicate names",
        "Meshes whose name another node also has; BlendShapes items find their base meshes by name.",
        _check_duplicate_names,
    ),
)
