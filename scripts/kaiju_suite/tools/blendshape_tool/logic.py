"""BlendShape Tool: corrective shapes for skinned meshes. No Qt here.

The workflow: pose the rig, :func:`start_sculpt` to get a copy of the posed
mesh, sculpt the fix on the copy, then :func:`create_corrective`. That works
out the shape which, put *before* the skinCluster, makes the posed mesh look
like the sculpt, and adds it as a target on a blendShape at the front of the
deformer chain (made if the mesh has none there yet).

How the inversion works, without a plugin: every deformer after the
blendShape that is linear per vertex (a skinCluster with linear skinning, a
cluster, ...) turns a vertex's pre-skin position ``x`` into
``A_v * x + t_v``. Setting the new target's deltas to 0, then to a unit offset
along X, Y and Z, and reading the deformed mesh four times gives every
vertex's ``A_v`` and ``t_v`` exactly, so each delta is solved directly. For
deformers that aren't linear (deltaMush, wrap, ...) the same solve is
repeated on what's left over a few times, which gets close but not exact.

A pose reader (:func:`create_pose_reader`) outputs 1 when a joint's axis
points where it did when the reader was made, falling to 0 once it's
``cone_angle`` degrees away; :func:`drive_target` connects it to a target's
weight. Every scene change is one undo step.
"""

import re

from maya import cmds
from maya.api import OpenMaya as om
from maya.api import OpenMayaAnim as oma

from kaiju_suite.core.log import get_logger
from kaiju_suite.core.selection import short_name
from kaiju_suite.core.undo import undoable

log = get_logger(__name__)

SCULPT_ATTR = "kaijuSculptBase"
READER_ATTR = "kaijuPoseReader"
_ITEM = 6000  # inputTargetItem index of a target at full weight.
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_AXES = {
    "x": (1, 0, 0),
    "y": (0, 1, 0),
    "z": (0, 0, 1),
    "-x": (-1, 0, 0),
    "-y": (0, -1, 0),
    "-z": (0, 0, -1),
}
# Stop refining the inversion once every vertex is this close to the sculpt.
_TOLERANCE = 1e-6
_REFINE_STEPS = 4


# -- finding ----------------------------------------------------------------


def _shape(transform):
    shapes = cmds.listRelatives(transform, shapes=True, noIntermediate=True, type="mesh", fullPath=True)
    return shapes[0] if shapes else None


def _mobject(node):
    return om.MSelectionList().add(node).getDependNode(0)


def _world_points(mesh):
    path = om.MSelectionList().add(_shape(mesh)).getDagPath(0)
    return om.MFnMesh(path).getPoints(om.MSpace.kWorld)


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


def _index(node, mesh):
    """The index of ``mesh`` in deformer ``node``'s geometry, or ``None``."""
    try:
        return oma.MFnGeometryFilter(_mobject(node)).indexForOutputShape(_mobject(_shape(mesh)))
    except RuntimeError:
        return None


def blend_shapes(mesh):
    """The blendShape nodes deforming ``mesh``, first evaluated first."""
    history = cmds.ls(cmds.listHistory(_shape(mesh)) or [], type="blendShape") or []
    return [node for node in reversed(history) if _index(node, mesh) is not None]


def skin_cluster(mesh):
    """The skinCluster deforming ``mesh``, or ``None``."""
    found = cmds.ls(cmds.listHistory(_shape(mesh)) or [], type="skinCluster")
    return found[0] if found else None


def _front_blend_shape(mesh):
    """A blendShape on ``mesh`` that is evaluated before its skinCluster."""
    skin = skin_cluster(mesh)
    for node in blend_shapes(mesh):
        if skin is None or skin in (cmds.listHistory(node, future=True) or []):
            return node
    return None


# -- sculpting --------------------------------------------------------------


@undoable
def start_sculpt(mesh):
    """Duplicate ``mesh`` as it's posed now, as a mesh to sculpt the
    corrective on, and hide ``mesh``; returns the sculpt."""
    sculpt = cmds.duplicate(mesh, name=f"{short_name(mesh)}_sculpt", returnRootsOnly=True)[0]
    sculpt = cmds.ls(sculpt, long=True)[0]
    intermediates = cmds.listRelatives(sculpt, shapes=True, fullPath=True) or []
    intermediates = [s for s in intermediates if cmds.getAttr(f"{s}.intermediateObject")]
    if intermediates:
        cmds.delete(intermediates)
    for channel in ("t", "r", "s"):
        for axis in "xyz":
            cmds.setAttr(f"{sculpt}.{channel}{axis}", lock=False)
    cmds.addAttr(sculpt, longName=SCULPT_ATTR, attributeType="message")
    cmds.connectAttr(f"{mesh}.message", f"{sculpt}.{SCULPT_ATTR}")
    cmds.setAttr(f"{mesh}.visibility", False)
    return sculpt


def sculpt_base(sculpt):
    """The mesh ``sculpt`` was started from, or ``None``."""
    if not cmds.attributeQuery(SCULPT_ATTR, node=sculpt, exists=True):
        return None
    found = cmds.listConnections(f"{sculpt}.{SCULPT_ATTR}", source=True, destination=False) or []
    return cmds.ls(found[0], long=True)[0] if found else None


def _check_name(name):
    if not _NAME.match(name or ""):
        raise ValueError(f"'{name}' isn't a valid target name: use letters, digits and _, not starting with a digit.")


def _free_name(node, wanted):
    names = {n for _, n in targets(node)}
    if wanted not in names and not cmds.attributeQuery(wanted, node=node, exists=True):
        return wanted
    i = 1
    while f"{wanted}{i}" in names or cmds.attributeQuery(f"{wanted}{i}", node=node, exists=True):
        i += 1
    return f"{wanted}{i}"


def _write_deltas(item, deltas):
    """Set a target item's deltas (``MVector`` per vertex), keeping only the
    vertices that move."""
    indices = [v for v, d in enumerate(deltas) if d.length() > _TOLERANCE]
    points = [(deltas[v].x, deltas[v].y, deltas[v].z, 1.0) for v in indices]
    components = [f"vtx[{v}]" for v in indices]
    cmds.setAttr(f"{item}.inputPointsTarget", len(points), *points, type="pointArray")
    cmds.setAttr(f"{item}.inputComponentsTarget", len(components), *components, type="componentList")


@undoable
def create_corrective(mesh, sculpt, name=None, blend_shape=None, keep_sculpt=False):
    """Add a target to ``mesh`` that, at weight 1 and in the current pose,
    makes it match ``sculpt``. The target goes on ``blend_shape``, or on a
    blendShape before the skin, made if needed. The sculpt is deleted (hidden
    with ``keep_sculpt``) and ``mesh`` shown again. Returns
    ``(blendShape, target name)``."""
    count = cmds.polyEvaluate(mesh, vertex=True)
    if cmds.polyEvaluate(sculpt, vertex=True) != count:
        raise ValueError(f"{short_name(sculpt)} doesn't have the same vertex count as {short_name(mesh)}.")
    if name is not None:
        _check_name(name)

    node = blend_shape or _front_blend_shape(mesh)
    if not node:
        node = cmds.blendShape(mesh, frontOfChain=True, name=f"{short_name(mesh)}_correctives")[0]
    if name is None:
        name = _free_name(node, "corrective")
    elif name in {n for _, n in targets(node)} or cmds.attributeQuery(name, node=node, exists=True):
        raise ValueError(f"{node} already has a target or attribute called {name}.")

    index = max(cmds.getAttr(f"{node}.weight", multiIndices=True) or [-1]) + 1
    cmds.setAttr(f"{node}.weight[{index}]", 1.0)
    cmds.aliasAttr(name, f"{node}.weight[{index}]")
    item = f"{node}.inputTarget[{_index(node, mesh)}].inputTargetGroup[{index}].inputTargetItem[{_ITEM}]"

    wanted = [om.MPoint(p) for p in _world_points(sculpt)]
    deltas = _invert(mesh, item, wanted, count)
    _write_deltas(item, deltas)

    if keep_sculpt:
        cmds.setAttr(f"{sculpt}.visibility", False)
    else:
        cmds.delete(sculpt)
    cmds.setAttr(f"{mesh}.visibility", True)
    return node, name


def _invert(mesh, item, wanted, count):
    """The deltas on ``item`` that make ``mesh`` (world space) reach ``wanted``."""

    def evaluate(offsets):
        _write_all(item, offsets)
        return [om.MPoint(p) for p in _world_points(mesh)]

    zero = [om.MVector()] * count
    base = evaluate(zero)
    columns = [evaluate([om.MVector(axis)] * count) for axis in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]

    inverses = []
    for v in range(count):
        rows = [columns[a][v] - base[v] for a in range(3)]
        matrix = om.MMatrix([*rows[0], 0, *rows[1], 0, *rows[2], 0, base[v].x, base[v].y, base[v].z, 1])
        inverses.append(matrix.inverse() if abs(matrix.det3x3()) > 1e-12 else None)

    deltas = []
    for v in range(count):
        if inverses[v] is None:
            log.warning("Vertex %d of %s doesn't move with its pre-skin position; left as is.", v, mesh)
            deltas.append(om.MVector())
        else:
            deltas.append(om.MVector(wanted[v] * inverses[v]))

    # Exact for linear deformers; non-linear ones (deltaMush, ...) need a few passes.
    for _ in range(_REFINE_STEPS):
        result = evaluate(deltas)
        errors = [wanted[v] - result[v] for v in range(count)]
        if max((e.length() for e in errors), default=0.0) < _TOLERANCE:
            break
        for v in range(count):
            if inverses[v] is not None:
                deltas[v] += errors[v] * inverses[v]
    return deltas


def _write_all(item, offsets):
    points = [(d.x, d.y, d.z, 1.0) for d in offsets]
    cmds.setAttr(f"{item}.inputPointsTarget", len(points), *points, type="pointArray")
    cmds.setAttr(f"{item}.inputComponentsTarget", 1, f"vtx[0:{len(points) - 1}]", type="componentList")


# -- targets ----------------------------------------------------------------


def targets(node):
    """``[(index, name), ...]`` for every target of blendShape ``node``."""
    found = []
    for index in cmds.getAttr(f"{node}.weight", multiIndices=True) or []:
        found.append((index, cmds.aliasAttr(f"{node}.weight[{index}]", query=True) or f"weight[{index}]"))
    return found


def _target_index(node, name):
    for index, found in targets(node):
        if found == name:
            return index
    raise ValueError(f"{node} has no target called {name}.")


def _weight_plug(node, name):
    return f"{node}.weight[{_target_index(node, name)}]"


def weight(node, name):
    """The current weight of target ``name``."""
    return cmds.getAttr(_weight_plug(node, name))


@undoable
def set_weight(node, name, value):
    """Set target ``name``'s weight; raises ``ValueError`` if something drives it."""
    plug = _weight_plug(node, name)
    if cmds.listConnections(plug, source=True, destination=False):
        raise ValueError(f"{name} is driven by {target_driver(node, name)}; disconnect it first.")
    cmds.setAttr(plug, value)


@undoable
def rename_target(node, old, new):
    """Rename target ``old`` to ``new``."""
    _check_name(new)
    plug = _weight_plug(node, old)
    if new != old and (new in {n for _, n in targets(node)} or cmds.attributeQuery(new, node=node, exists=True)):
        raise ValueError(f"{node} already has a target or attribute called {new}.")
    cmds.aliasAttr(new, plug)


@undoable
def delete_target(node, name):
    """Remove target ``name`` and its deltas from blendShape ``node``."""
    index = _target_index(node, name)
    plug = f"{node}.weight[{index}]"
    for source in cmds.listConnections(plug, source=True, destination=False, plugs=True) or []:
        cmds.disconnectAttr(source, plug)
    if cmds.aliasAttr(plug, query=True):
        cmds.aliasAttr(f"{node}.{name}", remove=True)
    for geo in cmds.getAttr(f"{node}.inputTarget", multiIndices=True) or []:
        group = f"{node}.inputTarget[{geo}].inputTargetGroup[{index}]"
        if index in (cmds.getAttr(f"{node}.inputTarget[{geo}].inputTargetGroup", multiIndices=True) or []):
            cmds.removeMultiInstance(group, b=True)
    cmds.removeMultiInstance(plug, b=True)


# -- pose readers -----------------------------------------------------------


@undoable
def create_pose_reader(joint, axis="x", cone_angle=90.0, name=None):
    """A reader whose output is 1 while ``joint``'s ``axis`` (in its parent's
    space) points where it does now, falling to 0 at ``cone_angle`` degrees
    away. Returns the reader (a remapValue node; see :func:`reader_output`)."""
    if axis not in _AXES:
        raise ValueError(f"Axis must be one of {', '.join(_AXES)}, not {axis}.")
    name = name or f"{short_name(joint)}_poseReader"
    direction = cmds.createNode("vectorProduct", name=f"{name}_direction")
    cmds.setAttr(f"{direction}.operation", 3)  # vector matrix product
    cmds.setAttr(f"{direction}.input1", *_AXES[axis])
    cmds.setAttr(f"{direction}.normalizeOutput", True)
    cmds.connectAttr(f"{joint}.matrix", f"{direction}.matrix")

    angle = cmds.createNode("angleBetween", name=f"{name}_angle")
    cmds.setAttr(f"{angle}.vector1", *cmds.getAttr(f"{direction}.output")[0])
    cmds.connectAttr(f"{direction}.output", f"{angle}.vector2")

    reader = cmds.createNode("remapValue", name=name)
    cmds.connectAttr(f"{angle}.angle", f"{reader}.inputValue")
    cmds.setAttr(f"{reader}.inputMin", 0.0)
    cmds.setAttr(f"{reader}.inputMax", cone_angle)
    cmds.setAttr(f"{reader}.value[0].value_Position", 0.0)
    cmds.setAttr(f"{reader}.value[0].value_FloatValue", 1.0)
    cmds.setAttr(f"{reader}.value[0].value_Interp", 1)  # linear
    cmds.setAttr(f"{reader}.value[1].value_Position", 1.0)
    cmds.setAttr(f"{reader}.value[1].value_FloatValue", 0.0)
    cmds.setAttr(f"{reader}.value[1].value_Interp", 1)
    cmds.addAttr(reader, longName=READER_ATTR, attributeType="message")
    cmds.connectAttr(f"{joint}.message", f"{reader}.{READER_ATTR}")
    return reader


def pose_readers():
    """Every pose reader in the scene."""
    return [n for n in cmds.ls(type="remapValue") or [] if cmds.attributeQuery(READER_ATTR, node=n, exists=True)]


def reader_output(reader):
    """The 0..1 output plug of ``reader``."""
    return f"{reader}.outValue"


def reader_joint(reader):
    """The joint ``reader`` reads, or ``None``."""
    found = cmds.listConnections(f"{reader}.{READER_ATTR}", source=True, destination=False) or []
    return cmds.ls(found[0], long=True)[0] if found else None


def cone_angle(reader):
    """The angle, in degrees, at which ``reader`` reaches 0."""
    return cmds.getAttr(f"{reader}.inputMax")


@undoable
def set_cone_angle(reader, angle):
    cmds.setAttr(f"{reader}.inputMax", angle)


@undoable
def drive_target(node, name, reader):
    """Drive target ``name``'s weight with ``reader``'s output."""
    cmds.connectAttr(reader_output(reader), _weight_plug(node, name), force=True)


@undoable
def undrive_target(node, name):
    """Disconnect whatever drives target ``name``, keeping its current weight."""
    plug = _weight_plug(node, name)
    for source in cmds.listConnections(plug, source=True, destination=False, plugs=True) or []:
        cmds.disconnectAttr(source, plug)


def target_driver(node, name):
    """The node driving target ``name``'s weight, or ``None``."""
    found = cmds.listConnections(_weight_plug(node, name), source=True, destination=False, skipConversionNodes=True) or []
    return found[0] if found else None
