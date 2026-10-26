"""Mesh (.mesh): polygon meshes saved as data and rebuilt as new meshes.

:func:`gather` saves the given meshes: name, parent name, local transform,
object-space points, topology, UV sets, hard edges, locked (user) normals
and color sets (vertex colors). Files saved before normals and color sets
were added still load, without them. :func:`apply` always creates
new meshes (with ``MFnMesh.create``) and never changes existing ones: a name
that's taken gets the next free one (``body`` → ``body1``, shape
``body1Shape``). Each new mesh gets ``initialShadingGroup``, and goes under
the scene's node with its saved parent name if there is one, otherwise under
the world.

Geometry goes through OpenMaya 2 for speed. The mesh shape is created by the
API under a transform made with cmds, so undoing the transform's creation
removes the shape with it and one undo still reverts a whole apply.

:data:`CHECKS` are QC checks on given meshes (n-gons, non-manifold, lamina,
zero-area faces, zero-length edges, missing UVs, locked normals, symmetry,
unfrozen transforms, history, duplicate names, shape names), run by the Mesh
Tool's QC tab and before Builder publishes; Missing UVs and Not symmetric
only run in the tool. Four have a ``fix``. Checks change nothing.
"""

from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite import datatypes
from kaiju_suite.core.checks import Check, Problem
from kaiju_suite.core.selection import short_name
from kaiju_suite.datatypes import create_node, node_path, outside_parents, parent_of, plural, short, unique_name

KIND = "mesh"
EXTENSION = ".mesh"

_VECTORS = ("translate", "rotate", "scale")


def _mesh_shape(transform):
    """The transform's first non-intermediate mesh shape, or ``None``."""
    shapes = cmds.listRelatives(transform, shapes=True, noIntermediate=True, fullPath=True) or []
    meshes = cmds.ls(shapes, type="mesh", long=True)
    return meshes[0] if meshes else None


def _split_selection(selection):
    """The selected mesh transforms (a selected mesh shape counts as its
    transform), in selection order, and the selected nodes that aren't meshes."""
    transforms, others = [], []
    for node in cmds.ls(selection, long=True, objectsOnly=True) or []:
        if cmds.objectType(node, isAType="transform") and _mesh_shape(node):
            transforms.append(node)
        elif cmds.objectType(node) == "mesh" and not cmds.getAttr(f"{node}.intermediateObject"):
            transforms.append(parent_of(node))
        else:
            others.append(node)
    return list(dict.fromkeys(transforms)), list(dict.fromkeys(others))


def _mfn(path):
    sel = om.MSelectionList()
    sel.add(path)
    return om.MFnMesh(sel.getDagPath(0))


def _record(transform):
    parent = parent_of(transform)
    record = {"name": short_name(transform), "parent": short_name(parent) if parent else None}
    for attr in _VECTORS:
        record[attr] = list(cmds.getAttr(f"{transform}.{attr}")[0])
    record["rotateOrder"] = int(cmds.getAttr(f"{transform}.rotateOrder"))

    fn = _mfn(_mesh_shape(transform))
    record["points"] = [[p.x, p.y, p.z] for p in fn.getPoints(om.MSpace.kObject)]
    counts, connects = fn.getVertices()
    record["face_counts"] = list(counts)
    record["face_connects"] = list(connects)

    current = fn.currentUVSetName()
    names = [current] + [n for n in fn.getUVSetNames() if n != current] if current else []
    record["uv_sets"] = []
    for name in names:
        u, v = fn.getUVs(name)
        uv_counts, uv_ids = fn.getAssignedUVs(name)
        record["uv_sets"].append(
            {"name": name, "u": list(u), "v": list(v), "uv_counts": list(uv_counts), "uv_ids": list(uv_ids)}
        )
    # Hard edges by their two vertices, which don't depend on edge numbering.
    record["hard_edges"] = sorted(
        sorted(fn.getEdgeVertices(e)) for e in range(fn.numEdges) if not fn.isEdgeSmooth(e)
    )
    record["normals"] = _locked_normals(fn, counts, connects)
    record["color_sets"] = _color_sets(fn)
    return record


def _locked_normals(fn, counts, connects):
    """The locked (user) normals as ``[face, vertex, x, y, z]``, one per
    face-vertex that has one."""
    _, normal_ids = fn.getNormalIds()
    normals = fn.getNormals()
    locked, i = [], 0
    for face, count in enumerate(counts):
        for _ in range(count):
            normal_id = normal_ids[i]
            if fn.isNormalLocked(normal_id):
                n = normals[normal_id]
                locked.append([face, connects[i], n.x, n.y, n.z])
            i += 1
    return locked


def _color_sets(fn):
    """Every color set, current first, with its representation (RGB, RGBA,
    A as ``MFnMesh`` numbers it) and one RGBA color per face-vertex, in face
    order; face-vertices with no color are ``None``."""
    current = fn.currentColorSetName()
    names = [current] + [n for n in fn.getColorSetNames() if n != current] if current else []
    sets = []
    for name in names:
        colors = []
        for c in fn.getFaceVertexColors(name):
            colors.append(None if (c.r, c.g, c.b, c.a) == (-1, -1, -1, -1) else [c.r, c.g, c.b, c.a])
        sets.append({"name": name, "representation": int(fn.getColorRepresentation(name)), "colors": colors})
    return sets


def _build_shape(transform, record):
    """Create the mesh shape under ``transform`` from ``record``; returns its path."""
    sel = om.MSelectionList()
    sel.add(transform)
    fn = om.MFnMesh()
    fn.create(
        [om.MPoint(*p) for p in record["points"]],
        record["face_counts"],
        record["face_connects"],
        parent=sel.getDependNode(0),
    )

    uv_sets = record["uv_sets"]
    for i, uv_set in enumerate(uv_sets):
        name = uv_set["name"]
        if i == 0:
            default = fn.currentUVSetName()
            if default != name:
                fn.renameUVSet(default, name)
        else:
            fn.createUVSet(name)
        fn.setUVs(uv_set["u"], uv_set["v"], name)
        fn.assignUVs(uv_set["uv_counts"], uv_set["uv_ids"], name)
    if uv_sets:
        fn.setCurrentUVSetName(uv_sets[0]["name"])

    # Older files have no normals or color sets. Setting normals hardens
    # edges, so the edge smoothing is set after them.
    normals = record.get("normals") or []
    if normals:
        fn.setFaceVertexNormals(
            [om.MVector(*n[2:]) for n in normals], [n[0] for n in normals], [n[1] for n in normals]
        )

    hard = {tuple(pair) for pair in record["hard_edges"]}
    edges = list(range(fn.numEdges))
    fn.setEdgeSmoothings(edges, [tuple(sorted(fn.getEdgeVertices(e))) not in hard for e in edges])
    fn.cleanupEdgeSmoothing()

    color_sets = record.get("color_sets") or []
    for color_set in color_sets:
        name, rep = color_set["name"], color_set["representation"]
        fn.createColorSet(name, False, rep)
        # One color per distinct value; -1 leaves a face-vertex without one.
        index, colors, ids = {}, [], []
        for color in color_set["colors"]:
            if color is None:
                ids.append(-1)
                continue
            key = tuple(color)
            if key not in index:
                index[key] = len(colors)
                colors.append(om.MColor(color))
            ids.append(index[key])
        fn.setColors(colors, name, rep)
        fn.assignColors(ids, name)
    if color_sets:
        fn.setCurrentColorSetName(color_sets[0]["name"])
    fn.updateSurface()
    return fn.fullPathName()


def selection_problems(selection):
    if not selection:
        return ["Nothing selected. Select the meshes to publish."]
    transforms, others = _split_selection(selection)
    if others:
        names = ", ".join(short_name(n) for n in others)
        return [f"Not meshes: {names}. Select only meshes to publish."]
    if not transforms:
        return ["No meshes selected. Select the meshes to publish."]
    return []


def gather(nodes):
    transforms, others = _split_selection(nodes)
    if others:
        raise RuntimeError(f"Not meshes: {', '.join(short_name(n) for n in others)}")
    if not transforms:
        raise RuntimeError("No meshes selected to publish.")
    return {"meshes": [_record(t) for t in transforms]}


def apply(payload, info=None):
    records = payload["meshes"]
    parents = outside_parents(records)
    uuids, renamed = [], []
    for record in records:
        uuid = create_node("transform", record["name"], parents.get(record["parent"]))
        transform = node_path(uuid)
        for attr in _VECTORS:
            cmds.setAttr(f"{transform}.{attr}", *record[attr])
        cmds.setAttr(f"{transform}.rotateOrder", record["rotateOrder"])
        shape = _build_shape(transform, record)
        leaf = short_name(transform)
        cmds.rename(shape, unique_name(f"{leaf}Shape"))
        cmds.sets(node_path(uuid), edit=True, forceElement="initialShadingGroup")
        uuids.append(uuid)
        if leaf != record["name"]:
            renamed.append(f"{record['name']} → {leaf}")
    message = f"Created {len(records)} mesh{'es' if len(records) != 1 else ''}"
    if renamed:
        message += f" (names taken, renamed: {', '.join(renamed)})"
    return message


def nodes(payload):
    return [r["name"] for r in payload["meshes"]]


def describe(payload):
    records = payload["meshes"]
    return [
        f"{len(records)} mesh{'es' if len(records) != 1 else ''}",
        ", ".join(r["name"] for r in records),
    ]


def compare_view(payload):
    # Files published before normals and colors were saved have neither: same as none.
    meshes = [{"normals": [], "color_sets": [], **r} for r in payload["meshes"]]
    return {**payload, "meshes": meshes}


# -- QC checks --------------------------------------------------------------

# How close counts as the same (scene units): edge lengths, face areas and
# where a vertex's mirror image should be.
TOLERANCE = 1e-4


def _dag_path(transform):
    return om.MSelectionList().add(_mesh_shape(transform)).getDagPath(0)


def _items(transform, kind, indices):
    return [f"{transform}.{kind}[{i}]" for i in indices]


def _on_transform(components, mesh):
    """``polyInfo``'s components (``bodyShape.e[2]``) named on the transform."""
    return [f"{mesh}.{c.split('.', 1)[1]}" for c in cmds.ls(components, flatten=True)]


def _find_ngons(mesh):
    counts, _ = om.MFnMesh(_dag_path(mesh)).getVertices()
    return _items(mesh, "f", [i for i, n in enumerate(counts) if n > 4])


def _find_non_manifold(mesh):
    found = cmds.polyInfo(mesh, nonManifoldEdges=True) or []
    found += cmds.polyInfo(mesh, nonManifoldVertices=True) or []
    return list(dict.fromkeys(_on_transform(found, mesh)))


def _find_lamina(mesh):
    return _on_transform(cmds.polyInfo(mesh, laminaFaces=True) or [], mesh)


def _find_zero_area(mesh):
    faces = om.MItMeshPolygon(_dag_path(mesh))
    found = []
    while not faces.isDone():
        if faces.getArea(om.MSpace.kObject) < TOLERANCE * TOLERANCE:
            found.append(faces.index())
        faces.next()
    return _items(mesh, "f", found)


def _find_zero_length(mesh):
    edges = om.MItMeshEdge(_dag_path(mesh))
    found = []
    while not edges.isDone():
        if edges.length(om.MSpace.kObject) < TOLERANCE:
            found.append(edges.index())
        edges.next()
    return _items(mesh, "e", found)


def _find_uvs(mesh):
    faces = om.MItMeshPolygon(_dag_path(mesh))
    found = []
    while not faces.isDone():
        if not faces.hasUVs():
            found.append(faces.index())
        faces.next()
    return _items(mesh, "f", found)


def _find_normals(mesh):
    fn = om.MFnMesh(_dag_path(mesh))
    locked = {i for i in range(fn.numNormals) if fn.isNormalLocked(i)}
    if not locked:
        return []
    _, normal_ids = fn.getNormalIds()
    _, vertex_ids = fn.getVertices()
    return _items(mesh, "vtx", sorted({v for v, n in zip(vertex_ids, normal_ids) if n in locked}))


def _fix_normals(meshes):
    for mesh in meshes:
        cmds.polyNormalPerVertex(mesh, unFreezeNormal=True)


def _cell(x, y, z):
    return round(x / TOLERANCE), round(y / TOLERANCE), round(z / TOLERANCE)


def _find_symmetry(mesh):
    """Vertices with no vertex at their mirror image across the YZ plane
    (object space)."""
    points = om.MFnMesh(_dag_path(mesh)).getPoints(om.MSpace.kObject)
    cells = {}
    for p in points:
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


_IDENTITY = {"translate": (0, 0, 0), "rotate": (0, 0, 0), "scale": (1, 1, 1), "shear": (0, 0, 0)}


def _find_transforms(mesh):
    for attr, identity in _IDENTITY.items():
        values = cmds.getAttr(f"{mesh}.{attr}")[0]
        if any(abs(v - i) > TOLERANCE for v, i in zip(values, identity)):
            return [mesh]
    return []


def _fix_transforms(meshes):
    for mesh in meshes:
        cmds.makeIdentity(mesh, apply=True, translate=True, rotate=True, scale=True, normal=False)


# Nodes in a mesh's history that aren't modeling history.
_NOT_HISTORY = ("geometryFilter", "tweak", "groupParts", "groupId", "shadingEngine", "objectSet")


def _find_history(mesh):
    found = cmds.listHistory(_mesh_shape(mesh), pruneDagObjects=True) or []
    if any(not any(cmds.objectType(node, isAType=kind) for kind in _NOT_HISTORY) for node in found):
        return [mesh]
    return []


def _fix_history(meshes):
    # Keeps deformers (skin, blendShapes, ...) and removes the rest.
    cmds.bakePartialHistory(meshes, prePostDeformers=True)


def _find_names(mesh):
    return [mesh] if len(cmds.ls(short_name(mesh))) > 1 else []


def _find_shape_names(mesh):
    return [mesh] if short_name(_mesh_shape(mesh)) != f"{short_name(mesh)}Shape" else []


def _fix_shape_names(meshes):
    for mesh in meshes:
        cmds.rename(_mesh_shape(mesh), f"{short_name(mesh)}Shape")


def _counted(singular, plural_form=None, after=""):
    """Problem text counting what was found, e.g. ``3 faces with more than 4 sides``."""

    def text(mesh, items):
        return f"{plural(len(items), singular, plural_form)}{after}"

    return text


def _per_mesh(find, text):
    """A check function: ``find(mesh)`` on each mesh among ``nodes``, one
    :class:`Problem` per mesh that has something, selecting what it found."""

    def run(nodes):
        problems = []
        for mesh in datatypes.meshes(nodes):
            items = find(mesh)
            if items:
                problems.append(Problem(f"{short(mesh)}: {text(mesh, items)}", items))
        return problems

    return run


def _with_meshes(fix):
    """``fix(meshes)`` as a check's ``fix(nodes)``: on the meshes among ``nodes``."""
    return lambda nodes: fix(datatypes.meshes(nodes))


def _shape_name_text(mesh, items):
    return f"shape is {short_name(_mesh_shape(mesh))}, not {short_name(mesh)}Shape"


CHECKS = (
    Check("ngons", "N-gons", "Faces with more than four sides.",
          _per_mesh(_find_ngons, _counted("face", after=" with more than 4 sides"))),
    Check("non_manifold", "Non-manifold", "Edges shared by more than two faces, and bow-tie vertices.",
          _per_mesh(_find_non_manifold, _counted("non-manifold edge or vertex", "non-manifold edges or vertices"))),
    Check("lamina", "Lamina faces", "Faces that share all their edges with another face.",
          _per_mesh(_find_lamina, _counted("lamina face"))),
    Check("zero_area", "Zero-area faces", "Faces with (almost) no area.",
          _per_mesh(_find_zero_area, _counted("zero-area face"))),
    Check("zero_length", "Zero-length edges", "Edges with (almost) no length.",
          _per_mesh(_find_zero_length, _counted("zero-length edge"))),
    Check("uvs", "Missing UVs", "Faces with no UVs in the current UV set. Not run before publishing.",
          _per_mesh(_find_uvs, _counted("face", after=" without UVs")), publish=False),
    Check("normals", "Locked normals", "Vertices with locked (user-set) normals.",
          _per_mesh(_find_normals, _counted("vertex", "vertices", " with locked normals")),
          fix=_with_meshes(_fix_normals)),
    Check("symmetry", "Not symmetric",
          "Vertices with no mirror vertex across X (object space). Not run before publishing.",
          _per_mesh(_find_symmetry, _counted("vertex", "vertices", " with no mirror across X")), publish=False),
    Check("transforms", "Unfrozen transform", "Translate, rotate, scale or shear not at their defaults.",
          _per_mesh(_find_transforms, lambda mesh, items: "transform not frozen"),
          fix=_with_meshes(_fix_transforms)),
    Check("history", "Construction history", "Modeling history (deformers don't count).",
          _per_mesh(_find_history, lambda mesh, items: "construction history"),
          fix=_with_meshes(_fix_history)),
    Check("names", "Duplicate name", "Another node has the same name; tools find meshes by name.",
          _per_mesh(_find_names, lambda mesh, items: f"another node is called {short_name(mesh)}")),
    Check("shape_names", "Shape name", "The shape isn't called <mesh>Shape.",
          _per_mesh(_find_shape_names, _shape_name_text), fix=_with_meshes(_fix_shape_names)),
)  # fmt: skip
