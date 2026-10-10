"""SkinCluster (.skin): skin weights saved as data and bound back by name.

Publish saves each selected mesh's skinCluster: its name, influences (in
index order), settings and sparse weights (per vertex, ``[influence index,
weight]`` pairs without zeros), plus the dual quaternion blend weights when
the skinning method is weight blended.

Run finds the mesh and influences by name. A mesh that's missing, or whose
influences aren't all there, is skipped with a warning. It checks every
other mesh first (the vertex counts match) and raises before changing
anything. Then, per mesh, it removes the mesh's existing skinCluster, binds
exactly the file's influences under the saved name, and sets every weight
in one ``MFnSkinCluster.setWeights`` call. Remapping weights onto a changed
mesh is not supported: the vertex count must match.

``setWeights`` isn't on Maya's undo queue. Undo still reverts a Run (removing
the new skinCluster takes its weights with it), but redo rebinds with Maya's
default weights, not the saved ones: run the file again instead.
"""

from maya import cmds
from maya.api import OpenMaya as om
from maya.api import OpenMayaAnim as oma

from kaiju_suite.tools.assembler import compare, data, runlog

_WEIGHT_BLENDED = 2
# Decimals kept for weights: well below what a skin can show, and it keeps
# the file small and the same for the same weights.
_DECIMALS = 8


def _short(path):
    """The shortest unique name of ``path``, as Maya shows it."""
    return cmds.ls(path)[0]


def _shape(transform):
    """The (non-intermediate) mesh shape of ``transform``, or ``None``."""
    found = cmds.listRelatives(transform, shapes=True, noIntermediate=True, type="mesh", fullPath=True)
    return found[0] if found else None


def _selected_meshes(selection):
    """Transforms with a mesh shape among ``selection`` (transforms, shapes
    or components), in selection order, each once."""
    meshes = []
    for node in cmds.ls(selection, objectsOnly=True, long=True) or []:
        if cmds.nodeType(node) == "mesh":
            node = cmds.listRelatives(node, parent=True, fullPath=True)[0]
        if _shape(node) and node not in meshes:
            meshes.append(node)
    return meshes


def _skin_cluster(mesh):
    """The skinCluster deforming ``mesh``, or ``None``."""
    shape = _shape(mesh)
    found = cmds.ls(cmds.listHistory(shape) or [], type="skinCluster") if shape else []
    return found[0] if found else None


def _dag_path(node):
    return om.MSelectionList().add(node).getDagPath(0)


def _skin_fn(cluster):
    return oma.MFnSkinCluster(om.MSelectionList().add(cluster).getDependNode(0))


def _all_vertices(count):
    component = om.MFnSingleIndexedComponent()
    obj = component.create(om.MFn.kMeshVertComponent)
    component.setCompleteData(count)
    return obj


def _record(mesh):
    cluster = _skin_cluster(mesh)
    shape = _shape(mesh)
    fn = _skin_fn(cluster)
    path = _dag_path(shape)
    count = om.MFnMesh(path).numVertices
    vertices = _all_vertices(count)

    influences = [_short(p.fullPathName()) for p in fn.influenceObjects()]
    weights, per_vertex = fn.getWeights(path, vertices)
    sparse = []
    for v in range(count):
        row = []
        for i in range(per_vertex):
            w = round(weights[v * per_vertex + i], _DECIMALS)
            if w:
                row.append([i, w])
        sparse.append(row)

    record = {
        "mesh": _short(mesh),
        "skinCluster": cluster,
        "influences": influences,
        "vertex_count": count,
    }
    record["skinningMethod"] = int(cmds.getAttr(f"{cluster}.skinningMethod"))
    record["normalizeWeights"] = int(cmds.getAttr(f"{cluster}.normalizeWeights"))
    record["maxInfluences"] = int(cmds.getAttr(f"{cluster}.maxInfluences"))
    record["maintainMaxInfluences"] = bool(cmds.getAttr(f"{cluster}.maintainMaxInfluences"))
    record["weights"] = sparse
    if record["skinningMethod"] == _WEIGHT_BLENDED:
        blend = fn.getBlendWeights(path, vertices)
        record["blend_weights"] = [round(w, _DECIMALS) for w in blend]
    return record


def _unique(name, label):
    """The one node called ``name``; raises if several have that name."""
    found = cmds.ls(name, long=True)
    if len(found) > 1:
        raise RuntimeError(f"Several nodes are called {name}, can't tell which {label} to use: {', '.join(found)}")
    return found[0]


def _present(records):
    """The records whose mesh and influences are all in the scene. The rest
    are skipped with a warning: binding a mesh to only some of its
    influences would give it the wrong weights."""
    missing = data.skip_missing([r["mesh"] for r in records], "meshes")
    kept = []
    for record in records:
        if record["mesh"] in missing:
            continue
        absent = [name for name in dict.fromkeys(record["influences"]) if not cmds.objExists(name)]
        if absent:
            runlog.warning(f"Skipped {record['mesh']}: missing influences {', '.join(absent)}")
            continue
        kept.append(record)
    return kept


def _check(records):
    """Raise, before anything changes, if any record can't be applied."""
    problems = []
    for record in records:
        mesh = _unique(record["mesh"], "mesh")
        for name in record["influences"]:
            _unique(name, "influence")
        if not _shape(mesh):
            problems.append(f"{record['mesh']} has no mesh shape")
            continue
        count = cmds.polyEvaluate(mesh, vertex=True)
        if count != record["vertex_count"]:
            problems.append(f"{record['mesh']} has {count} vertices, the file has {record['vertex_count']}")
    if problems:
        raise RuntimeError(f"Can't apply skin weights: {'; '.join(problems)}.")


def _apply_record(record):
    mesh = _unique(record["mesh"], "mesh")
    old = _skin_cluster(mesh)
    if old:
        cmds.skinCluster(old, edit=True, unbind=True)

    influences = record["influences"]
    cluster = cmds.skinCluster(
        *influences,
        mesh,
        toSelectedBones=True,
        name=record["skinCluster"],
        normalizeWeights=1,
        maximumInfluences=len(influences),
        obeyMaxInfluences=False,
    )[0]
    # Weights are set as saved: no normalizing or pruning while setting them.
    cmds.setAttr(f"{cluster}.normalizeWeights", 0)
    cmds.setAttr(f"{cluster}.maintainMaxInfluences", False)

    count = record["vertex_count"]
    dense = om.MDoubleArray(count * len(influences), 0.0)
    for v, row in enumerate(record["weights"]):
        for i, w in row:
            dense[v * len(influences) + i] = w
    fn = _skin_fn(cluster)
    path = _dag_path(_shape(mesh))
    vertices = _all_vertices(count)
    fn.setWeights(path, vertices, om.MIntArray(list(range(len(influences)))), dense, False)

    cmds.setAttr(f"{cluster}.skinningMethod", record["skinningMethod"])
    if "blend_weights" in record:
        fn.setBlendWeights(path, vertices, om.MDoubleArray(record["blend_weights"]))
    cmds.setAttr(f"{cluster}.maxInfluences", record["maxInfluences"])
    cmds.setAttr(f"{cluster}.maintainMaxInfluences", record["maintainMaxInfluences"])
    cmds.setAttr(f"{cluster}.normalizeWeights", record["normalizeWeights"])
    return cluster


def _weights_by_name(record):
    """Per vertex, ``{influence name: weight}``, so reordered influences compare equal."""
    names = record["influences"]
    return [{names[i]: w for i, w in row} for row in record["weights"]]


def _changed_weights(old, new):
    """How many vertices' weights differ between two records, and the largest difference."""
    changed, largest = 0, 0.0
    for a, b in zip(_weights_by_name(old), _weights_by_name(new)):
        deltas = [abs(a.get(n, 0.0) - b.get(n, 0.0)) for n in set(a) | set(b)]
        if any(deltas):
            changed += 1
            largest = max(largest, *deltas)
    return changed, largest


def _compare_record(old, new):
    """What changed on one mesh's skin, as lines without the mesh name."""
    lines = []
    added = [n for n in new["influences"] if n not in old["influences"]]
    removed = [n for n in old["influences"] if n not in new["influences"]]
    if added:
        lines.append(f"added influences {', '.join(added)}")
    if removed:
        lines.append(f"removed influences {', '.join(removed)}")
    skip = ("mesh", "influences", "vertex_count", "weights", "blend_weights")
    count = new["vertex_count"]
    if old["vertex_count"] != count:
        lines.append(f"vertex count {old['vertex_count']} → {count}, weights not compared")
    else:
        changed, largest = _changed_weights(old, new)
        vertices = data.plural(count, "vertex", "vertices")
        if changed:
            lines.append(f"weights changed on {changed} of {vertices} (largest change {compare.num(largest)})")
        if "blend_weights" in old and "blend_weights" in new:
            changed, largest = compare.numeric_change(old["blend_weights"], new["blend_weights"])
            if changed:
                lines.append(
                    f"blend weights changed on {changed} of {vertices} (largest change {compare.num(largest)})"
                )
        else:
            skip = skip[:-1]  # turned on or off: the structural summary says so
    rest = [{k: v for k, v in r.items() if k not in skip} for r in (old, new)]
    lines.extend(compare.changes(*rest))
    return lines


class SkinProduct(data.DataProduct):
    name = "SkinCluster"
    utility = "SkinCluster Tool"
    kind = "skin"
    extension = ".skin"
    order = 60
    menu_slot = (3, 0)

    def selection_problems(self):
        selection = cmds.ls(selection=True)
        if not selection:
            return ["Nothing selected. Select the skinned meshes to publish."]
        meshes = _selected_meshes(selection)
        if not meshes:
            return ["No meshes selected. Select the skinned meshes to publish."]
        bare = [_short(m) for m in meshes if not _skin_cluster(m)]
        if bare:
            return [f"No skinCluster on: {', '.join(bare)}. Bind them first, or leave them out."]
        return []

    def gather(self, selection):
        meshes = _selected_meshes(selection)
        if not meshes:
            raise RuntimeError("No meshes selected to publish.")
        bare = [_short(m) for m in meshes if not _skin_cluster(m)]
        if bare:
            raise RuntimeError(f"No skinCluster on: {', '.join(bare)}")
        return {"meshes": [_record(m) for m in meshes]}

    def apply(self, payload):
        records = _present(payload["meshes"])
        _check(records)
        clusters = []
        for record in records:
            clusters.append(_apply_record(record))
            runlog.info(
                f"{record['mesh']}: bound {clusters[-1]} to {data.plural(len(record['influences']), 'influence')}"
            )
        message = f"Bound {data.plural(len(clusters), 'mesh', 'meshes')}"
        return f"{message}: {', '.join(clusters)}" if clusters else message

    def describe(self, payload):
        records = payload["meshes"]
        influences = {name for r in records for name in r["influences"]}
        lines = [f"{data.plural(len(records), 'mesh', 'meshes')}, {data.plural(len(influences), 'influence')}"]
        for r in records:
            lines.append(
                f"{r['mesh']}: {r['skinCluster']}, {data.plural(len(r['influences']), 'influence')}, "
                f"{data.plural(r['vertex_count'], 'vertex', 'vertices')}"
            )
        return lines

    def compare(self, old, new):
        added, removed, common = compare.match(old["meshes"], new["meshes"], "mesh")
        lines = []
        if added:
            lines.append(f"Added meshes: {', '.join(added)}")
        if removed:
            lines.append(f"Removed meshes: {', '.join(removed)}")
        for name, a, b in common:
            lines.extend(f"{name}: {line}" for line in _compare_record(a, b))
        return compare.finish(lines)


PRODUCT = SkinProduct()
