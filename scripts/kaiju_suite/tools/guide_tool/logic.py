"""Guide Tool: place a joint chain with guide locators. No Qt here.

A chain's guides are a start guide, any number of middle guides and an end
guide, plus an up guide off to the side, like a pole vector. They can only
be moved: rotate and scale are locked. They sit under ``<name>_guides_grp``,
which finds them (and the joints built from them) through message
connections, so renaming them is fine.

Building joints puts them on the plane through the start, end and up
guides: middle guides off that plane are projected onto it. Each joint's
aim axis points at the next joint and its up axis lies in the plane, on the
up guide's side, so the third axis is the plane's normal for every joint
and the chain bends around that one axis. The end joint sits on the end
guide and lines up with its parent.

Every function that changes the scene is one undo step and raises
``ValueError``, changing nothing, when its input is wrong.
"""

import re

from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.core import orient
from kaiju_suite.core.selection import short_name
from kaiju_suite.core.undo import undoable

NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# On the guide group: the chain's name, then message links to its nodes.
_TAG = "kaijuGuides"
_CHAIN = "guideChain"  # start, middle and end guides, in order
_UP = "guideUp"
_JOINTS = "guideJoints"  # the joints built from the guides, top first
_CURVES = "guideCurves"  # the display curves: through the chain, start to up
_PREVIEWS = "guidePreviews"  # one transform per joint, placed as the joint will be
_PLANE = "guidePlane"
_NODES = "guideNodes"  # utility nodes of the preview network, deleted with the group
# The previews' aim axis and the axis that lines up with the plane normal.
_AIM = "previewAim"
_THIRD = "previewThird"
# Closer than this counts as the same spot.
_TOLERANCE = 1e-4
_UP_COLOR = 17  # yellow
_DISC_COLOR = 18  # light blue
# Materials (color, transparency) of the discs and the plane: shaded, so they
# show where they cut a mesh, and see-through, so they don't hide the guides.
_DISC_SHADE = ((0.35, 0.75, 1.0), 0.4)  # light blue
_PLANE_SHADE = ((1.0, 0.9, 0.4), 0.75)  # pale yellow, like the up guide
# Turns a disc made around X to ring the aim axis, by the aim axis' index.
_DISC_ROTATE = {0: (0, 0, 0), 1: (0, 0, 90), 2: (0, -90, 0)}


# -- helpers ------------------------------------------------------------------


def _long(node):
    return cmds.ls(node, long=True)[0]


def _by_uuid(uuid):
    return cmds.ls(uuid, long=True)[0]


def _position(node):
    return om.MVector(cmds.xform(node, query=True, worldSpace=True, translation=True))


def _is_group(node):
    return cmds.objExists(node) and cmds.attributeQuery(_TAG, node=node, exists=True)


def _connected(group, attr):
    """The nodes linked to ``group``'s multi message ``attr``, by index."""
    found = []
    for index in cmds.getAttr(f"{group}.{attr}", multiIndices=True) or []:
        source = cmds.listConnections(f"{group}.{attr}[{index}]", source=True, destination=False)
        if source:
            found.append(_long(source[0]))
    return found


def _link(node, group, plug):
    cmds.connectAttr(f"{node}.message", f"{group}.{plug}")


def _plane(points, up):
    """``points`` (start, middles, end) on the plane through start, end and
    ``up``, and that plane's normal (start->end ^ start->up)."""
    points = [om.MVector(p) for p in points]
    start, end, up = points[0], points[-1], om.MVector(up)
    span = end - start
    if span.length() < _TOLERANCE:
        raise ValueError("The start and end guides are on the same spot; move them apart.")
    normal = span ^ (up - start)
    if normal.length() / span.length() < _TOLERANCE:
        raise ValueError("The up guide is in line with the start and end guides; move it to the side.")
    normal.normalize()
    placed = [start] + [p - normal * ((p - start) * normal) for p in points[1:-1]] + [end]
    for i, (a, b) in enumerate(zip(placed, placed[1:]), start=1):
        if (b - a).length() < _TOLERANCE:
            raise ValueError(f"Joints {i} and {i + 1} land on the same spot on the plane; move their guides apart.")
    return placed, normal


def _lock_to_move_only(node):
    for attr in ("rx", "ry", "rz", "sx", "sy", "sz"):
        cmds.setAttr(f"{node}.{attr}", lock=True, keyable=False, channelBox=False)


def _guide(name, group, position, size):
    guide = cmds.spaceLocator(name=name)[0]
    guide = _long(cmds.parent(guide, group)[0])
    cmds.xform(guide, worldSpace=True, translation=(position.x, position.y, position.z))
    shape = cmds.listRelatives(guide, shapes=True, fullPath=True)[0]
    cmds.setAttr(f"{shape}.localScale", size, size, size)
    _lock_to_move_only(guide)
    cmds.setAttr(f"{guide}.displayHandle", True)
    return guide


def _display_curve(name, group, guides):
    """A template curve through ``guides`` that follows them as they move."""
    curve = cmds.curve(degree=1, point=[(0, 0, 0)] * len(guides), name=name)
    curve = _long(cmds.parent(curve, group)[0])
    # Its points come in world space, so it must not move with the group.
    cmds.setAttr(f"{curve}.inheritsTransform", False)
    cmds.setAttr(f"{curve}.template", True)
    shape = cmds.listRelatives(curve, shapes=True, fullPath=True)[0]
    for i, guide in enumerate(guides):
        guide_shape = cmds.listRelatives(guide, shapes=True, fullPath=True)[0]
        cmds.connectAttr(f"{guide_shape}.worldPosition[0]", f"{shape}.controlPoints[{i}]")
    return curve


# -- live preview -------------------------------------------------------------
# A node network does what build_joints does, live: it projects the middle
# guides onto the plane and orients a preview transform per joint (aim at
# the next joint, third axis along the plane normal) with aimMatrix nodes.


def _util(group, node_type, name):
    """A utility node of the preview network, linked to ``group`` so it's
    deleted with it."""
    return _track(group, cmds.createNode(node_type, name=name))


def _track(group, node):
    """Link ``node`` to ``group`` so it's deleted with it."""
    index = len(cmds.getAttr(f"{group}.{_NODES}", multiIndices=True) or [])
    _link(node, group, f"{_NODES}[{index}]")
    return node


def _difference(group, name, a, b):
    """The plug of ``a - b``, both vector plugs."""
    node = _util(group, "plusMinusAverage", name)
    cmds.setAttr(f"{node}.operation", 2)
    cmds.connectAttr(a, f"{node}.input3D[0]")
    cmds.connectAttr(b, f"{node}.input3D[1]")
    return f"{node}.output3D"


def _world_position(guide):
    shape = cmds.listRelatives(guide, shapes=True, fullPath=True)[0]
    return f"{shape}.worldPosition[0]"


def _aligned(group, name, position, primary_axis, primary, secondary_axis, secondary):
    """A matrix plug at ``position`` whose ``primary_axis`` points along the
    ``primary`` vector and whose ``secondary_axis`` is as close as it can be
    to ``secondary``. Axes are plugs or tuples."""
    compose = _util(group, "composeMatrix", f"{name}_compose")
    cmds.connectAttr(position, f"{compose}.inputTranslate")
    aim = _util(group, "aimMatrix", f"{name}_aim")
    cmds.connectAttr(f"{compose}.outputMatrix", f"{aim}.inputMatrix")
    for prefix, axis, target in (("primary", primary_axis, primary), ("secondary", secondary_axis, secondary)):
        cmds.setAttr(f"{aim}.{prefix}Mode", 2)  # align
        if isinstance(axis, str):
            cmds.connectAttr(axis, f"{aim}.{prefix}InputAxis")
        else:
            cmds.setAttr(f"{aim}.{prefix}InputAxis", *axis)
        cmds.connectAttr(target, f"{aim}.{prefix}TargetVector")
    return f"{aim}.outputMatrix"


def _visual(node, color=None, shaded=False):
    """Draw ``node`` unselectable, as wireframe unless ``shaded``."""
    cmds.setAttr(f"{node}.overrideEnabled", True)
    cmds.setAttr(f"{node}.overrideDisplayType", 2)  # reference
    cmds.setAttr(f"{node}.overrideShading", shaded)
    if color is not None:
        cmds.setAttr(f"{node}.overrideColor", color)


def _placed(group, node, matrix):
    """Put ``node`` under ``group``, placed in world space by ``matrix``."""
    node = _long(cmds.parent(node, group, relative=True)[0])
    cmds.setAttr(f"{node}.inheritsTransform", False)
    cmds.connectAttr(matrix, f"{node}.offsetParentMatrix")
    return node


def _material(group, name, shade):
    """A shading group with a lambert of ``shade`` (color, transparency)."""
    color, transparency = shade
    material = _util(group, "lambert", f"{name}_mat")
    cmds.setAttr(f"{material}.color", *color)
    cmds.setAttr(f"{material}.transparency", transparency, transparency, transparency)
    engine = _track(group, cmds.sets(renderable=True, noSurfaceShader=True, empty=True, name=f"{name}_sg"))
    cmds.connectAttr(f"{material}.outColor", f"{engine}.surfaceShader")
    return engine


def _disc(name, parent, radius, engine):
    circle = cmds.circle(normal=(1, 0, 0), radius=radius, constructionHistory=False)[0]
    disc = cmds.planarSrf(circle, constructionHistory=False)[0]
    cmds.delete(circle)
    # Relative: the parent is already in place, and the disc must not keep its world position.
    disc = cmds.rename(cmds.parent(disc, parent, relative=True)[0], name)
    disc = _long(f"{parent}|{disc}")
    _visual(disc, _DISC_COLOR, shaded=True)
    cmds.sets(cmds.listRelatives(disc, shapes=True, fullPath=True), edit=True, forceElement=engine)
    return disc


def _preview_network(group, name, chain, up, size):
    start, end = _world_position(chain[0]), _world_position(chain[-1])
    span = _difference(group, f"{name}_span", end, start)
    cross = _util(group, "vectorProduct", f"{name}_normal")
    cmds.setAttr(f"{cross}.operation", 2)  # cross product
    cmds.setAttr(f"{cross}.normalizeOutput", True)
    cmds.connectAttr(span, f"{cross}.input1")
    cmds.connectAttr(_difference(group, f"{name}_to_up", _world_position(up), start), f"{cross}.input2")
    normal = f"{cross}.output"

    engine = _material(group, f"{name}_disc", _DISC_SHADE)
    points = [start]
    for i, guide in enumerate(chain[1:-1], start=2):
        position = _world_position(guide)
        dot = _util(group, "vectorProduct", f"{name}_{i:02d}_height")
        cmds.setAttr(f"{dot}.operation", 1)  # dot product
        cmds.connectAttr(_difference(group, f"{name}_{i:02d}_from_start", position, start), f"{dot}.input1")
        cmds.connectAttr(normal, f"{dot}.input2")
        offset = _util(group, "multiplyDivide", f"{name}_{i:02d}_offset")
        cmds.connectAttr(normal, f"{offset}.input1")
        for letter in "XYZ":
            cmds.connectAttr(f"{dot}.outputX", f"{offset}.input2{letter}")
        points.append(_difference(group, f"{name}_{i:02d}_planar", position, f"{offset}.output"))
    points.append(end)

    segments = [
        _difference(group, f"{name}_{i + 1:02d}_segment", b, a) for i, (a, b) in enumerate(zip(points, points[1:]))
    ]
    for i, point in enumerate(points):
        label = f"{name}_{i + 1:02d}"
        # The end joint lines up with its parent: it aims along the last segment.
        matrix = _aligned(
            group, label, point, f"{group}.{_AIM}", segments[min(i, len(segments) - 1)], f"{group}.{_THIRD}", normal
        )
        preview = _placed(group, cmds.createNode("transform", name=f"{label}_preview"), matrix)
        cmds.setAttr(f"{preview}.displayLocalAxis", True)
        _disc(f"{label}_disc", preview, size * 2, engine)
        _link(preview, group, f"{_PREVIEWS}[{i}]")

    center = _util(group, "plusMinusAverage", f"{name}_center")
    cmds.setAttr(f"{center}.operation", 3)  # average
    cmds.connectAttr(start, f"{center}.input3D[0]")
    cmds.connectAttr(end, f"{center}.input3D[1]")
    matrix = _aligned(group, f"{name}_plane", f"{center}.output3D", (1, 0, 0), span, (0, 0, 1), normal)
    surface = cmds.nurbsPlane(
        name=f"{name}_plane", axis=(0, 0, 1), width=1, lengthRatio=1, patchesU=4, patchesV=2, constructionHistory=False
    )[0]
    surface = _placed(group, surface, matrix)
    length = _util(group, "distanceBetween", f"{name}_length")
    cmds.connectAttr(start, f"{length}.point1")
    cmds.connectAttr(end, f"{length}.point2")
    scale = _util(group, "multiplyDivide", f"{name}_plane_size")
    cmds.setAttr(f"{scale}.input2", 1.2, 0.6, 1)
    for letter in "XY":
        cmds.connectAttr(f"{length}.distance", f"{scale}.input1{letter}")
        cmds.connectAttr(f"{scale}.output{letter}", f"{surface}.scale{letter}")
    _visual(surface, shaded=True)
    cmds.sets(
        cmds.listRelatives(surface, shapes=True, fullPath=True),
        edit=True,
        forceElement=_material(group, f"{name}_plane", _PLANE_SHADE),
    )
    _link(surface, group, _PLANE)


def _apply_axes(group, aim, up):
    """Point the previews' ``aim`` axis down the chain and their ``up`` axis
    to the up guide's side, as build_joints does (``(index, sign)`` pairs)."""
    direction, normal = om.MVector(1, 0, 0), om.MVector(0, 0, 1)
    matrix = orient.aim_matrix(direction, aim, up, normal ^ direction)
    third = 3 - aim[0] - up[0]
    aim_vector, third_vector = [0, 0, 0], [0, 0, 0]
    aim_vector[aim[0]] = aim[1]
    third_vector[third] = 1 if orient.row(matrix, third) * normal > 0 else -1
    cmds.setAttr(f"{group}.{_AIM}", *aim_vector)
    cmds.setAttr(f"{group}.{_THIRD}", *third_vector)
    for preview in _connected(group, _PREVIEWS):
        for disc in cmds.listRelatives(preview, children=True, type="transform", fullPath=True) or []:
            cmds.setAttr(f"{disc}.rotate", *_DISC_ROTATE[aim[0]])


def _axes(aim, up):
    aim_axis, up_axis = orient.axis(aim), orient.axis(up)
    if aim_axis[0] == up_axis[0]:
        raise ValueError("The aim axis and the up axis must be different axes.")
    return aim_axis, up_axis


# -- finding guides -----------------------------------------------------------


def guide_group(node):
    """The guide group ``node`` belongs to: ``node`` itself, the group above
    a guide, or the group a built joint is linked to."""
    found = cmds.ls(node, long=True) if node else []
    if not found:
        raise ValueError(f"{node!r} isn't in the scene.")
    path = found[0]
    linked = cmds.listConnections(f"{path}.message", source=False, destination=True) or []
    parents = cmds.listRelatives(path, allParents=True, fullPath=True) or []
    for candidate in [path] + cmds.ls(linked, long=True) + parents:
        if _is_group(candidate):
            return _long(candidate)
    raise ValueError(f"{short_name(path)} isn't a guide, a guide group or a joint built from guides.")


def find_group(nodes):
    """The one guide group ``nodes`` (e.g. the selection) belong to, or,
    with no ``nodes``, the only guide group in the scene."""
    if not nodes:
        groups = [n for n in cmds.ls(type="transform", long=True) if _is_group(n)]
        if not groups:
            raise ValueError("No guides in the scene. Create guides first.")
        if len(groups) > 1:
            raise ValueError("There are several guide groups. Select a guide, its group or a joint built from it.")
        return groups[0]
    groups = list(dict.fromkeys(guide_group(node) for node in nodes))
    if len(groups) > 1:
        raise ValueError(f"Select guides of one chain, not {', '.join(short_name(g) for g in groups)}.")
    return groups[0]


def guides(group):
    """``{"chain": [start, middles..., end], "up": up}``, as long names."""
    group = guide_group(group)
    chain, up = _connected(group, _CHAIN), cmds.listConnections(f"{group}.{_UP}", source=True, destination=False)
    if len(chain) < 2 or not up:
        raise ValueError(f"Guides of {short_name(group)} are missing; delete it and create the guides again.")
    return {"chain": chain, "up": _long(up[0])}


def joints(group):
    """The joints built from ``group``'s guides, top first."""
    return _connected(guide_group(group), _JOINTS)


def display_curves(group):
    """``(curve through the chain, curve from start to up)``."""
    return tuple(_connected(guide_group(group), _CURVES))


def previews(group):
    """The preview transforms, one per joint, top first. Each sits and
    turns as its joint will, shows its local axis and holds a disc."""
    return _connected(guide_group(group), _PREVIEWS)


def plane(group):
    """The surface showing the plane the chain is built on."""
    group = guide_group(group)
    return _long(cmds.listConnections(f"{group}.{_PLANE}", source=True, destination=False)[0])


def planar_positions(points, up):
    """``points`` (start, middle points, end) with each middle point moved
    straight onto the plane through the start, the end and ``up``. Raises
    ``ValueError`` if ``up`` is in line with start and end, or if two
    neighbouring points land on the same spot."""
    return _plane(points, up)[0]


# -- editing ------------------------------------------------------------------


@undoable
def create_guides(name, count, start=(0, 0, 0), end=(10, 0, 0), aim="x", up="y"):
    """Make guides for a chain named ``name``: start and end guides at
    ``start`` and ``end``, ``count`` middle guides evenly between them, and
    an up guide off to the side, with a live preview of the joints (oriented
    by ``aim`` and ``up``, see :func:`build_joints`) and of their plane.
    Returns the guide group."""
    if not isinstance(name, str) or not NAME.match(name):
        raise ValueError(
            f"Name {name!r} can't be used in node names: use letters, digits and _, not starting with a digit."
        )
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("The number of middle guides must be 0 or more.")
    start, end = om.MVector(start), om.MVector(end)
    span = end - start
    if span.length() < _TOLERANCE:
        raise ValueError("The start and end guides can't be on the same spot.")
    axes = _axes(aim, up)

    chain_names = (
        [f"{name}_start_guide"] + [f"{name}_mid_{i:02d}_guide" for i in range(1, count + 1)] + [f"{name}_end_guide"]
    )
    names = [f"{name}_guides_grp", f"{name}_up_guide", f"{name}_guide_crv", f"{name}_up_crv", f"{name}_plane"]
    names += chain_names + [f"{name}_{i:02d}_{kind}" for i in range(1, count + 3) for kind in ("preview", "disc")]
    taken = [n for n in names if cmds.objExists(n)]
    if taken:
        raise ValueError(f"These names are already used, rename or delete them first: {', '.join(taken)}")

    group = _long(cmds.createNode("transform", name=f"{name}_guides_grp"))
    cmds.addAttr(group, longName=_TAG, dataType="string")
    cmds.setAttr(f"{group}.{_TAG}", name, type="string")
    for attr in (_CHAIN, _JOINTS, _CURVES, _PREVIEWS, _NODES):
        cmds.addAttr(group, longName=attr, attributeType="message", multi=True)
    for attr in (_UP, _PLANE):
        cmds.addAttr(group, longName=attr, attributeType="message")
    for attr in (_AIM, _THIRD):
        cmds.addAttr(group, longName=attr, attributeType="double3")
        for letter in "XYZ":
            cmds.addAttr(group, longName=f"{attr}{letter}", attributeType="double", parent=attr)

    size = span.length() * 0.05
    chain = []
    for i, guide_name in enumerate(chain_names):
        guide = _guide(guide_name, group, start + span * (i / (count + 1)), size)
        _link(guide, group, f"{_CHAIN}[{i}]")
        chain.append(guide)

    side = orient.row(orient.aim_matrix(span, (0, 1), (1, 1), om.MVector(0, 1, 0)), 1)
    up = _guide(f"{name}_up_guide", group, start + span * 0.5 + side * (span.length() * 0.5), size)
    cmds.setAttr(f"{up}.overrideEnabled", True)
    cmds.setAttr(f"{up}.overrideColor", _UP_COLOR)
    _link(up, group, _UP)

    _link(_display_curve(f"{name}_guide_crv", group, chain), group, f"{_CURVES}[0]")
    _link(_display_curve(f"{name}_up_crv", group, [chain[0], up]), group, f"{_CURVES}[1]")
    _preview_network(group, name, chain, up, size)
    _apply_axes(group, *axes)
    cmds.select(clear=True)
    return group


@undoable
def build_joints(group, aim="x", up="y"):
    """Build a planar joint chain from ``group``'s guides, or, if one was
    built already, move and re-orient those joints (keeping their names
    and what's attached to them). ``aim`` points at the next joint and
    ``up`` towards the up guide's side, both ``"x"``, ``"-y"``...
    Returns the joints, top first."""
    group = guide_group(group)
    aim_axis, up_axis = _axes(aim, up)
    found = guides(group)
    positions, normal = _plane([_position(g) for g in found["chain"]], _position(found["up"]))

    existing = joints(group)
    if existing and len(existing) != len(positions):
        raise ValueError(
            f"The chain built from these guides has {len(existing)} joints but the guides make {len(positions)}. "
            "Delete the joints to build a new chain."
        )
    if existing:
        uuids = cmds.ls(existing, uuid=True)
    else:
        name = cmds.getAttr(f"{group}.{_TAG}")
        names = [f"{name}_{i:02d}_jnt" for i in range(1, len(positions) + 1)]
        taken = [n for n in names if cmds.objExists(n)]
        if taken:
            raise ValueError(f"These names are already used, rename or delete them first: {', '.join(taken)}")
        uuids, parent = [], None
        for i, joint_name in enumerate(names):
            joint = cmds.createNode("joint", name=joint_name, **({"parent": parent} if parent else {}))
            joint = _long(joint)
            if parent:
                cmds.connectAttr(f"{parent}.scale", f"{joint}.inverseScale", force=True)
            _link(joint, group, f"{_JOINTS}[{i}]")
            uuids.append(cmds.ls(joint, uuid=True)[0])
            parent = joint

    _apply_axes(group, aim_axis, up_axis)
    last = len(uuids) - 1
    for i, uuid in enumerate(uuids):
        joint = _by_uuid(uuid)
        position = positions[i]
        cmds.xform(joint, worldSpace=True, translation=(position.x, position.y, position.z))
        if i < last:
            direction = positions[i + 1] - position
            world = orient.aim_matrix(direction, aim_axis, up_axis, normal ^ direction)
            orient.set_world_rotation(joint, world)
        else:
            for attr in ("rotate", "rotateAxis", "jointOrient"):
                cmds.setAttr(f"{joint}.{attr}", 0, 0, 0)
    return [_by_uuid(uuid) for uuid in uuids]


@undoable
def set_axes(group, aim="x", up="y"):
    """Turn ``group``'s previews to show joints built with ``aim`` and
    ``up`` (see :func:`build_joints`)."""
    _apply_axes(guide_group(group), *_axes(aim, up))


@undoable
def delete_guides(group):
    """Delete ``group``, its guides and their preview. Joints built from
    them stay."""
    group = guide_group(group)
    cmds.delete(_connected(group, _NODES) + [group])
