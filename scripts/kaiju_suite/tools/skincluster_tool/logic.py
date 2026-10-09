"""SkinCluster Tool: copy, mirror and clean up skin weights. No Qt here.

Copy Skin puts a source mesh's weights on target meshes, matching vertices
by closest point, by UV or by vertex ID (topology). A target without a
skinCluster is bound to the source's influences; a skinned target gets any
it's missing, at zero weight. Every edit goes through undoable Maya
commands, so each function is one undo step.
"""

from collections import defaultdict

from maya import cmds
from maya.api import OpenMaya as om
from maya.api import OpenMayaAnim as oma

from kaiju_suite.core.undo import undoable

MODES = ("closest_point", "uv", "topology")
MODE_LABELS = {"closest_point": "Closest Point", "uv": "UV", "topology": "Topology"}
# Decimals compared when grouping vertices with the same weights.
_DECIMALS = 6


def _short(node):
    return cmds.ls(node)[0]


def _shape(transform):
    shapes = cmds.listRelatives(transform, shapes=True, noIntermediate=True, type="mesh", fullPath=True)
    return shapes[0] if shapes else None


def meshes(selection):
    """The mesh transforms in ``selection`` (a shape or component stands for
    its transform), in order, each once."""
    found = []
    for node in cmds.ls(selection, objectsOnly=True, long=True) or []:
        if cmds.nodeType(node) == "mesh":
            node = cmds.listRelatives(node, parent=True, fullPath=True)[0]
        if cmds.objectType(node, isAType="transform") and _shape(node):
            found.append(node)
    return list(dict.fromkeys(found))


def skin_cluster(mesh):
    """The skinCluster deforming ``mesh``, or ``None``."""
    shape = _shape(mesh)
    found = cmds.ls(cmds.listHistory(shape) or [], type="skinCluster") if shape else []
    return found[0] if found else None


def _influences(cluster):
    return cmds.ls(cmds.skinCluster(cluster, query=True, influence=True) or [], long=True)


def _require_skin(mesh):
    cluster = skin_cluster(mesh)
    if not cluster:
        raise ValueError(f"{_short(mesh)} has no skinCluster.")
    return cluster


def _uv_set(mesh):
    return cmds.polyUVSet(mesh, query=True, currentUVSet=True)[0]


# -- copy -------------------------------------------------------------------


def _prepare_target(target, source_cluster):
    """The target's skinCluster, bound to the source's influences if it had
    none, else with the missing ones added at zero weight."""
    influences = _influences(source_cluster)
    cluster = skin_cluster(target)
    if cluster is None:
        cluster = cmds.skinCluster(
            *influences,
            target,
            toSelectedBones=True,
            maximumInfluences=cmds.getAttr(f"{source_cluster}.maxInfluences"),
            obeyMaxInfluences=False,
        )[0]
        cmds.setAttr(f"{cluster}.skinningMethod", cmds.getAttr(f"{source_cluster}.skinningMethod"))
        return cluster
    have = set(_influences(cluster))
    for influence in influences:
        if influence not in have:
            cmds.skinCluster(cluster, edit=True, addInfluence=influence, weight=0, lockWeights=False)
    return cluster


def _weights(mesh, cluster):
    """``(influence names, rows)``: every vertex's weights, in influence order."""
    path = om.MSelectionList().add(_shape(mesh)).getDagPath(0)
    fn = oma.MFnSkinCluster(om.MSelectionList().add(cluster).getDependNode(0))
    names = [_short(p.fullPathName()) for p in fn.influenceObjects()]
    weights, per_vertex = fn.getWeights(path, om.MObject())
    rows = [weights[v * per_vertex : (v + 1) * per_vertex] for v in range(len(weights) // per_vertex)]
    return names, rows


def _copy_by_topology(source, source_cluster, target, cluster):
    """Give each target vertex the weights of the source vertex with the same
    ID; vertices with the same weights are set in one ``skinPercent``."""
    names, source_rows = _weights(source, source_cluster)
    rows = defaultdict(list)
    for v, row in enumerate(source_rows):
        rows[tuple((names[i], round(w, _DECIMALS)) for i, w in enumerate(row) if w > 0)].append(v)
    for row, vertices in rows.items():
        components = [f"{target}.vtx[{v}]" for v in vertices]
        cmds.skinPercent(cluster, components, transformValue=list(row), zeroRemainingInfluences=True, normalize=True)


@undoable
def copy_skin(source, targets, mode="closest_point"):
    """Copy ``source``'s skin weights onto each of ``targets``, matching
    vertices by ``mode`` (one of :data:`MODES`); returns the targets'
    skinClusters. Raises ``ValueError`` before changing anything if the
    source has no skin, or a target can't take the weights."""
    if mode not in MODES:
        raise ValueError(f"Unknown copy mode {mode!r}; use one of {', '.join(MODES)}.")
    source_cluster = _require_skin(source)
    targets = [t for t in cmds.ls(targets, long=True) if t != cmds.ls(source, long=True)[0]]
    if not targets:
        raise ValueError("No target meshes. Select the source mesh first, then the targets.")
    if mode == "topology":
        count = cmds.polyEvaluate(source, vertex=True)
        counts = {t: cmds.polyEvaluate(t, vertex=True) for t in targets}
        wrong = [f"{_short(t)} ({n})" for t, n in counts.items() if n != count]
        if wrong:
            raise ValueError(
                f"Copying by topology needs the same vertex count as {_short(source)} ({count}): {', '.join(wrong)}."
            )

    clusters = []
    for target in targets:
        cluster = _prepare_target(target, source_cluster)
        if mode == "topology":
            _copy_by_topology(source, source_cluster, target, cluster)
        else:
            kwargs = {"uvSpace": (_uv_set(source), _uv_set(target))} if mode == "uv" else {}
            cmds.copySkinWeights(
                sourceSkin=source_cluster,
                destinationSkin=cluster,
                noMirror=True,
                surfaceAssociation="closestPoint",
                influenceAssociation=("name", "oneToOne"),
                **kwargs,
            )
        clusters.append(cluster)
    return clusters


# -- mirror -----------------------------------------------------------------


@undoable
def mirror_skin(meshes, positive_to_negative=True):
    """Mirror each mesh's weights across X (object space), from the +X half
    onto the -X half, or the other way. Influences are matched to their
    mirror image by position (Maya's closest joint)."""
    for mesh in meshes:
        cluster = _require_skin(mesh)
        cmds.copySkinWeights(
            sourceSkin=cluster,
            destinationSkin=cluster,
            mirrorMode="YZ",
            mirrorInverse=not positive_to_negative,
            surfaceAssociation="closestPoint",
            influenceAssociation=("closestJoint", "oneToOne"),
        )


# -- clean up ---------------------------------------------------------------


@undoable
def prune(meshes, threshold=0.01):
    """Zero every weight below ``threshold`` on each mesh, then normalize."""
    for mesh in meshes:
        cmds.skinPercent(_require_skin(mesh), mesh, pruneWeights=threshold, normalize=True)


@undoable
def remove_unused(meshes):
    """Remove influences with no weight on any vertex; returns their names."""
    removed = []
    for mesh in meshes:
        cluster = _require_skin(mesh)
        names, rows = _weights(mesh, cluster)
        unused = [name for i, name in enumerate(names) if not any(row[i] > 0 for row in rows)]
        # Keep one influence: a skinCluster can't be left with none.
        if len(unused) == len(names):
            unused = unused[1:]
        for influence in unused:
            cmds.skinCluster(cluster, edit=True, removeInfluence=influence)
        removed += unused
    return removed


def influences(meshes):
    """The influences of every mesh's skinCluster (long names), each once."""
    found = []
    for mesh in meshes:
        found += _influences(_require_skin(mesh))
    return list(dict.fromkeys(found))
