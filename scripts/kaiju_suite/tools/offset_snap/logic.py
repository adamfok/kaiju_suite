"""Offset & Snap Tool logic. No Qt here, so it can be scripted and tested headless.

- :func:`add_offset_groups` puts zero / offset groups above nodes.
- :func:`match_transforms` snaps nodes to a target (position, rotation,
  scale, pivot).
- :func:`centroid` / :func:`place_at_centroid` put a locator or joint at
  the middle of components or objects.
- :func:`zero_out` resets controls' keyable translate / rotate / scale.
"""

from collections import namedtuple

from maya import cmds

from kaiju_suite.core import naming
from kaiju_suite.core.log import get_logger
from kaiju_suite.core.nodes import unique_name
from kaiju_suite.core.selection import short_name
from kaiju_suite.core.undo import undoable

log = get_logger(__name__)

#: What :func:`zero_out` changed (long names) and skipped (``"node.attr (why)"``).
Result = namedtuple("Result", "changed skipped")

KINDS = ("locator", "joint")

_TRANSFORM_ATTRS = [f"{a}{x}" for a in ("translate", "rotate", "scale") for x in "XYZ"]
# Channels set to their defaults on a node put under a new offset group.
_LOCAL_DEFAULTS = (
    [(f"translate{x}", 0.0) for x in "XYZ"]
    + [(f"rotate{x}", 0.0) for x in "XYZ"]
    + [(f"scale{x}", 1.0) for x in "XYZ"]
    + [(f"shear{a}", 0.0) for a in ("XY", "XZ", "YZ")]
)
_JOINT_DEFAULTS = [(f"jointOrient{x}", 0.0) for x in "XYZ"]


def _path(uuid):
    return cmds.ls(uuid, long=True)[0]


def _uuids(nodes):
    """UUIDs of ``nodes`` in order, each once."""
    found = []
    for node in nodes:
        for uuid in cmds.ls(node, uuid=True) or []:
            if uuid not in found:
                found.append(uuid)
    return found


def _parent(node):
    parents = cmds.listRelatives(node, parent=True, fullPath=True)
    return parents[0] if parents else None


def _connected(plug):
    """Whether ``plug`` is driven by something other than keys."""
    sources = cmds.listConnections(plug, source=True, destination=False, skipConversionNodes=True) or []
    return any(not cmds.nodeType(source).startswith("animCurveT") for source in sources)


# -- offset groups ----------------------------------------------------------------


def group_name(pattern, node, level):
    """The name of the offset group ``pattern`` makes above ``node``.

    ``{name}`` becomes the node's short name (without namespace), and a run
    of ``#`` becomes ``level`` zero-padded (see :func:`naming.expand_pattern`):
    ``group_name("{name}_grp##", "|rig|arm_ctrl", 2)`` -> ``"arm_ctrl_grp02"``.
    """
    name = pattern.replace("{name}", short_name(node).rsplit(":", 1)[-1])
    return naming.expand_pattern(name, level) if "#" in name else name


def _zero_local(node):
    """Set ``node``'s local transform to identity, unlocking (and relocking)
    locked channels; connected ones are left alone."""
    defaults = list(_LOCAL_DEFAULTS)
    compounds = ["translate", "rotate", "scale", "shear"]
    if cmds.nodeType(node) == "joint":
        defaults += _JOINT_DEFAULTS
        compounds.append("jointOrient")
    # A locked compound (e.g. ``scale``) locks its children without them
    # reporting it, so unlock the compounds and the children both.
    plugs = [f"{node}.{attr}" for attr in compounds] + [f"{node}.{attr}" for attr, _ in defaults]
    locked = [plug for plug in plugs if cmds.getAttr(plug, lock=True)]
    for plug in locked:
        cmds.setAttr(plug, lock=False)
    for attr, value in defaults:
        plug = f"{node}.{attr}"
        if _connected(plug):
            log.warning("%s is connected; left as it is", plug)
        else:
            cmds.setAttr(plug, value)
    for plug in locked:
        cmds.setAttr(plug, lock=True)


@undoable
def add_offset_groups(nodes, patterns):
    """Put a group above each of ``nodes`` for each name pattern in
    ``patterns`` (outermost first), e.g. ``["{name}_zero", "{name}_offset"]``.

    Each group takes the node's world transform, so the node keeps its place
    in the world and ends up with zero translate / rotate (and joint orient)
    and a scale of 1. Returns, per node, its new groups' long names,
    outermost first.
    """
    patterns = [p.strip() for p in patterns if p and p.strip()]
    if not patterns:
        raise ValueError("Give at least one group name pattern, e.g. {name}_zero.")

    made = []
    # Track by UUID: reparenting a node changes the long names of everything
    # below it, including other selected nodes.
    for uuid in _uuids(nodes):
        node = _path(uuid)
        world = cmds.xform(node, query=True, worldSpace=True, matrix=True)
        parent = _parent(node)
        groups = []
        for level, pattern in enumerate(patterns, 1):
            name = unique_name(group_name(pattern, node, level))
            kwargs = {"name": name, "skipSelect": True}
            if parent:
                kwargs["parent"] = parent
            group = cmds.ls(cmds.createNode("transform", **kwargs), uuid=True)[0]
            cmds.xform(_path(group), worldSpace=True, matrix=world)
            groups.append(group)
            parent = _path(group)
        cmds.parent(_path(uuid), parent, relative=True)
        _zero_local(_path(uuid))
        made.append(groups)
    return [[_path(group) for group in groups] for groups in made]


# -- matching ---------------------------------------------------------------------


@undoable
def match_transforms(nodes, target, translate=True, rotate=True, scale=False, pivot=False):
    """Snap each of ``nodes`` to ``target`` in world space: its position,
    rotation and, optionally, scale; ``pivot`` moves the nodes' pivots onto
    the target's without moving the nodes. ``target`` itself is skipped.

    Returns the long names of the nodes matched.
    """
    target_uuid = cmds.ls(target, uuid=True)[0]
    uuids = [uuid for uuid in _uuids(nodes) if uuid != target_uuid]
    if translate or rotate or scale:
        for uuid in uuids:
            cmds.matchTransform(_path(uuid), _path(target_uuid), position=translate, rotation=rotate, scale=scale)
    if pivot:
        position = cmds.xform(_path(target_uuid), query=True, worldSpace=True, rotatePivot=True)
        for uuid in uuids:
            cmds.xform(_path(uuid), worldSpace=True, pivots=position)
    return [_path(uuid) for uuid in uuids]


# -- centroid ---------------------------------------------------------------------


def _is_component(item):
    return "." in item and "[" in item


def centroid(items):
    """The world-space middle of ``items``: components (vertices, edges,
    faces, CVs, ...) count once per vertex or point, objects by their rotate
    pivot."""
    components = [item for item in items if _is_component(item)]
    objects = [item for item in items if not _is_component(item)]

    points = []
    for component in components:
        points += cmds.polyListComponentConversion(component, toVertex=True) or [component]
    points = list(dict.fromkeys(cmds.ls(points, flatten=True) or []))

    positions = [cmds.pointPosition(point, world=True) for point in points]
    positions += [
        cmds.xform(node, query=True, worldSpace=True, rotatePivot=True) for node in cmds.ls(objects, long=True) or []
    ]
    if not positions:
        raise ValueError("Select components or objects to find the middle of.")
    return [sum(p[i] for p in positions) / len(positions) for i in range(3)]


@undoable
def place_at_centroid(items, kind="locator", name=None):
    """Make a locator or joint (``kind``) in the world at the middle of
    ``items`` (see :func:`centroid`). Returns its long name."""
    if kind not in KINDS:
        raise ValueError(f"Can't place a {kind}; pick one of {', '.join(KINDS)}.")
    position = centroid(items)
    name = unique_name(name or ("centroid_loc" if kind == "locator" else "centroid_jnt"))
    if kind == "locator":
        node = cmds.spaceLocator(name=name)[0]
        cmds.xform(node, worldSpace=True, translation=position)
    else:
        cmds.select(clear=True)  # or the joint goes under the selection
        node = cmds.joint(name=name, position=position)
    return cmds.ls(node, long=True)[0]


# -- zero out ---------------------------------------------------------------------


@undoable
def zero_out(nodes):
    """Set the keyable translate / rotate / scale channels of ``nodes`` to
    their defaults, skipping locked ones and ones driven by a connection
    (keyed ones are set). Returns a :data:`Result`."""
    changed, skipped = [], []
    for node in dict.fromkeys(cmds.ls(nodes, long=True, transforms=True) or []):
        keyable = set(cmds.listAttr(node, keyable=True) or [])
        for attr in _TRANSFORM_ATTRS:
            if attr not in keyable:
                continue
            plug = f"{node}.{attr}"
            if cmds.getAttr(plug, lock=True):
                skipped.append(f"{short_name(node)}.{attr} (locked)")
            elif _connected(plug):
                skipped.append(f"{short_name(node)}.{attr} (connected)")
            else:
                cmds.setAttr(plug, cmds.attributeQuery(attr, node=node, listDefault=True)[0])
        changed.append(node)
    return Result(changed, skipped)
