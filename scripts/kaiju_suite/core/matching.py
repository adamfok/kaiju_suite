"""Vertex matching between meshes, or between a mesh and saved points. No Qt here.

Used wherever data made on one mesh has to go onto another: the SkinCluster
Tool's Copy Skin (closest point, UV or topology), and the Assembler's
SkinCluster, DeltaMush and BlendShapes items when a mesh's vertex count
changed since publish (they match by closest point to the saved positions).

:func:`closest_indices` is a plain nearest-neighbour search (a k-d tree in
pure Python) on 2D or 3D points, so it works on UVs as well as positions.
On a tie the lower source index wins, so results are repeatable.
"""

from maya import cmds
from maya.api import OpenMaya as om

MODES = ("closest_point", "uv", "topology")
MODE_LABELS = {"closest_point": "Closest Point", "uv": "UV", "topology": "Topology"}


def check_mode(mode):
    """Raise ``ValueError`` unless ``mode`` is one of :data:`MODES`."""
    if mode not in MODES:
        raise ValueError(f"Unknown matching mode {mode!r}; use one of {', '.join(MODES)}.")


# -- nearest neighbour ------------------------------------------------------


def _build(points, indices, depth):
    """A k-d tree node ``(index, axis, lower, upper)``, or ``None``."""
    if not indices:
        return None
    axis = depth % len(points[indices[0]])
    indices.sort(key=lambda i: (points[i][axis], i))
    mid = len(indices) // 2
    return (
        indices[mid],
        axis,
        _build(points, indices[:mid], depth + 1),
        _build(points, indices[mid + 1 :], depth + 1),
    )


def _search(tree, points, point):
    """The index of the point in ``tree`` closest to ``point``."""
    best_distance, best_index = float("inf"), -1
    # (node, squared distance from ``point`` to the node's side of a split)
    stack = [(tree, 0.0)]
    while stack:
        node, bound = stack.pop()
        if node is None or bound > best_distance:
            continue
        index, axis, lower, upper = node
        other = points[index]
        distance = sum((a - b) ** 2 for a, b in zip(point, other))
        if distance < best_distance or (distance == best_distance and index < best_index):
            best_distance, best_index = distance, index
        diff = point[axis] - other[axis]
        near, far = (lower, upper) if diff < 0 else (upper, lower)
        stack.append((far, diff * diff))  # popped after the near side
        stack.append((near, bound))
    return best_index


def closest_indices(source_points, target_points):
    """For each of ``target_points``, the index of the closest of
    ``source_points`` (2D or 3D sequences). Raises ``ValueError`` if there
    are no source points."""
    source = [tuple(p) for p in source_points]
    if not source:
        raise ValueError("No points to match against.")
    tree = _build(source, list(range(len(source))), 0)
    return [_search(tree, source, tuple(p)) for p in target_points]


# -- meshes -----------------------------------------------------------------


def _shape(mesh):
    """The visible mesh shape of ``mesh`` (a transform or a shape)."""
    if cmds.nodeType(mesh) == "mesh":
        return cmds.ls(mesh, long=True)[0]
    shapes = cmds.listRelatives(mesh, shapes=True, noIntermediate=True, type="mesh", fullPath=True)
    if not shapes:
        raise ValueError(f"{mesh} has no mesh shape.")
    return shapes[0]


def _dag_path(node):
    return om.MSelectionList().add(node).getDagPath(0)


def vertex_count(mesh):
    return cmds.polyEvaluate(_shape(mesh), vertex=True)


def uv_set(mesh):
    """The current UV set of ``mesh``."""
    return cmds.polyUVSet(_shape(mesh), query=True, currentUVSet=True)[0]


def rest_points(mesh):
    """Every vertex position of ``mesh`` in object space, before any
    deformer (from its original shape when it has one), as tuples."""
    shape = _shape(mesh)
    original = [p for p in cmds.deformableShape(shape, originalGeometry=True) or [] if p]
    source = original[0].split(".")[0] if original else shape
    points = om.MFnMesh(_dag_path(source)).getPoints(om.MSpace.kObject)
    return [(p.x, p.y, p.z) for p in points]


def world_points(mesh):
    """Every vertex position of ``mesh`` in world space, as deformed now."""
    points = om.MFnMesh(_dag_path(_shape(mesh))).getPoints(om.MSpace.kWorld)
    return [(p.x, p.y, p.z) for p in points]


def vertex_uvs(mesh, uv_set_name=None):
    """Each vertex's ``(u, v)`` in ``uv_set_name`` (default: the current
    set); a vertex with several UVs gives its first. Raises ``ValueError``
    if a vertex has no UV."""
    fn = om.MFnMesh(_dag_path(_shape(mesh)))
    name = uv_set_name or uv_set(mesh)
    us, vs = fn.getUVs(name)
    counts, uv_ids = fn.getAssignedUVs(name)
    _, vertex_ids = fn.getVertices()
    uvs = [None] * fn.numVertices
    for vertex, uv in zip(vertex_ids, uv_ids):
        if uvs[vertex] is None:
            uvs[vertex] = (us[uv], vs[uv])
    if None in uvs:
        raise ValueError(f"{cmds.ls(mesh)[0]} has vertices without UVs in {name}.")
    return uvs


def count_mismatches(source, targets):
    """``"name (count)"`` for each of ``targets`` whose vertex count isn't ``source``'s."""
    count = vertex_count(source)
    found = []
    for target in targets:
        n = vertex_count(target)
        if n != count:
            found.append(f"{cmds.ls(target)[0]} ({n})")
    return found


def vertex_map(source, target, mode="closest_point"):
    """For each vertex of ``target``, the matching vertex of ``source``, by
    ``mode`` (one of :data:`MODES`): closest point in world space, closest
    UV, or the same vertex ID (which needs the same vertex count)."""
    check_mode(mode)
    if mode == "topology":
        if count_mismatches(source, [target]):
            raise ValueError(
                f"Matching by topology needs the same vertex count: {cmds.ls(source)[0]} has "
                f"{vertex_count(source)}, {cmds.ls(target)[0]} has {vertex_count(target)}."
            )
        return list(range(vertex_count(target)))
    if mode == "uv":
        return closest_indices(vertex_uvs(source), vertex_uvs(target))
    return closest_indices(world_points(source), world_points(target))
