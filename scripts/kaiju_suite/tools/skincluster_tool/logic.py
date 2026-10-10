"""SkinCluster Tool: copy, mirror, clean up and edit skin weights. No Qt here.

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


def _set_rows(mesh, cluster, rows):
    """Set ``rows`` ({vertex: [(influence, weight), ...]}) on ``mesh``; the
    other influences go to zero. Vertices with the same weights are set in
    one ``skinPercent``."""
    groups = defaultdict(list)
    for v, row in rows.items():
        groups[tuple((name, round(w, _DECIMALS)) for name, w in row if w > 0)].append(v)
    for row, vertices in groups.items():
        components = [f"{mesh}.vtx[{v}]" for v in vertices]
        cmds.skinPercent(cluster, components, transformValue=list(row), zeroRemainingInfluences=True, normalize=True)


def _normalized(pairs):
    """``pairs`` ([(influence, weight), ...]) scaled to sum to 1."""
    total = sum(w for _, w in pairs)
    return [(name, w / total) for name, w in pairs]


def _copy_by_topology(source, source_cluster, target, cluster):
    """Give each target vertex the weights of the source vertex with the same ID."""
    names, source_rows = _weights(source, source_cluster)
    _set_rows(target, cluster, {v: list(zip(names, row)) for v, row in enumerate(source_rows)})


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


# -- skin weights -----------------------------------------------------------


def _vertices(components):
    """``{mesh transform: [vertex IDs]}`` for the vertices of ``components``
    (vertices, edges or faces; whole meshes are ignored), in order."""
    components = [c for c in cmds.ls(components) or [] if "." in c]
    found = defaultdict(list)
    if not components:
        return found
    for vertex in cmds.ls(cmds.polyListComponentConversion(components, toVertex=True), flatten=True, long=True):
        node, index = vertex.rsplit(".vtx[", 1)
        mesh = meshes([node])
        if mesh:
            found[mesh[0]].append(int(index.rstrip("]")))
    return found


def _require_vertices(components):
    found = _vertices(components)
    if not found:
        raise ValueError("No vertices selected. Select vertices (or edges, faces) on a skinned mesh.")
    for mesh in found:
        _require_skin(mesh)
    return found


def _pairs(names, row):
    """``[(influence, weight), ...]`` for the non-zero weights of ``row``."""
    return [(name, w) for name, w in zip(names, row) if w > 0]


@undoable
def limit_influences(meshes, max_influences=4):
    """Keep only the ``max_influences`` largest weights on each vertex of each
    mesh, scaled back up to sum to 1."""
    if max_influences < 1:
        raise ValueError("Max influences must be at least 1.")
    for mesh in meshes:
        cluster = _require_skin(mesh)
        names, all_rows = _weights(mesh, cluster)
        rows = {}
        for v, row in enumerate(all_rows):
            pairs = _pairs(names, row)
            if len(pairs) > max_influences:
                pairs.sort(key=lambda pair: pair[1], reverse=True)
                rows[v] = _normalized(pairs[:max_influences])
        _set_rows(mesh, cluster, rows)


@undoable
def normalize(meshes):
    """Scale each vertex's weights to sum to 1 on each mesh."""
    for mesh in meshes:
        cluster = _require_skin(mesh)
        names, all_rows = _weights(mesh, cluster)
        rows = {}
        for v, row in enumerate(all_rows):
            pairs = _pairs(names, row)
            if pairs and abs(sum(row) - 1.0) > 10**-_DECIMALS:
                rows[v] = _normalized(pairs)
        _set_rows(mesh, cluster, rows)


@undoable
def hammer(components):
    """Give each vertex of ``components`` the average weights of the vertices
    connected to it (all read before any changes), like Maya's Weight Hammer."""
    for mesh, vertices in _require_vertices(components).items():
        cluster = skin_cluster(mesh)
        names, all_rows = _weights(mesh, cluster)
        it = om.MItMeshVertex(om.MSelectionList().add(_shape(mesh)).getDagPath(0))
        rows = {}
        for v in vertices:
            it.setIndex(v)
            neighbors = list(it.getConnectedVertices())
            pairs = _pairs(names, [sum(all_rows[n][i] for n in neighbors) for i in range(len(names))])
            if pairs:
                rows[v] = _normalized(pairs)
        _set_rows(mesh, cluster, rows)


def copy_vertex_weights(component):
    """The weights of one vertex, as ``{influence: weight}`` (non-zero only)."""
    found = _require_vertices([component])
    if len(found) != 1 or len(next(iter(found.values()))) != 1:
        raise ValueError("Select exactly one vertex to copy its weights.")
    ((mesh, (vertex,)),) = found.items()
    names, rows = _weights(mesh, skin_cluster(mesh))
    return dict(_pairs(names, rows[vertex]))


@undoable
def paste_vertex_weights(weights, components):
    """Set ``weights`` (``{influence: weight}``, from :func:`copy_vertex_weights`)
    on every vertex of ``components``. Raises ``ValueError`` before changing
    anything if a mesh's skinCluster lacks one of the influences."""
    if not weights:
        raise ValueError("No weights copied. Copy a vertex's weights first.")
    found = _require_vertices(components)
    for mesh in found:
        have = {_short(i) for i in _influences(skin_cluster(mesh))}
        missing = [name for name in weights if name not in have]
        if missing:
            raise ValueError(f"{_short(mesh)}'s skinCluster has no {', '.join(missing)}. Add the influences first.")
    row = _normalized(list(weights.items()))
    for mesh, vertices in found.items():
        _set_rows(mesh, skin_cluster(mesh), {v: row for v in vertices})


@undoable
def add_influences(mesh, joints):
    """Add ``joints`` to ``mesh``'s skinCluster at zero weight, skipping ones
    it already has; returns the names added."""
    joints = cmds.ls(joints, long=True) or []
    if not joints:
        raise ValueError("No joints selected. Select the joints and the skinned mesh.")
    cluster = _require_skin(mesh)
    have = set(_influences(cluster))
    added = []
    for joint in joints:
        if joint not in have:
            cmds.skinCluster(cluster, edit=True, addInfluence=joint, weight=0, lockWeights=False)
            added.append(_short(joint))
    return added


def _closest(names, mesh, vertex):
    """The one of ``names`` closest to ``mesh``'s ``vertex``, in world space."""
    position = om.MVector(cmds.pointPosition(f"{mesh}.vtx[{vertex}]", world=True))

    def distance(name):
        return (om.MVector(cmds.xform(name, query=True, worldSpace=True, translation=True)) - position).length()

    return min(names, key=distance)


@undoable
def remove_influences(mesh, joints):
    """Remove ``joints`` from ``mesh``'s skinCluster; returns the names
    removed. Each vertex's weight on them is shared out over its other
    influences, so weights stay normalized; a vertex left with no weight goes
    fully to the closest remaining influence."""
    cluster = _require_skin(mesh)
    have = _influences(cluster)
    removing = [j for j in dict.fromkeys(cmds.ls(joints, long=True) or []) if j in have]
    if not removing:
        raise ValueError(f"None of the selected joints are influences of {_short(mesh)}.")
    if len(removing) == len(have):
        raise ValueError("Can't remove every influence: a skinCluster needs at least one.")
    gone = {_short(j) for j in removing}
    names, all_rows = _weights(mesh, cluster)
    kept = [name for name in names if name not in gone]
    rows = {}
    for v, row in enumerate(all_rows):
        pairs = _pairs(names, row)
        if any(name in gone for name, _ in pairs):
            pairs = [(name, w) for name, w in pairs if name not in gone]
            rows[v] = _normalized(pairs) if pairs else [(_closest(kept, mesh, v), 1.0)]
    _set_rows(mesh, cluster, rows)
    for joint in removing:
        cmds.skinCluster(cluster, edit=True, removeInfluence=joint)
    return [_short(j) for j in removing]
