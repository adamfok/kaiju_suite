"""BlendShapes (.bshp): blendShape nodes saved as data and rebuilt by name.

Publish saves every blendShape on the selected meshes: envelope, base
weights, and per target its name, weight, per-vertex weights and the sparse
deltas of each in-between (item 5000-6000; 6000 is the full target). A target
still connected to a sculpt mesh is saved from that mesh, so the file never
needs target geometry.

Run skips, with a warning, the blendShapes whose base mesh is missing. It
checks the other base meshes have the saved vertex count, then
replaces any blendShape with the same name by a new one made at the front of
the deformer chain (under a skin, whatever order the steps run in), and
writes the targets straight into its ``inputTarget`` attributes.
"""

import re

from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.core.selection import short_name
from kaiju_suite.tools.assembler import data, runlog

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
    """``{shape: transform}`` for the selected meshes, in selection order."""
    found = {}
    for node in selection:
        shape = _shape(node)
        if shape and shape not in found:
            found[shape] = cmds.listRelatives(shape, parent=True, fullPath=True)[0]
    return found


def _blendshapes_on(shape):
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


def _record(node, transform, shape):
    deformed = cmds.blendShape(node, query=True, geometry=True) or []
    if len(deformed) != 1:
        raise RuntimeError(f"{node} deforms several meshes ({', '.join(deformed)}); only one per blendShape is supported.")
    (geo,) = cmds.blendShape(node, query=True, geometryIndices=True)
    target_root = f"{node}.inputTarget[{geo}]"
    base_points = _mesh_points(_plug(f"{node}.input[{geo}].inputGeometry").asMObject())

    targets = []
    for index in cmds.getAttr(f"{node}.weight", multiIndices=True) or []:
        group = f"{target_root}.inputTargetGroup[{index}]"
        items = []
        for item in cmds.getAttr(f"{group}.inputTargetItem", multiIndices=True) or []:
            item_plug = f"{group}.inputTargetItem[{item}]"
            found = _live_deltas(item_plug, base_points) or _stored_deltas(item_plug)
            items.append({"item": item, "indices": found[0], "deltas": found[1]})
        targets.append(
            {
                "name": cmds.aliasAttr(f"{node}.weight[{index}]", query=True) or f"weight[{index}]",
                "index": index,
                "weight": cmds.getAttr(f"{node}.weight[{index}]"),
                "weights": _sparse(f"{group}.targetWeights"),
                "items": items,
            }
        )
    return {
        "name": short_name(node),
        "mesh": short_name(transform),
        "vertex_count": cmds.polyEvaluate(shape, vertex=True),
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
        count = cmds.polyEvaluate(mesh, vertex=True)
        if count != record["vertex_count"]:
            problems.append(f"{record['mesh']} has {count} vertices, {record['name']} needs {record['vertex_count']}")
        name = record["name"]
        if cmds.objExists(name) and cmds.nodeType(name) != "blendShape":
            problems.append(f"{name} is already the name of a {cmds.nodeType(name)} node")
    if problems:
        raise RuntimeError(f"Can't apply blendShapes: {'; '.join(problems)}.")


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


class BlendShapeProduct(data.DataProduct):
    name = "BlendShapes"
    utility = "BlendShape Tool"
    kind = "blendshape"
    extension = ".bshp"
    order = 80

    def _problems(self, selection):
        if not selection:
            return ["Nothing selected. Select the meshes whose blendShapes to publish."]
        meshes = _selected_meshes(selection)
        if not meshes:
            return ["No meshes selected. Select the meshes whose blendShapes to publish."]
        without = [short_name(t) for s, t in meshes.items() if not _blendshapes_on(s)]
        if without:
            return [f"No blendShape on: {', '.join(without)}"]
        return []

    def selection_problems(self):
        return self._problems(cmds.ls(selection=True, long=True) or [])

    def gather(self, selection):
        problems = self._problems(selection)
        if problems:
            raise RuntimeError(problems[0])
        records, seen = [], set()
        for shape, transform in _selected_meshes(selection).items():
            for node in _blendshapes_on(shape):
                if node not in seen:
                    seen.add(node)
                    records.append(_record(node, transform, shape))
        return {"blendshapes": records}

    def apply(self, payload):
        records = payload["blendshapes"]
        missing = data.skip_missing([r["mesh"] for r in records], "meshes")
        records = [r for r in records if r["mesh"] not in missing]
        _check(records)
        for record in records:
            _build(record)
            runlog.info(f"{record['name']}: built on {record['mesh']}, {data.plural(len(record['targets']), 'target')}")
        count = sum(len(r["targets"]) for r in records)
        return f"Built {data.plural(len(records), 'blendShape')} with {data.plural(count, 'target')}"

    def describe(self, payload):
        records = payload["blendshapes"]
        count = sum(len(r["targets"]) for r in records)
        meshes = list(dict.fromkeys(r["mesh"] for r in records))
        return [f"{data.plural(len(records), 'blendShape')}, {data.plural(count, 'target')}", f"Meshes: {', '.join(meshes)}"]


PRODUCT = BlendShapeProduct()
