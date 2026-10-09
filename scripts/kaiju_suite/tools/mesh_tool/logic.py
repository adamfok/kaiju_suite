"""Mesh Tool: checks that a mesh is clean, and fixes for some problems. No Qt.

Each check looks at one mesh (its transform, long name) and returns what's
wrong as items to select: components (``|body.f[3]``) or the transform
itself. Checks with a ``fix`` can also repair what they find.
"""

from collections import namedtuple

from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.core.undo import undoable

# How close counts as the same (scene units): edge lengths, face areas and
# where a vertex's mirror image should be.
TOLERANCE = 1e-4

Check = namedtuple("Check", "key label description find fix")
Result = namedtuple("Result", "check mesh items")


def _shape(transform):
    shapes = cmds.listRelatives(transform, shapes=True, noIntermediate=True, type="mesh", fullPath=True)
    return shapes[0] if shapes else None


def _dag_path(transform):
    return om.MSelectionList().add(_shape(transform)).getDagPath(0)


def _items(transform, kind, indices):
    return [f"{transform}.{kind}[{i}]" for i in indices]


# -- topology ---------------------------------------------------------------


def _ngons(mesh):
    counts, _ = om.MFnMesh(_dag_path(mesh)).getVertices()
    return _items(mesh, "f", [i for i, n in enumerate(counts) if n > 4])


def _non_manifold(mesh):
    found = cmds.polyInfo(mesh, nonManifoldEdges=True) or []
    found += cmds.polyInfo(mesh, nonManifoldVertices=True) or []
    return list(dict.fromkeys(_long(found, mesh)))


def _lamina(mesh):
    return _long(cmds.polyInfo(mesh, laminaFaces=True) or [], mesh)


def _long(components, mesh):
    """``polyInfo``'s components (``bodyShape.e[2]``) named on the transform."""
    return [f"{mesh}.{c.split('.', 1)[1]}" for c in cmds.ls(components, flatten=True)]


def _zero_area(mesh):
    faces = om.MItMeshPolygon(_dag_path(mesh))
    found = []
    while not faces.isDone():
        if faces.getArea(om.MSpace.kObject) < TOLERANCE * TOLERANCE:
            found.append(faces.index())
        faces.next()
    return _items(mesh, "f", found)


def _zero_length(mesh):
    edges = om.MItMeshEdge(_dag_path(mesh))
    found = []
    while not edges.isDone():
        if edges.length(om.MSpace.kObject) < TOLERANCE:
            found.append(edges.index())
        edges.next()
    return _items(mesh, "e", found)


def _borders(mesh):
    edges = om.MItMeshEdge(_dag_path(mesh))
    found = []
    while not edges.isDone():
        if edges.onBoundary():
            found.append(edges.index())
        edges.next()
    return _items(mesh, "e", found)


# -- surface ----------------------------------------------------------------


def _uvs(mesh):
    faces = om.MItMeshPolygon(_dag_path(mesh))
    found = []
    while not faces.isDone():
        if not faces.hasUVs():
            found.append(faces.index())
        faces.next()
    return _items(mesh, "f", found)


def _normals(mesh):
    fn = om.MFnMesh(_dag_path(mesh))
    locked = {i for i in range(fn.numNormals) if fn.isNormalLocked(i)}
    if not locked:
        return []
    counts, normal_ids = fn.getNormalIds()
    _, vertex_ids = fn.getVertices()
    vertices = sorted({v for v, n in zip(vertex_ids, normal_ids) if n in locked})
    return _items(mesh, "vtx", vertices)


def _unlock_normals(meshes):
    for mesh in meshes:
        cmds.polyNormalPerVertex(mesh, unFreezeNormal=True)


def _symmetry(mesh):
    """Vertices with no vertex at their mirror image across the YZ plane
    (object space)."""
    points = om.MFnMesh(_dag_path(mesh)).getPoints(om.MSpace.kObject)
    cells = {}
    for i, p in enumerate(points):
        cells.setdefault(_cell(p.x, p.y, p.z), []).append(p)

    def has_mirror(p):
        x, y, z = _cell(-p.x, p.y, p.z)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for q in cells.get((x + dx, y + dy, z + dz), ()):
                        if abs(q.x + p.x) < TOLERANCE and abs(q.y - p.y) < TOLERANCE and abs(q.z - p.z) < TOLERANCE:
                            return True
        return False

    return _items(mesh, "vtx", [i for i, p in enumerate(points) if not has_mirror(p)])


def _cell(x, y, z):
    return round(x / TOLERANCE), round(y / TOLERANCE), round(z / TOLERANCE)


# -- nodes ------------------------------------------------------------------

_IDENTITY = {"translate": (0, 0, 0), "rotate": (0, 0, 0), "scale": (1, 1, 1), "shear": (0, 0, 0)}


def _transforms(mesh):
    for attr, identity in _IDENTITY.items():
        values = cmds.getAttr(f"{mesh}.{attr}")[0]
        if any(abs(v - i) > TOLERANCE for v, i in zip(values, identity)):
            return [mesh]
    return []


def _freeze(meshes):
    for mesh in meshes:
        cmds.makeIdentity(mesh, apply=True, translate=True, rotate=True, scale=True, normal=False)


# Nodes in a mesh's history that aren't modeling history.
_NOT_HISTORY = ("geometryFilter", "tweak", "groupParts", "groupId", "shadingEngine", "objectSet")


def _history(mesh):
    shape = _shape(mesh)
    found = cmds.listHistory(shape, pruneDagObjects=True) or []
    if any(not any(cmds.objectType(node, isAType=kind) for kind in _NOT_HISTORY) for node in found):
        return [mesh]
    return []


def _delete_history(meshes):
    # Keeps deformers (skin, blendShapes, ...) and removes the rest.
    cmds.bakePartialHistory(meshes, prePostDeformers=True)


def _names(mesh):
    return [mesh] if len(cmds.ls(mesh.rsplit("|", 1)[-1])) > 1 else []


def _shape_names(mesh):
    shape = _shape(mesh)
    return [mesh] if shape.rsplit("|", 1)[-1] != f"{mesh.rsplit('|', 1)[-1]}Shape" else []


def _rename_shapes(meshes):
    for mesh in meshes:
        cmds.rename(_shape(mesh), f"{mesh.rsplit('|', 1)[-1]}Shape")


CHECKS = (
    Check("ngons", "N-gons", "Faces with more than four sides.", _ngons, None),
    Check("non_manifold", "Non-manifold", "Edges shared by more than two faces, and bow-tie vertices.", _non_manifold, None),
    Check("lamina", "Lamina faces", "Faces that share all their edges with another face.", _lamina, None),
    Check("zero_area", "Zero-area faces", "Faces with (almost) no area.", _zero_area, None),
    Check("zero_length", "Zero-length edges", "Edges with (almost) no length.", _zero_length, None),
    Check("borders", "Open borders", "Edges on a hole or an open edge of the mesh.", _borders, None),
    Check("uvs", "Missing UVs", "Faces with no UVs in the current UV set.", _uvs, None),
    Check("normals", "Locked normals", "Vertices with locked (user-set) normals.", _normals, _unlock_normals),
    Check("symmetry", "Not symmetric", "Vertices with no mirror vertex across X (object space).", _symmetry, None),
    Check("transforms", "Unfrozen transform", "Translate, rotate, scale or shear not at their defaults.", _transforms, _freeze),
    Check("history", "Construction history", "Modeling history (deformers don't count).", _history, _delete_history),
    Check("names", "Duplicate name", "Another node has the same name; tools find meshes by name.", _names, None),
    Check("shape_names", "Shape name", "The shape isn't called <mesh>Shape.", _shape_names, _rename_shapes),
)  # fmt: skip

_BY_KEY = {check.key: check for check in CHECKS}


def meshes(selection):
    """The mesh transforms in ``selection`` (a shape or component stands for
    its transform), in order, each once; every mesh in the scene if
    ``selection`` is empty."""
    if not selection:
        shapes = cmds.ls(type="mesh", noIntermediate=True, long=True) or []
        selection = [cmds.listRelatives(s, parent=True, fullPath=True)[0] for s in shapes]
    found = []
    for node in cmds.ls(selection, objectsOnly=True, long=True) or []:
        if cmds.nodeType(node) == "mesh":
            node = cmds.listRelatives(node, parent=True, fullPath=True)[0]
        if cmds.objectType(node, isAType="transform") and _shape(node):
            found.append(node)
    return list(dict.fromkeys(found))


def run(meshes, keys=None):
    """Run the checks named in ``keys`` (default: all) on each mesh; returns
    a :data:`Result` for every check that found something, in check order."""
    checks = [_BY_KEY[key] for key in keys] if keys else CHECKS
    results = []
    for check in checks:
        for mesh in meshes:
            items = check.find(mesh)
            if items:
                results.append(Result(check, mesh, items))
    return results


@undoable
def fix(key, meshes):
    """Repair what check ``key`` finds on ``meshes``, as one undo step."""
    check = _BY_KEY[key]
    if not check.fix:
        raise ValueError(f"{check.label} can't be fixed automatically.")
    check.fix(list(meshes))
