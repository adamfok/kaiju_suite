"""Rig Validator: scene-wide checks that a rig is clean, and fixes for the
safe ones. No Qt.

Each check scans the whole scene and returns what's wrong as items: nodes
(long names), vertices (``|body.vtx[3]``) or namespaces (``:old``). Checks
with a ``fix`` can also repair what they find.
"""

from collections import namedtuple

from maya import cmds
from maya.api import OpenMaya as om
from maya.api import OpenMayaAnim as oma

from kaiju_suite.core.undo import undoable

# How far off counts as off: transform values and a vertex's weight sum.
TOLERANCE = 1e-4

Check = namedtuple("Check", "key label description find fix")
Result = namedtuple("Result", "check items")


def _long(nodes):
    return cmds.ls(nodes, long=True) or []


def _settable(plug):
    return cmds.getAttr(plug, settable=True)


def _referenced(node):
    return cmds.referenceQuery(node, isNodeReferenced=True)


# -- controls ---------------------------------------------------------------


def controls():
    """Every transform with a (non-intermediate) NURBS curve shape, long names."""
    shapes = cmds.ls(type="nurbsCurve", noIntermediate=True, long=True) or []
    parents = [cmds.listRelatives(s, parent=True, fullPath=True)[0] for s in shapes]
    return list(dict.fromkeys(parents))


_DEFAULTS = {"translate": 0.0, "rotate": 0.0, "scale": 1.0}
_AXES = "XYZ"


def _control_transforms():
    found = []
    for control in controls():
        for attr, default in _DEFAULTS.items():
            values = cmds.getAttr(f"{control}.{attr}")[0]
            if any(abs(v - default) > TOLERANCE for v in values):
                found.append(control)
                break
    return found


def _zero_controls(nodes):
    """Set translate, rotate and scale to their defaults where they can be set."""
    for node in nodes:
        for attr, default in _DEFAULTS.items():
            for axis in _AXES:
                plug = f"{node}.{attr}{axis}"
                if _settable(plug):
                    cmds.setAttr(plug, default)


# Animation curves driven by time (keys), not by another attribute (driven keys).
_TIME_CURVES = ("animCurveTL", "animCurveTA", "animCurveTU", "animCurveTT")


def _time_curves(node):
    curves = cmds.listConnections(node, source=True, destination=False, type="animCurve") or []
    return [c for c in dict.fromkeys(curves) if cmds.nodeType(c) in _TIME_CURVES]


def _control_keys():
    return [control for control in controls() if _time_curves(control)]


def _delete_keys(nodes):
    # Deleting the curves leaves each attribute at its current value.
    curves = [c for node in nodes for c in _time_curves(node)]
    if curves:
        cmds.delete(curves)


# -- joints -----------------------------------------------------------------

_ROTATE_PLUGS = ("rotate", "rotateX", "rotateY", "rotateZ")


def _driven_rotation(joint):
    return any(
        cmds.listConnections(f"{joint}.{plug}", source=True, destination=False, skipConversionNodes=True)
        for plug in _ROTATE_PLUGS
    )


def _joint_rotations():
    found = []
    for joint in cmds.ls(type="joint", long=True) or []:
        if _driven_rotation(joint):
            continue
        if any(abs(v) > TOLERANCE for v in cmds.getAttr(f"{joint}.rotate")[0]):
            found.append(joint)
    return found


def _rotations_to_orient(joints):
    """Fold each joint's rotation into its joint orient. The joint's local
    matrix doesn't change, so neither its children nor skinned meshes move."""
    for joint in joints:
        plugs = [f"{joint}.rotate{axis}" for axis in _AXES] + [f"{joint}.jointOrient{axis}" for axis in _AXES]
        if not all(_settable(plug) for plug in plugs):
            continue
        order = cmds.getAttr(f"{joint}.rotateOrder")
        rotate = om.MEulerRotation([om.MAngle(v, om.MAngle.uiUnit()).asRadians() for v in cmds.getAttr(f"{joint}.rotate")[0]], order)
        orient = om.MEulerRotation([om.MAngle(v, om.MAngle.uiUnit()).asRadians() for v in cmds.getAttr(f"{joint}.jointOrient")[0]])
        combined = om.MTransformationMatrix(rotate.asMatrix() * orient.asMatrix()).rotation()
        combined.reorderIt(om.MEulerRotation.kXYZ)
        cmds.setAttr(f"{joint}.rotate", 0, 0, 0)
        cmds.setAttr(
            f"{joint}.jointOrient",
            *[om.MAngle(v).asUnits(om.MAngle.uiUnit()) for v in (combined.x, combined.y, combined.z)],
        )


# -- skin weights -----------------------------------------------------------


def _skin_geometry(skin):
    """The skinCluster's output shapes as (transform long name, MDagPath)."""
    fn = oma.MFnSkinCluster(om.MSelectionList().add(skin).getDependNode(0))
    found = []
    for i in range(fn.numOutputConnections()):
        index = fn.indexForOutputConnection(i)
        path = fn.getPathAtIndex(index)
        if path.apiType() != om.MFn.kMesh:
            continue
        transform = om.MDagPath(path)
        transform.pop()
        found.append((transform.fullPathName(), path))
    return fn, found


def _skin_weights():
    found = []
    for skin in cmds.ls(type="skinCluster") or []:
        fn, geometry = _skin_geometry(skin)
        for transform, path in geometry:
            components = om.MFnSingleIndexedComponent().create(om.MFn.kMeshVertComponent)
            om.MFnSingleIndexedComponent(components).setCompleteData(om.MFnMesh(path).numVertices)
            weights, count = fn.getWeights(path, components)
            for vertex in range(len(weights) // count if count else 0):
                total = sum(weights[vertex * count : (vertex + 1) * count])
                if abs(total - 1.0) > TOLERANCE:
                    found.append(f"{transform}.vtx[{vertex}]")
    return found


def _skin_of(mesh):
    skins = cmds.ls(cmds.listHistory(mesh, pruneDagObjects=True) or [], type="skinCluster")
    return skins[0] if skins else None


def _normalize(vertices):
    """Scale each vertex's weights so they add up to 1. Sets the weights
    directly, so it works whatever the skinCluster's Normalize Weights mode;
    vertices with no weight at all are left alone."""
    for vertex in vertices:
        mesh, component = vertex.split(".", 1)
        skin = _skin_of(mesh)
        if not skin:
            continue
        index = int(component[component.index("[") + 1 : -1])
        plug = f"{skin}.weightList[{index}].weights"
        influences = cmds.getAttr(plug, multiIndices=True) or []
        weights = {i: cmds.getAttr(f"{plug}[{i}]") for i in influences}
        total = sum(weights.values())
        if total <= 0:
            continue
        for i, weight in weights.items():
            cmds.setAttr(f"{plug}[{i}]", weight / total)


# -- names and namespaces ---------------------------------------------------


def _duplicate_names():
    nodes = cmds.ls(dagObjects=True, long=True) or []
    counts = {}
    for node in nodes:
        counts.setdefault(node.rsplit("|", 1)[-1], []).append(node)
    return [node for node in nodes if len(counts[node.rsplit("|", 1)[-1]]) > 1]


_BUILT_IN_NAMESPACES = {":UI", ":shared"}


def _namespaces():
    found = cmds.namespaceInfo(":", listOnlyNamespaces=True, recurse=True, absoluteName=True) or []
    from_references = set()
    for ref in cmds.ls(type="reference") or []:
        try:
            namespace = cmds.referenceQuery(ref, namespace=True)
        except RuntimeError:
            continue  # sharedReferenceNode and references with no file
        from_references.add(namespace)
    stray = []
    for namespace in found:
        if namespace in _BUILT_IN_NAMESPACES:
            continue
        if any(namespace == ns or namespace.startswith(ns + ":") for ns in from_references):
            continue
        stray.append(namespace)
    return sorted(stray)


def _remove_namespaces(namespaces):
    # Deepest first, so each one is empty of namespaces when it's removed.
    for namespace in sorted(namespaces, key=lambda ns: ns.count(":"), reverse=True):
        if cmds.namespace(exists=namespace):
            cmds.namespace(removeNamespace=namespace, mergeNamespaceWithRoot=True)


# -- unknown and unused nodes -----------------------------------------------


def _unknown_nodes():
    nodes = cmds.ls(type=("unknown", "unknownDag", "unknownTransform"), long=True) or []
    return [node for node in nodes if not _referenced(node)]


def _shading_group_used(sg):
    return bool(cmds.sets(sg, query=True))


def _unused_nodes():
    defaults = set(cmds.ls(defaultNodes=True) or [])
    found = []
    for sg in cmds.ls(type="shadingEngine") or []:
        if sg not in defaults and not _shading_group_used(sg):
            found.append(sg)
    for material in cmds.ls(materials=True) or []:
        if material in defaults:
            continue
        sgs = cmds.listConnections(material, source=False, destination=True, type="shadingEngine") or []
        if not any(_shading_group_used(sg) for sg in sgs):
            found.append(material)
    for curve in cmds.ls(type="animCurve") or []:
        if not cmds.listConnections(curve, source=False, destination=True):
            found.append(curve)
    return [node for node in dict.fromkeys(found) if not _referenced(node)]


def _delete(nodes):
    nodes = [node for node in nodes if cmds.objExists(node)]
    if nodes:
        cmds.lockNode(nodes, lock=False)
        cmds.delete(nodes)


CHECKS = (
    Check("control_transforms", "Controls off zero", "Controls (transforms with curve shapes) whose translate, rotate or scale aren't at their defaults. Fix resets them; locked channels are left alone.", _control_transforms, _zero_controls),
    Check("control_keys", "Keys on controls", "Controls with keyframes (driven keys don't count). Fix deletes the keys and keeps the current values.", _control_keys, _delete_keys),
    Check("joint_rotations", "Joint rotations", "Joints with rotate values instead of joint orient (joints driven by the rig don't count). Fix moves the rotation into joint orient without moving anything.", _joint_rotations, _rotations_to_orient),
    Check("skin_weights", "Skin weights", "Skinned vertices whose weights don't add up to 1. Fix normalizes them.", _skin_weights, _normalize),
    Check("duplicate_names", "Duplicate names", "DAG nodes that share a short name with another node; tools and scripts find nodes by name.", _duplicate_names, None),
    Check("namespaces", "Stray namespaces", "Namespaces that don't belong to a reference. Fix removes them, moving their nodes to the root namespace.", _namespaces, _remove_namespaces),
    Check("unknown_nodes", "Unknown nodes", "Nodes from plug-ins that aren't loaded. Fix deletes them.", _unknown_nodes, _delete),
    Check("unused_nodes", "Unused nodes", "Shading groups with no members, materials on no used shading group, and animation curves that drive nothing. Fix deletes them.", _unused_nodes, _delete),
)  # fmt: skip

_BY_KEY = {check.key: check for check in CHECKS}


def run(keys=None):
    """Run the checks named in ``keys`` (default: all) on the scene; returns a
    :data:`Result` for every check that found something, in check order."""
    checks = [_BY_KEY[key] for key in keys] if keys else CHECKS
    results = []
    for check in checks:
        items = check.find()
        if items:
            results.append(Result(check, items))
    return results


def select_targets(key, items):
    """What to select for ``items`` found by check ``key``: the nodes or
    components that still exist; a namespace stands for the nodes in it."""
    if key == "namespaces":
        nodes = []
        for namespace in items:
            if cmds.namespace(exists=namespace):
                nodes += cmds.namespaceInfo(namespace, listOnlyDependencyNodes=True, dagPath=True) or []
        return _long(nodes)
    return [item for item in items if cmds.objExists(item)]


@undoable
def fix(key, items):
    """Repair what check ``key`` found (``items``), as one undo step."""
    check = _BY_KEY[key]
    if not check.fix:
        raise ValueError(f"{check.label} can't be fixed automatically.")
    check.fix(list(items))
