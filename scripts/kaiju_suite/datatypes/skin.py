"""Skin weights (.skin): saved as data and bound back by name.

:func:`gather` saves each mesh's skinCluster: its name, influences (in
index order), settings and sparse weights (per vertex, ``[influence index,
weight]`` pairs without zeros), plus the dual quaternion blend weights when
the skinning method is weight blended.

:func:`apply` finds the mesh and influences by name. A mesh that's missing,
or whose influences aren't all there, is skipped with a warning. It checks
every other mesh first (the vertex counts match) and raises before changing
anything. Then, per mesh, it removes the mesh's existing skinCluster, binds
exactly the file's influences under the saved name, and sets every weight
in one ``MFnSkinCluster.setWeights`` call.

Gathering also saves each mesh's rest point positions. If a mesh's vertex
count changed since, applying gives each vertex the weights of the saved
vertex closest to it and warns. Files from before points were saved still
need the same vertex count.

``setWeights`` isn't on Maya's undo queue. Undo still reverts an apply
(removing the new skinCluster takes its weights with it), but redo rebinds
with Maya's default weights, not the saved ones: apply the file again
instead.
"""

from maya import cmds
from maya.api import OpenMaya as om
from maya.api import OpenMayaAnim as oma

from kaiju_suite import datatypes
from kaiju_suite.datatypes import mesh_shape, plural, short

KIND = "skin"
EXTENSION = ".skin"

_WEIGHT_BLENDED = 2
# Decimals kept for weights: well below what a skin can show, and it keeps
# the file small and the same for the same weights.
_DECIMALS = 8


def skin_cluster(mesh):
    """The skinCluster deforming ``mesh``, or ``None``."""
    shape = mesh_shape(mesh)
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
    cluster = skin_cluster(mesh)
    shape = mesh_shape(mesh)
    fn = _skin_fn(cluster)
    path = _dag_path(shape)
    count = om.MFnMesh(path).numVertices
    vertices = _all_vertices(count)

    influences = [short(p.fullPathName()) for p in fn.influenceObjects()]
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
        "mesh": short(mesh),
        "skinCluster": cluster,
        "influences": influences,
        "vertex_count": count,
        "points": datatypes.saved_points(mesh),
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
    missing = datatypes.skip_missing([r["mesh"] for r in records], "meshes")
    kept = []
    for record in records:
        if record["mesh"] in missing:
            continue
        absent = [name for name in dict.fromkeys(record["influences"]) if not cmds.objExists(name)]
        if absent:
            datatypes.warning(f"Skipped {record['mesh']}: missing influences {', '.join(absent)}")
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
        if not mesh_shape(mesh):
            problems.append(f"{record['mesh']} has no mesh shape")
            continue
        problem = datatypes.count_problem(record, mesh, record["mesh"])
        if problem:
            problems.append(problem)
    if problems:
        raise RuntimeError(f"Can't apply skin weights: {'; '.join(problems)}.")


def _remapped(record):
    """``record``, or a copy with its per-vertex data moved onto the mesh's
    current vertices by closest point if the vertex count changed."""
    mesh = _unique(record["mesh"], "mesh")
    mapping = datatypes.vertex_remap(record, mesh, record["mesh"], "skin weights")
    if mapping is None:
        return record
    record = dict(record, vertex_count=len(mapping), weights=[record["weights"][m] for m in mapping])
    if "blend_weights" in record:
        record["blend_weights"] = [record["blend_weights"][m] for m in mapping]
    return record


def _apply_record(record):
    mesh = _unique(record["mesh"], "mesh")
    old = skin_cluster(mesh)
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
    path = _dag_path(mesh_shape(mesh))
    vertices = _all_vertices(count)
    fn.setWeights(path, vertices, om.MIntArray(list(range(len(influences)))), dense, False)

    cmds.setAttr(f"{cluster}.skinningMethod", record["skinningMethod"])
    if "blend_weights" in record:
        fn.setBlendWeights(path, vertices, om.MDoubleArray(record["blend_weights"]))
    cmds.setAttr(f"{cluster}.maxInfluences", record["maxInfluences"])
    cmds.setAttr(f"{cluster}.maintainMaxInfluences", record["maintainMaxInfluences"])
    cmds.setAttr(f"{cluster}.normalizeWeights", record["normalizeWeights"])
    return cluster


def _without(record, key):
    return {k: v for k, v in record.items() if k != key}


def _weights_by_name(record):
    """Per vertex, ``{influence name: weight}``, so reordered influences compare equal."""
    names = record["influences"]
    return [{names[i]: w for i, w in row} for row in record["weights"]]


# -- the datatype -----------------------------------------------------------


def _unskinned(meshes):
    return [short(m) for m in meshes if not skin_cluster(m)]


def selection_problems(selection):
    """Why ``selection`` can't be gathered, as messages."""
    if not selection:
        return ["Nothing selected. Select the skinned meshes to publish."]
    meshes = datatypes.meshes(selection)
    if not meshes:
        return ["No meshes selected. Select the skinned meshes to publish."]
    bare = _unskinned(meshes)
    if bare:
        return [f"No skinCluster on: {', '.join(bare)}. Bind them first, or leave them out."]
    return []


def gather(nodes):
    """The skin weights of the meshes among ``nodes``."""
    meshes = datatypes.meshes(nodes)
    if not meshes:
        raise RuntimeError("No meshes selected to publish.")
    bare = _unskinned(meshes)
    if bare:
        raise RuntimeError(f"No skinCluster on: {', '.join(bare)}")
    return {"meshes": [_record(m) for m in meshes]}


def apply(payload, info=None):
    """Bind each saved mesh with its saved weights; returns a message."""
    records = _present(payload["meshes"])
    _check(records)
    clusters = []
    for record in records:
        clusters.append(_apply_record(_remapped(record)))
        datatypes.report(info, f"{record['mesh']}: bound {clusters[-1]} to {plural(len(record['influences']), 'influence')}")
    message = f"Bound {plural(len(clusters), 'mesh', 'meshes')}"
    return f"{message}: {', '.join(clusters)}" if clusters else message


def nodes(payload):
    return [r["mesh"] for r in payload["meshes"]]


def describe(payload):
    records = payload["meshes"]
    influences = {name for r in records for name in r["influences"]}
    lines = [f"{plural(len(records), 'mesh', 'meshes')}, {plural(len(influences), 'influence')}"]
    for r in records:
        lines.append(
            f"{r['mesh']}: {r['skinCluster']}, {plural(len(r['influences']), 'influence')}, "
            f"{plural(r['vertex_count'], 'vertex', 'vertices')}"
        )
    return lines


def compare_view(payload):
    """Weights by influence name, so reordered influences compare equal;
    without the rest points (saved for remapping, not skin data)."""
    meshes = [{**_without(r, "points"), "weights": _weights_by_name(r)} for r in payload["meshes"]]
    return {**payload, "meshes": meshes}
