"""DeltaMush Tool: add a deltaMush and edit where it acts. No Qt here.

A deltaMush's per-vertex weights say how much it smooths each vertex: 0
leaves the vertex as the deformers below made it, 1 smooths it fully.
:func:`add` starts them at 0 so you paint in only the area you need, with
Maya's Paint Attributes tool on :func:`paint_attribute`. Every edit goes
through undoable Maya commands, so each function is one undo step.
"""

from maya import cmds
from maya.api import OpenMaya as om
from maya.api import OpenMayaAnim as oma

from kaiju_suite.core.undo import undoable


def _shape(transform):
    shapes = cmds.listRelatives(transform, shapes=True, noIntermediate=True, type="mesh", fullPath=True)
    return shapes[0] if shapes else None


def _mobject(node):
    return om.MSelectionList().add(node).getDependNode(0)


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


def components_of(mesh, selection):
    """The components in ``selection`` that belong to ``mesh``."""
    return [c for c in cmds.ls(selection, long=True) or [] if "." in c and meshes([c]) == [mesh]]


def _index(node, mesh):
    """The index of ``mesh`` in deformer ``node``'s geometry, or ``None``."""
    try:
        return oma.MFnGeometryFilter(_mobject(node)).indexForOutputShape(_mobject(_shape(mesh)))
    except RuntimeError:
        return None


def delta_mushes(mesh):
    """The deltaMush nodes deforming ``mesh``, first evaluated first."""
    history = cmds.ls(cmds.listHistory(_shape(mesh)) or [], type="deltaMush") or []
    return [node for node in reversed(history) if _index(node, mesh) is not None]


def paint_attribute(node):
    """What Maya's Paint Attributes tool (``artAttrCtx``) paints for ``node``."""
    return f"deltaMush.{node}.weights"


# -- weights ----------------------------------------------------------------


def weights(node, mesh):
    """Every vertex's weight on ``node``, in vertex order (unset ones are 1)."""
    count = cmds.polyEvaluate(mesh, vertex=True)
    fn = om.MFnDependencyNode(_mobject(node))
    plug = fn.findPlug("weightList", False).elementByLogicalIndex(_index(node, mesh)).child(fn.attribute("weights"))
    found = [1.0] * count
    for i in range(plug.numElements()):
        element = plug.elementByPhysicalIndex(i)
        if element.logicalIndex() < count:
            found[element.logicalIndex()] = element.asDouble()
    return found


def _write(node, mesh, values):
    """Set every vertex's weight (an undoable ``setAttr`` on the whole range)."""
    plug = f"{node}.weightList[{_index(node, mesh)}].weights[0:{len(values) - 1}]"
    cmds.setAttr(plug, *values, size=len(values))


@undoable
def add(meshes, weight=0.0):
    """Add a deltaMush on top of each mesh's deformers, every weight set to
    ``weight``; returns the new nodes."""
    nodes = []
    for mesh in meshes:
        node = cmds.deltaMush(mesh)[0]
        _write(node, mesh, [weight] * cmds.polyEvaluate(mesh, vertex=True))
        nodes.append(node)
    return nodes


@undoable
def set_weights(node, components, value):
    """Set the weight of the vertices in ``components`` (any components;
    faces and edges stand for their vertices) to ``value``."""
    vertices = cmds.polyListComponentConversion(components, toVertex=True) or []
    if vertices:
        cmds.percent(node, vertices, value=value)


@undoable
def flood(node, mesh, value):
    """Set every vertex of ``mesh`` to ``value``."""
    _write(node, mesh, [value] * cmds.polyEvaluate(mesh, vertex=True))


@undoable
def invert(node, mesh):
    """Swap where the deltaMush acts: each weight ``w`` becomes ``1 - w``."""
    _write(node, mesh, [1.0 - w for w in weights(node, mesh)])


def _mirror_map(mesh):
    """For each vertex, the vertex closest to its mirror image across X
    (object space)."""
    fn = om.MFnMesh(om.MSelectionList().add(_shape(mesh)).getDagPath(0))
    points = fn.getPoints(om.MSpace.kObject)
    mirror = []
    for p in points:
        image = om.MPoint(-p.x, p.y, p.z)
        _, face = fn.getClosestPoint(image, om.MSpace.kObject)
        candidates = fn.getPolygonVertices(face)
        mirror.append(min(candidates, key=lambda v: points[v].distanceTo(image)))
    return mirror


@undoable
def mirror_weights(node, mesh, positive_to_negative=True):
    """Copy the weights of one half of ``mesh`` (object-space X) onto the
    other half; vertices on the middle keep theirs."""
    values = weights(node, mesh)
    points = om.MFnMesh(om.MSelectionList().add(_shape(mesh)).getDagPath(0)).getPoints(om.MSpace.kObject)
    mirror = _mirror_map(mesh)
    result = list(values)
    for v, p in enumerate(points):
        if (p.x < 0) if positive_to_negative else (p.x > 0):
            result[v] = values[mirror[v]]
    _write(node, mesh, result)


def affected(node, mesh):
    """The vertices of ``mesh`` the deltaMush acts on (weight above 0)."""
    return [f"{mesh}.vtx[{v}]" for v, w in enumerate(weights(node, mesh)) if w > 1e-6]
