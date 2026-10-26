"""Deformer weight-map helpers shared by tools and rig data. No Qt here.

Works on any ``geometryFilter`` (cluster, softMod, wire, ffd, nonLinear,
deltaMush, ...): which index a shape has in a deformer, which vertices it
deforms, and its per-vertex weights, read sparsely (only weights that
aren't 1.0).
"""

from maya import cmds
import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma

_DIGITS = 6


def _mobject(node):
    return om.MSelectionList().add(node).getDependNode(0)


def geometry_index(node, shape):
    """The index of ``shape`` in deformer ``node``'s geometry, or ``None``."""
    try:
        return oma.MFnGeometryFilter(_mobject(node)).indexForOutputShape(_mobject(shape))
    except RuntimeError:
        return None


def deformers_on(shape, node_types):
    """The deformers of ``node_types`` deforming ``shape``, first evaluated
    first. Deformers only upstream (e.g. on a lattice feeding an ffd) are left out."""
    history = cmds.ls(cmds.listHistory(shape) or [], type=list(node_types)) or []
    return [n for n in reversed(history) if geometry_index(n, shape) is not None]


def members(node, index, vertex_count):
    """The vertices deformer ``node`` deforms at geometry ``index``, as sorted
    inclusive ``[first, last]`` ranges, or ``None`` for the whole mesh."""
    component = oma.MFnGeometryFilter(_mobject(node)).getComponentAtIndex(index)
    if component.isNull():
        return None
    fn = om.MFnSingleIndexedComponent(component)
    vertices = sorted(set(v for v in fn.getElements() if v < vertex_count))
    if fn.isComplete or len(vertices) == vertex_count:
        return None
    ranges = []
    for vertex in vertices:
        if ranges and vertex == ranges[-1][1] + 1:
            ranges[-1][1] = vertex
        else:
            ranges.append([vertex, vertex])
    return ranges


def member_components(shape, ranges):
    """What to pass a deformer command to deform ``ranges`` (see :func:`members`) of ``shape``."""
    if ranges is None:
        return [shape]
    return [f"{shape}.vtx[{first}:{last}]" for first, last in ranges]


def _weights_plug(node, index):
    fn = om.MFnDependencyNode(_mobject(node))
    return fn.findPlug("weightList", False).elementByLogicalIndex(index).child(fn.attribute("weights"))


def read_weights(node, index, vertex_count):
    """Sparse ``[vertex, weight]`` pairs of the weights that aren't 1.0."""
    plug = _weights_plug(node, index)
    weights = []
    for i in range(plug.numElements()):
        element = plug.elementByPhysicalIndex(i)
        vertex = element.logicalIndex()
        weight = round(element.asDouble(), _DIGITS)
        if vertex < vertex_count and weight != 1.0:
            weights.append([vertex, weight])
    return sorted(weights)


def write_weights(node, index, weights):
    """Set the sparse ``[vertex, weight]`` pairs from :func:`read_weights`."""
    for vertex, weight in weights:
        cmds.setAttr(f"{node}.weightList[{index}].weights[{vertex}]", weight)
