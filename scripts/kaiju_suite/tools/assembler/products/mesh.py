"""Mesh (.mesh): polygon meshes saved as data and rebuilt as new meshes.

Publish saves the selected meshes: name, parent name, local transform,
object-space points, topology, UV sets, hard edges, locked (user) normals
and color sets (vertex colors). Files saved before normals and color sets
were added still load, without them. Run always creates
new meshes (with ``MFnMesh.create``) and never changes existing ones: a name
that's taken gets the next free one (``body`` → ``body1``, shape
``body1Shape``). Each new mesh gets ``initialShadingGroup``, and goes under
the scene's node with its saved parent name if there is one, otherwise under
the world.

Geometry goes through OpenMaya 2 for speed. The mesh shape is created by the
API under a transform made with cmds, so undoing the transform's creation
removes the shape with it and one undo still reverts a whole Run.
"""

from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.core.selection import short_name
from kaiju_suite.tools.assembler import compare, data

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
            transforms.append(data.parent_of(node))
        else:
            others.append(node)
    return list(dict.fromkeys(transforms)), list(dict.fromkeys(others))


def _mfn(path):
    sel = om.MSelectionList()
    sel.add(path)
    return om.MFnMesh(sel.getDagPath(0))


def _record(transform):
    parent = data.parent_of(transform)
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


def _compare_record(old, new):
    """What changed on one mesh, as lines without its name."""
    lines = []
    topology = ("face_counts", "face_connects")
    old_points, new_points = old["points"], new["points"]
    if len(old_points) != len(new_points) or any(old[k] != new[k] for k in topology):
        lines.append(
            f"topology changed ({len(old_points)} → {len(new_points)} vertices, "
            f"{len(old['face_counts'])} → {len(new['face_counts'])} faces)"
        )
    else:
        moves = [compare.distance(a, b) for a, b in zip(old_points, new_points) if a != b]
        if moves:
            points = data.plural(len(new_points), "point")
            lines.append(f"{len(moves)} of {points} moved (largest move {compare.num(max(moves))})")
    if old.get("uv_sets") != new.get("uv_sets"):
        lines.append("UVs changed")
    if old.get("hard_edges") != new.get("hard_edges"):
        lines.append("hard edges changed")
    # Files published before normals and colors were saved have neither: same as none.
    if (old.get("normals") or []) != (new.get("normals") or []):
        lines.append("normals changed")
    if (old.get("color_sets") or []) != (new.get("color_sets") or []):
        lines.append("vertex colors changed")
    if old.get("parent") != new.get("parent"):
        lines.append(f"parent {old.get('parent') or 'world'} → {new.get('parent') or 'world'}")
    skip = {"name", "points", "uv_sets", "hard_edges", "normals", "color_sets", "parent", *topology}
    for key in dict.fromkeys([*old, *new]):
        if key not in skip and old.get(key) != new.get(key):
            lines.append(f"{key} changed")
    return lines


class MeshProduct(data.DataProduct):
    name = "Mesh"
    utility = "Mesh Tool"
    kind = "mesh"
    extension = ".mesh"
    order = 50
    menu_slot = (2, 0)

    def selection_problems(self):
        selection = cmds.ls(selection=True)
        if not selection:
            return ["Nothing selected. Select the meshes to publish."]
        transforms, others = _split_selection(selection)
        if others:
            names = ", ".join(short_name(n) for n in others)
            return [f"Not meshes: {names}. Select only meshes to publish."]
        if not transforms:
            return ["No meshes selected. Select the meshes to publish."]
        return []

    def gather(self, selection):
        transforms, others = _split_selection(selection)
        if others:
            raise RuntimeError(f"Not meshes: {', '.join(short_name(n) for n in others)}")
        if not transforms:
            raise RuntimeError("No meshes selected to publish.")
        return {"meshes": [_record(t) for t in transforms]}

    def apply(self, payload):
        records = payload["meshes"]
        parents = data.outside_parents(records)
        uuids, renamed = [], []
        for record in records:
            uuid = data.create_node("transform", record["name"], parents.get(record["parent"]))
            transform = data.node_path(uuid)
            for attr in _VECTORS:
                cmds.setAttr(f"{transform}.{attr}", *record[attr])
            cmds.setAttr(f"{transform}.rotateOrder", record["rotateOrder"])
            shape = _build_shape(transform, record)
            leaf = short_name(transform)
            cmds.rename(shape, data.unique_name(f"{leaf}Shape"))
            cmds.sets(data.node_path(uuid), edit=True, forceElement="initialShadingGroup")
            uuids.append(uuid)
            if leaf != record["name"]:
                renamed.append(f"{record['name']} → {leaf}")
        message = f"Created {len(records)} mesh{'es' if len(records) != 1 else ''}"
        if renamed:
            message += f" (names taken, renamed: {', '.join(renamed)})"
        return message

    def nodes(self, payload):
        return [r["name"] for r in payload["meshes"]]

    def describe(self, payload):
        records = payload["meshes"]
        return [
            f"{len(records)} mesh{'es' if len(records) != 1 else ''}",
            ", ".join(r["name"] for r in records),
        ]

    def compare(self, old, new):
        added, removed, common = compare.match(old["meshes"], new["meshes"], "name")
        lines = []
        if added:
            lines.append(f"Added meshes: {', '.join(added)}")
        if removed:
            lines.append(f"Removed meshes: {', '.join(removed)}")
        for name, a, b in common:
            lines.extend(f"{name}: {line}" for line in _compare_record(a, b))
        return compare.finish(lines)


PRODUCT = MeshProduct()
