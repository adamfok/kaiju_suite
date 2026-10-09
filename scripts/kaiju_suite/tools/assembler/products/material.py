"""Material (.mat): shading networks and their assignments, saved as data.

Publish takes the selected meshes or faces. It saves the shading groups on
them and the networks upstream (materials, file textures, place2d nodes, ...)
as mayaAscii text, plus the assignments: shading group → whole meshes
(``body_geo``) or face ranges (``head_geo.f[0:9]``), by mesh name. The
default ``initialShadingGroup`` and its lambert1 aren't saved, but
assignments to it are. Texture images stay where they are, by path.

The network text is a stripped mayaAscii export (``exportSelectedStrict`` of
the shading groups and their upstream nodes, which doesn't bring member
meshes along). Lines that would touch scene-wide nodes (``select -ne :...``),
UUIDs, file info and dates are dropped, so publishing unchanged content
gives the same text.

Run checks first that every assigned mesh exists. It then creates the
network by evaluating that text as MEL in a temporary namespace, rather than
importing a file, because a file import clears the undo queue: this way a
Run is one undo step. A created node whose name an existing node of the same
type already has is dropped and the existing node is used instead, as it
is (the file's values don't overwrite it); its connections into the new
network move to the existing node. Created nodes that then feed no new
shading group are deleted, and the rest leave the namespace with their own
names (numbered if a node of another type has the name). Last, the
assignments are applied with ``sets -forceElement``.
"""

import glob
import os
import re
import shlex
import tempfile

from maya import cmds, mel

from kaiju_suite.core.log import get_logger
from kaiju_suite.tools.assembler import data

log = get_logger(__name__)

DEFAULT_SG = "initialShadingGroup"

# shadingEngine inputs that are membership, not network.
_MEMBER_ATTRS = {"dagSetMembers", "dnSetMembers", "groupNodes", "memberWireframeColor", "partition"}
# DAG nodes that belong to a shading network rather than to the geometry.
_DAG_NETWORK_TYPES = {"place3dTexture"}
# mayaAscii statements dropped from the network text.
_DROPPED = ("//", "fileInfo", "currentUnit", "dataStructure", "applyMetadata", "select -ne", "select -noExpand")
_NAMESPACE = "kaiju_material"
_CONNECT = re.compile(r'^connectAttr\s+"([^"]+)"\s+"([^"]+)"')
_FACE = re.compile(r"\.f\[(\d+)(?::(\d+))?\]$")
_TOKEN = re.compile(r"<[^>]+>")


# -- publish ----------------------------------------------------------------


def _transform(shape):
    return cmds.listRelatives(shape, parent=True, fullPath=True)[0]


def _selected_meshes(selection):
    """``{mesh shape: selected face indices, or None for the whole mesh}``,
    from a selection of transforms, mesh shapes and faces."""
    found = {}
    objects = [s for s in selection if "." not in s]
    components = [s for s in selection if "." in s]
    for node in objects:
        if cmds.nodeType(node) == "mesh":
            shapes = [node]
        else:
            shapes = cmds.listRelatives(node, shapes=True, type="mesh", noIntermediate=True, fullPath=True) or []
        for shape in cmds.ls(shapes, long=True):
            found[shape] = None
    for face in cmds.filterExpand(components, selectionMask=34, fullPath=True) or []:
        owner = cmds.ls(face, objectsOnly=True, long=True)[0]
        if found.get(owner, ()) is None:
            continue  # the whole mesh is selected too
        found.setdefault(owner, set()).update(_face_indices(face))
    return found


def _face_indices(member):
    match = _FACE.search(member)
    if not match:
        return set()
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else start
    return set(range(start, end + 1))


def _ranges(indices):
    """Sorted face indices as ``f[...]`` ranges: ``{0, 1, 2, 5}`` → ``['f[0:2]', 'f[5]']``."""
    out, ordered = [], sorted(indices)
    start = prev = None
    for index in ordered + [None]:
        if start is not None and index == prev + 1:
            prev = index
            continue
        if start is not None:
            out.append(f"f[{start}]" if start == prev else f"f[{start}:{prev}]")
        start = prev = index
    return out


def _sg_faces(shape):
    """``{shadingEngine: face indices on shape, or None if it holds the whole shape}``."""
    transform = _transform(shape)
    found = {}
    for sg in sorted(set(cmds.listConnections(shape, type="shadingEngine") or [])):
        for member in cmds.sets(sg, query=True) or []:
            if "." in member:
                if cmds.ls(member, objectsOnly=True, long=True)[0] != shape:
                    continue
                for face in cmds.ls(member, flatten=True):
                    indices = found.setdefault(sg, set())
                    if indices is not None:
                        indices.update(_face_indices(face))
            elif cmds.ls(member, long=True)[0] in (shape, transform):
                found[sg] = None
    return found


def _assignments(meshes):
    """``{shadingEngine: sorted members}`` for the selected meshes and faces."""
    found = {}
    for shape, selected in meshes.items():
        name = cmds.ls(_transform(shape))[0]  # shortest unique name
        face_count = cmds.polyEvaluate(shape, face=True)
        for sg, faces in _sg_faces(shape).items():
            if faces is None and selected is None:
                found.setdefault(sg, []).append(name)
                continue
            faces = set(range(face_count)) if faces is None else faces
            if selected is not None:
                faces &= selected
            found.setdefault(sg, []).extend(f"{name}.{r}" for r in _ranges(faces))
    return {sg: sorted(members) for sg, members in sorted(found.items()) if members}


def _network(shading_engines):
    """The shading groups and every node upstream of them, except member
    geometry, its groupIds and Maya's default nodes."""
    defaults = set(cmds.ls(defaultNodes=True) or [])
    nodes = []
    for sg in shading_engines:
        nodes.append(sg)
        pairs = cmds.listConnections(sg, source=True, destination=False, connections=True, plugs=True) or []
        for dest, source in zip(pairs[::2], pairs[1::2]):
            attr = dest.split(".", 1)[1].split("[", 1)[0]
            if attr in _MEMBER_ATTRS:
                continue
            nodes.extend(cmds.listHistory(source.split(".", 1)[0]) or [])
    kept = []
    for node in dict.fromkeys(cmds.ls(nodes)):
        if node in defaults or cmds.nodeType(node) == "groupId":
            continue
        if cmds.ls(node, dag=True) and cmds.nodeType(node) not in _DAG_NETWORK_TYPES:
            continue
        kept.append(node)
    return kept


def _strip(text):
    """Keep the statements that build the network; drop the rest (see module doc)."""
    kept, skipping = [], False
    for line in text.splitlines():
        if line[:1] in ("\t", " "):
            if not skipping and not line.strip().startswith("rename -uid"):
                kept.append(line)
            continue
        skipping = line.startswith(_DROPPED)
        if not skipping:
            kept.append(line)
    return "\n".join(kept) + "\n"


def _export(nodes):
    """The stripped mayaAscii text of ``nodes``. Restores the selection."""
    previous = cmds.ls(selection=True, long=True) or []
    folder = tempfile.mkdtemp(prefix="kaiju_material_")
    path = os.path.join(folder, "network.ma")
    try:
        cmds.select(nodes, noExpand=True, replace=True)
        cmds.file(path, exportSelectedStrict=True, type="mayaAscii", force=True, preserveReferences=False)
        with open(path, encoding="utf-8", errors="replace") as f:
            return _strip(f.read())
    finally:
        if previous:
            cmds.select(previous, replace=True)
        else:
            cmds.select(clear=True)
        if os.path.exists(path):
            os.remove(path)
        os.rmdir(folder)


def _textures(nodes):
    return sorted({p for p in (cmds.getAttr(f"{n}.fileTextureName") for n in cmds.ls(nodes, type="file")) if p})


def _texture_exists(path):
    path = cmds.workspace(expandName=path)
    if _TOKEN.search(path):  # <UDIM>, <f>, ...: any matching file will do
        return bool(glob.glob(_TOKEN.sub("*", path)))
    return os.path.isfile(path)


def _network_of_selection():
    meshes = _selected_meshes(cmds.ls(selection=True, long=True) or [])
    assignments = _assignments(meshes)
    return meshes, assignments, _network([sg for sg in assignments if sg != DEFAULT_SG])


# -- run --------------------------------------------------------------------


def _mesh_of(member):
    return member.split(".", 1)[0]


def _blocks(text):
    """Statements: a top-level line and the indented lines that follow it."""
    blocks = []
    for line in text.splitlines():
        if line[:1] in ("\t", " ") and blocks:
            blocks[-1] += "\n" + line
        elif line.strip():
            blocks.append(line)
    return blocks


def _load_plugins(blocks):
    """Load the plug-ins the network's ``requires`` lines name. Raises if one can't be."""
    failed = []
    for block in blocks:
        if not block.startswith("requires"):
            continue
        tokens = shlex.split(block.rstrip(";").strip())[1:]
        positional = []
        while tokens:
            token = tokens.pop(0)
            if token.startswith("-"):
                if tokens:
                    tokens.pop(0)
                continue
            positional.append(token)
        plugin = positional[0] if positional else "maya"
        if plugin == "maya" or cmds.pluginInfo(plugin, query=True, loaded=True):
            continue
        try:
            cmds.loadPlugin(plugin, quiet=True)
        except RuntimeError:
            failed.append(plugin)
    if failed:
        raise RuntimeError(f"Can't load the plug-ins this material needs: {', '.join(failed)}")


def _free_namespace():
    name, number = _NAMESPACE, 1
    while cmds.namespace(exists=f":{name}"):
        number += 1
        name = f"{_NAMESPACE}{number}"
    return name


def _create_in_namespace(blocks, namespace):
    """Evaluate the network statements with ``namespace`` current. Returns
    the nodes they created."""
    cmds.namespace(add=namespace)
    relative = cmds.namespace(query=True, relativeNames=True)
    cmds.namespace(set=f":{namespace}")
    cmds.namespace(relativeNames=True)
    try:
        for block in blocks:
            if block.startswith("requires"):
                continue
            connect = _CONNECT.match(block)
            if connect and cmds.objExists(connect.group(1)) and cmds.objExists(connect.group(2)):
                # Some nodes connect themselves on creation (file → color management).
                if cmds.isConnected(connect.group(1), connect.group(2)):
                    continue
            try:
                mel.eval(block)
            except RuntimeError:
                if block.startswith("createNode"):
                    raise
                log.warning("Material: skipped %s", block.splitlines()[0])
    finally:
        cmds.namespace(relativeNames=relative)
        cmds.namespace(set=":")
    return cmds.ls(f":{namespace}:*") or []


def _bare(node):
    return node.rsplit(":", 1)[-1]


def _settle(created, namespace):
    """Reuse existing same-named nodes, delete what's left unused, and move
    the rest out of ``namespace``. Returns ``(names, reused)``: each created
    shading group's file name → its node in the scene, and the names of the
    existing nodes used."""
    reuse = {}
    for node in created:
        if cmds.nodeType(node) == "materialInfo":
            continue
        existing = cmds.ls(f":{_bare(node)}")
        if existing and cmds.nodeType(existing[0]) == cmds.nodeType(node):
            reuse[node] = existing[0]

    kept_created = set(created) - set(reuse)
    for node, existing in reuse.items():
        pairs = cmds.listConnections(node, source=False, destination=True, connections=True, plugs=True) or []
        for source, dest in zip(pairs[::2], pairs[1::2]):
            if cmds.ls(dest, objectsOnly=True)[0] in kept_created:
                cmds.connectAttr(f"{existing}.{source.split('.', 1)[1]}", dest, force=True)

    new_sgs = [n for n in kept_created if cmds.nodeType(n) == "shadingEngine"]
    keep = set()
    for sg in new_sgs:
        keep.update(n for n in cmds.ls(cmds.listHistory(sg) or []) if n in kept_created)
        keep.update(n for n in cmds.listConnections(f"{sg}.message", type="materialInfo") or [] if n in kept_created)
    unused = [n for n in created if n not in keep and cmds.objExists(n)]
    if unused:
        cmds.delete(unused)

    names = {_bare(n): e for n, e in reuse.items() if cmds.nodeType(e) == "shadingEngine"}
    for node in sorted(keep):
        renamed = cmds.rename(node, f":{data.unique_name(_bare(node))}")
        if node in new_sgs:
            names[_bare(node)] = renamed
    cmds.namespace(removeNamespace=f":{namespace}", mergeNamespaceWithRoot=True)
    return names, sorted(set(reuse.values()))


class MaterialProduct(data.DataProduct):
    name = "Material"
    kind = "material"
    extension = ".mat"
    order = 90

    def selection_problems(self):
        if not cmds.ls(selection=True):
            return ["Nothing selected. Select the meshes or faces to publish."]
        meshes, assignments, network = _network_of_selection()
        if not meshes:
            return ["No meshes or faces selected. Select the meshes or faces to publish."]
        return []

    def selection_warnings(self):
        meshes, assignments, network = _network_of_selection()
        missing = [p for p in _textures(network) if not _texture_exists(p)]
        if missing:
            return [f"Texture files not found: {', '.join(missing)}"]
        return []

    def gather(self, selection):
        meshes = _selected_meshes(selection)
        if not meshes:
            raise RuntimeError("No meshes or faces selected to publish.")
        assignments = _assignments(meshes)
        shading_engines = [sg for sg in assignments if sg != DEFAULT_SG]
        network = _network(shading_engines)
        return {
            "shading_engines": shading_engines,
            "assignments": assignments,
            "textures": _textures(network),
            "network": _export(network) if network else "",
        }

    def apply(self, payload):
        assignments = payload["assignments"]
        meshes = sorted({_mesh_of(m) for members in assignments.values() for m in members})
        data.require_nodes(meshes, "meshes")
        blocks = _blocks(payload["network"])
        _load_plugins(blocks)

        names, reused = {DEFAULT_SG: DEFAULT_SG}, []
        if payload["shading_engines"]:
            namespace = _free_namespace()
            created = _create_in_namespace(blocks, namespace)
            settled, reused = _settle(created, namespace)
            names.update(settled)
        missing = [sg for sg in assignments if sg not in names]
        if missing:
            raise RuntimeError(f"The file's network didn't create: {', '.join(missing)}")

        # Whole meshes first, so face assignments then split them.
        for whole in (True, False):
            for sg, members in assignments.items():
                chosen = [m for m in members if ("." not in m) == whole]
                if chosen:
                    cmds.sets(chosen, forceElement=names[sg])

        message = f"Assigned {data.plural(len(assignments), 'shading group')} to {data.plural(len(meshes), 'mesh', 'meshes')}"
        if reused:
            message += f" (used existing: {', '.join(reused)})"
        return message

    def describe(self, payload):
        sgs = payload["shading_engines"]
        meshes = sorted({_mesh_of(m) for members in payload["assignments"].values() for m in members})
        return [
            f"{data.plural(len(sgs), 'shading group')}: {', '.join(sgs)}" if sgs else "0 shading groups",
            f"{data.plural(len(meshes), 'mesh', 'meshes')}: {', '.join(meshes)}",
            data.plural(len(payload["textures"]), "texture"),
        ]


PRODUCT = MaterialProduct()
