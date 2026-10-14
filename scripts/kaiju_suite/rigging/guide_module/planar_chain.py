"""Planar chains: place a joint chain with guide locators. No Qt here.

Shared by the Guide Module Editor, which wraps the functions that change the scene
in one undo step each, and the guide modules
(:mod:`kaiju_suite.rigging.guide_module`): the Chain guide module is one planar
chain, and other guide modules are built from several.

A chain's guides are a start guide, any number of middle guides and an end
guide, plus an up guide off to the side, like a pole vector. They can only
be moved: rotate and scale are locked. They sit under ``<name>_guides_grp``,
which finds them (and their joints) through message connections, so
renaming them is fine.

Building guides also builds a joint chain that follows them live: a node
network puts the joints on the plane through the start, end and up guides
(middle guides off that plane are projected onto it). Each joint's aim axis
points at the next joint and its up axis lies in the plane, on the up
guide's side, so the third axis is the plane's normal for every joint and
the chain bends around that one axis. The end joint sits on the end guide
and lines up with its parent. Deleting the guides extracts the joints: they
stay where they are, with plain translate and joint orient values.

A chain can also hang under a joint of another chain (a foot under a leg's
ankle): it shares that joint's guide as its start guide, and its joints,
from the second on, are parented under that joint. Its guide group sits
under the other chain's group, and extracting the other chain extracts it
first.

Every function that changes the scene raises ``ValueError``, changing
nothing, when its input is wrong. None of them opens an undo chunk: the
caller makes one user action one undo step.
"""

import re

from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.core import orient
from kaiju_suite.core.selection import short_name

NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# On the guide group: the chain's name, then message links to its nodes.
_TAG = "kaijuGuides"
_CHAIN = "guideChain"  # start, middle and end guides, in order
_UP = "guideUp"
_JOINTS = "guideJoints"  # the joints built from the guides, top first
_CURVES = "guideCurves"  # the display curves: through the chain, start to up
_PREVIEWS = "guidePreviews"  # one transform per joint, placed as the joint will be
_PLANE = "guidePlane"
_PARENT = "guideParent"  # the joint of another chain an attached chain hangs under
_NODES = "guideNodes"  # utility nodes of the preview network, deleted with the group
# The previews' aim axis and the axis that lines up with the plane normal.
_AIM = "previewAim"
_THIRD = "previewThird"
# The aim and up axes as chosen ("x", "-y"...), kept for rebuilding the guides.
_AXES_TEXT = "previewAxes"
# A joint's channels, locked while the guides drive it.
_MOVES = ("tx", "ty", "tz", "rx", "ry", "rz")
# Left on the top joint when the guides are deleted, to build them again:
# the chain's name, its axes ("x y") and where the up guide was.
_NOTE_NAME = "kaijuGuideName"
_NOTE_AXES = "kaijuGuideAxes"
_NOTE_UP = "kaijuGuideUp"
# Closer than this counts as the same spot.
_TOLERANCE = 1e-4
_UP_COLOR = 17  # yellow
_DISC_COLOR = 18  # light blue
# The material (color, transparency) the discs and the plane share: shaded, so
# they show where they cut a mesh, and see-through, so they don't hide the guides.
_SHADE = ((0.35, 0.75, 1.0), 0.4)  # light blue
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


def guide_locator(name, group, position, size):
    """A move-only locator named ``name`` under ``group`` at ``position`` (an
    MVector), drawn ``size`` big: a guide."""
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

    engine = _material(group, f"{name}_preview", _SHADE)
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
        forceElement=engine,
    )
    _link(surface, group, _PLANE)


def _apply_axes(group, aim, up):
    """Point the previews' ``aim`` axis down the chain and their ``up`` axis
    to the up guide's side; the joints follow them (``(index, sign)`` pairs)."""
    direction, normal = om.MVector(1, 0, 0), om.MVector(0, 0, 1)
    matrix = orient.aim_matrix(direction, aim, up, normal ^ direction)
    third = 3 - aim[0] - up[0]
    aim_vector, third_vector = [0, 0, 0], [0, 0, 0]
    aim_vector[aim[0]] = aim[1]
    third_vector[third] = 1 if orient.row(matrix, third) * normal > 0 else -1
    cmds.setAttr(f"{group}.{_AIM}", *aim_vector)
    cmds.setAttr(f"{group}.{_THIRD}", *third_vector)
    text = " ".join(("-" if sign < 0 else "") + "xyz"[index] for index, sign in (aim, up))
    cmds.setAttr(f"{group}.{_AXES_TEXT}", text, type="string")
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
    # Parents first: a start guide shared with an attached chain is linked to both groups.
    for candidate in [path] + parents + cmds.ls(linked, long=True):
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


def parent_joint(group):
    """The joint of another chain ``group``'s chain hangs under, or ``None``."""
    group = guide_group(group)
    if not cmds.attributeQuery(_PARENT, node=group, exists=True):
        return None
    found = cmds.listConnections(f"{group}.{_PARENT}", source=True, destination=False)
    return _long(found[0]) if found else None


def attached(joint):
    """The guide groups of the chains hanging under ``joint``."""
    plugs = cmds.listConnections(f"{joint}.message", source=False, destination=True, plugs=True) or []
    return [_long(p.split(".")[0]) for p in plugs if p.split(".", 1)[1] == _PARENT]


def _guided(joint):
    """``(guide group, index)`` of ``joint`` in the chain whose guides drive
    it. Raises ``ValueError`` if no guides drive it."""
    found = cmds.ls(joint, long=True, type="joint") if joint else []
    linked = cmds.listConnections(f"{found[0]}.message", source=False, destination=True) or [] if found else []
    for group in cmds.ls(linked, long=True):
        if _is_group(group) and found[0] in joints(group):
            return group, joints(group).index(found[0])
    raise ValueError(f"{short_name(found[0]) if found else repr(joint)} isn't a joint built from guides.")


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


def _chain_names(name, count, attached=False):
    """The guides' names; an attached chain has no start guide of its own."""
    middles = [f"{name}_mid_{i:02d}_guide" for i in range(1, count + 1)]
    return ([] if attached else [f"{name}_start_guide"]) + middles + [f"{name}_end_guide"]


def _joint_names(name, count, attached=False):
    """The joints' names; an attached chain has no joint on its start guide."""
    return [f"{name}_{i:02d}_jnt" for i in range(1, count + (2 if attached else 3))]


def _names(name, count, attached=False):
    """Every name building ``count`` middle guides for ``name`` uses."""
    names = [f"{name}_guides_grp", f"{name}_up_guide", f"{name}_guide_crv", f"{name}_up_crv", f"{name}_plane"]
    names += _chain_names(name, count, attached) + _joint_names(name, count, attached)
    return names + [f"{name}_{i:02d}_{kind}" for i in range(1, count + 3) for kind in ("preview", "disc")]


def _create_guides(name, count, start, end, axes, start_guide=None):
    """Make the guide group, guides and preview for a chain named ``name``:
    start and end guides at ``start`` and ``end``, ``count`` middle guides
    evenly between them, and an up guide off to the side. ``start_guide``,
    another chain's guide, is shared instead of making a start guide."""
    start, end = om.MVector(start), om.MVector(end)
    span = end - start
    chain_names = _chain_names(name, count, attached=start_guide is not None)

    group = _long(cmds.createNode("transform", name=f"{name}_guides_grp"))
    cmds.addAttr(group, longName=_TAG, dataType="string")
    cmds.setAttr(f"{group}.{_TAG}", name, type="string")
    for attr in (_CHAIN, _JOINTS, _CURVES, _PREVIEWS, _NODES):
        cmds.addAttr(group, longName=attr, attributeType="message", multi=True)
    for attr in (_UP, _PLANE, _PARENT):
        cmds.addAttr(group, longName=attr, attributeType="message")
    cmds.addAttr(group, longName=_AXES_TEXT, dataType="string")
    for attr in (_AIM, _THIRD):
        cmds.addAttr(group, longName=attr, attributeType="double3")
        for letter in "XYZ":
            cmds.addAttr(group, longName=f"{attr}{letter}", attributeType="double", parent=attr)

    size = span.length() * 0.05
    chain = []
    if start_guide is not None:
        _link(start_guide, group, f"{_CHAIN}[0]")
        chain.append(start_guide)
    for i, guide_name in enumerate(chain_names, start=len(chain)):
        guide = guide_locator(guide_name, group, start + span * (i / (count + 1)), size)
        _link(guide, group, f"{_CHAIN}[{i}]")
        chain.append(guide)

    side = orient.row(orient.aim_matrix(span, (0, 1), (1, 1), om.MVector(0, 1, 0)), 1)
    up = guide_locator(f"{name}_up_guide", group, start + span * 0.5 + side * (span.length() * 0.5), size)
    cmds.setAttr(f"{up}.overrideEnabled", True)
    cmds.setAttr(f"{up}.overrideColor", _UP_COLOR)
    _link(up, group, _UP)

    _link(_display_curve(f"{name}_guide_crv", group, chain), group, f"{_CURVES}[0]")
    _link(_display_curve(f"{name}_up_crv", group, [chain[0], up]), group, f"{_CURVES}[1]")
    _preview_network(group, name, chain, up, size)
    _apply_axes(group, *axes)
    cmds.select(clear=True)
    return group


def _live_joints(group, name, uuids=None):
    """Make the chain's joints follow the previews (``uuids`` are joints to
    reuse, top first; new ones are made if not given). Each joint's offset
    parent matrix is its preview's world matrix in the space of the preview
    above it, which is where its parent joint is (the top joint takes its
    preview's world matrix, so it must stay at the world root). Reading the
    joints' own parentInverseMatrix instead goes stale. Translate and rotate
    stay zero, locked. An attached chain makes no joint on its first preview:
    its top joint hangs under the parent joint, in the space of the preview
    that drives that joint."""
    shown, parent = previews(group), parent_joint(group)
    if parent:
        parent_group, index = _guided(parent)
        driven, spaces = shown[1:], [previews(parent_group)[index]] + shown[1:-1]
    else:
        driven, spaces = shown, [None] + shown[:-1]
    if uuids is None:
        uuids, above = [], parent
        for joint_name in _joint_names(name, len(shown) - 2, attached=bool(parent)):
            joint = _long(cmds.createNode("joint", name=joint_name, **({"parent": above} if above else {})))
            if above:
                cmds.connectAttr(f"{above}.scale", f"{joint}.inverseScale", force=True)
            uuids.append(cmds.ls(joint, uuid=True)[0])
            above = joint
    for i, (uuid, preview, space) in enumerate(zip(uuids, driven, spaces)):
        joint = _by_uuid(uuid)
        for attr in _MOVES:
            cmds.setAttr(f"{joint}.{attr}", lock=False)
        for attr in ("translate", "rotate", "rotateAxis", "jointOrient"):
            cmds.setAttr(f"{joint}.{attr}", 0, 0, 0)
        for attr in _MOVES:
            cmds.setAttr(f"{joint}.{attr}", lock=True)
        if space is None:
            cmds.connectAttr(f"{preview}.worldMatrix[0]", f"{joint}.offsetParentMatrix", force=True)
        else:
            mult = _util(group, "multMatrix", f"{name}_{i + 1:02d}_joint_mult")
            cmds.connectAttr(f"{preview}.worldMatrix[0]", f"{mult}.matrixIn[0]")
            cmds.connectAttr(f"{space}.worldInverseMatrix[0]", f"{mult}.matrixIn[1]")
            cmds.connectAttr(f"{mult}.matrixSum", f"{joint}.offsetParentMatrix", force=True)
        _link(joint, group, f"{_JOINTS}[{i}]")


def _extract(group):
    """Delete ``group`` and everything it made, and cut its joints loose
    where they are, with plain translate and joint orient values (rotate
    zero). Chains attached under its joints go first. Returns its joints,
    top first, then theirs."""
    found = _check_extract(group)
    hanging = []
    for joint in joints(group):
        for child in attached(joint):
            hanging += cmds.ls(_extract(child), uuid=True)
    linked = joints(group)
    uuids = cmds.ls(linked, uuid=True)
    worlds = [om.MMatrix(cmds.xform(j, query=True, worldSpace=True, matrix=True)) for j in linked]
    note = (cmds.getAttr(f"{group}.{_TAG}"), cmds.getAttr(f"{group}.{_AXES_TEXT}") or "x y", _position(found["up"]))
    parented = parent_joint(group) is not None
    # One delete takes the drivers too, so the joints keep their last value.
    _remove(group)
    for uuid in uuids:
        joint = _by_uuid(uuid)
        cmds.setAttr(f"{joint}.offsetParentMatrix", list(om.MMatrix()), type="matrix")
        for attr in _MOVES:
            cmds.setAttr(f"{joint}.{attr}", lock=False)
    for uuid, world in zip(uuids, worlds):
        joint = _by_uuid(uuid)
        cmds.xform(joint, worldSpace=True, translation=(world[12], world[13], world[14]))
        orient.set_world_rotation(joint, world)
    # An attached chain can't be built again on its own: it gets no note.
    if uuids and not parented:
        _leave_note(_by_uuid(uuids[0]), *note)
    return [_by_uuid(uuid) for uuid in uuids + hanging]


def _check_extract(group):
    """``group``'s guides; raises ``ValueError`` if its joints can't be extracted."""
    found = guides(group)
    _plane([_position(g) for g in found["chain"]], _position(found["up"]))  # raises if it can't be built
    for joint in joints(group):
        for child in attached(joint):
            _check_extract(child)
    return found


def _leave_note(joint, name, axes, up):
    for attr, kind in ((_NOTE_NAME, "string"), (_NOTE_AXES, "string")):
        if not cmds.attributeQuery(attr, node=joint, exists=True):
            cmds.addAttr(joint, longName=attr, dataType=kind)
    if not cmds.attributeQuery(_NOTE_UP, node=joint, exists=True):
        cmds.addAttr(joint, longName=_NOTE_UP, attributeType="double3")
        for letter in "XYZ":
            cmds.addAttr(joint, longName=f"{_NOTE_UP}{letter}", attributeType="double", parent=_NOTE_UP)
    cmds.setAttr(f"{joint}.{_NOTE_NAME}", name, type="string")
    cmds.setAttr(f"{joint}.{_NOTE_AXES}", axes, type="string")
    cmds.setAttr(f"{joint}.{_NOTE_UP}", up.x, up.y, up.z)


def _note(joint, attr):
    return cmds.getAttr(f"{joint}.{attr}") if cmds.attributeQuery(attr, node=joint, exists=True) else None


def _check_name(name):
    if not isinstance(name, str) or not NAME.match(name):
        raise ValueError(
            f"Name {name!r} can't be used in node names: use letters, digits and _, not starting with a digit."
        )


def _remove(group):
    """Delete ``group``, with the utility nodes of its chain and of any chain
    whose group is under it."""
    below = cmds.listRelatives(group, allDescendents=True, type="transform", fullPath=True) or []
    nodes = [n for g in [group] + [b for b in below if _is_group(b)] for n in _connected(g, _NODES)]
    # While the guides go, the plane normal's inputs drop to zero; normalizing
    # that makes Maya print "found a zero-length output vector" errors.
    # Callers put the joints back where they were, so its value no longer matters.
    for node in cmds.ls(nodes, type="vectorProduct"):
        cmds.setAttr(f"{node}.normalizeOutput", False)
    cmds.delete(nodes + [group])


def _taken(name, count, owned=(), attached=False):
    owned = set(owned)
    return [n for n in _names(name, count, attached) if set(cmds.ls(n, long=True)) - owned]


def _check_free(name, count, owned=(), attached=False):
    taken = _taken(name, count, owned, attached)
    if taken:
        raise ValueError(f"These names are already used, rename or delete them first: {', '.join(taken)}")


def _build_at(name, positions, up_position, axes, uuids=None, parent=None):
    """Guides for ``name`` on ``positions`` (start, middles, end), the up
    guide on ``up_position``, and joints following them live (``uuids`` to
    reuse, top first, or new ones), attached under the ``parent`` joint if
    given. Checks nothing."""
    start_guide = None
    if parent:
        parent_group, index = _guided(parent)
        start_guide = guides(parent_group)["chain"][index]
    group = _create_guides(name, len(positions) - 2, positions[0], positions[-1], axes, start_guide)
    if parent:
        group = _long(cmds.parent(group, parent_group)[0])
        _link(parent, group, _PARENT)
        # Its first preview sits on the parent joint, which shows its own.
        cmds.setAttr(f"{previews(group)[0]}.visibility", False)
    chain = guides(group)["chain"]
    # The shared start guide stays where its own chain has it.
    for guide, position in list(zip(chain, positions))[1 if parent else 0 :]:
        cmds.xform(guide, worldSpace=True, translation=(position.x, position.y, position.z))
    cmds.xform(guides(group)["up"], worldSpace=True, translation=(up_position.x, up_position.y, up_position.z))
    _live_joints(group, name, uuids)
    return group


def _rounded(vector):
    # + 0.0 turns -0.0 into 0.0.
    return [round(c, 6) + 0.0 for c in (vector.x, vector.y, vector.z)]


def build_guides(name, count, start=(0, 0, 0), end=(10, 0, 0), aim=None, up=None):
    """Build guides for a chain named ``name`` with ``count`` middle guides,
    and a joint chain that follows them live (``aim`` points at the next
    joint and ``up`` towards the up guide's side, ``"x"``, ``"-y"``...).

    New guides go from ``start`` to ``end`` with the up guide to the side,
    aiming +X with up +Y unless given. If guides named ``name`` exist, their
    start, end and up guides stay where they are and the middle guides are
    replaced by ``count`` new ones, evenly between start and end; the axes
    stay unless given. Their joints stay too, unless the number of joints
    changes: then the old joints are replaced by new ones.
    Returns the guide group."""
    _check_name(name)
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("The number of middle guides must be 0 or more.")
    old = f"{name}_guides_grp"
    old = _long(old) if cmds.objExists(old) and _is_group(old) else None
    owned, keep, doomed = set(), None, []
    if old:
        found = guides(old)
        start, end = _position(found["chain"][0]), _position(found["chain"][-1])
        up_position = _position(found["up"])
        # Guides made before the axes were kept have none: use the defaults.
        kept = cmds.attributeQuery(_AXES_TEXT, node=old, exists=True) and cmds.getAttr(f"{old}.{_AXES_TEXT}")
        kept = kept.split() if kept else ("x", "y")
        aim, up = aim or kept[0], up or kept[1]
        linked = joints(old)
        if len(linked) == count + 2:
            keep = cmds.ls(linked, uuid=True)
        else:
            doomed = cmds.ls(linked, uuid=True)
        # Names the old guides (and joints about to go) use are free to reuse.
        owned = set(cmds.ls(old, dag=True, long=True)) | set(cmds.ls(_connected(old, _NODES), long=True))
        owned |= set(cmds.ls(linked, dag=True, long=True))
    axes = _axes(aim or "x", up or "y")
    if (om.MVector(end) - om.MVector(start)).length() < _TOLERANCE:
        raise ValueError("The start and end guides can't be on the same spot.")
    _check_free(name, count, owned)

    if old:
        _remove(old)
        for uuid in doomed:
            if cmds.ls(uuid):
                cmds.delete(cmds.ls(uuid, long=True))
    group = _create_guides(name, count, start, end, axes)
    if old:
        cmds.xform(guides(group)["up"], worldSpace=True, translation=(up_position.x, up_position.y, up_position.z))
    _live_joints(group, name, keep)
    return group


def free_joint(nodes):
    """The first joint among ``nodes`` (e.g. the selection) that doesn't
    follow guides, or ``None``: one to build guides from."""
    for joint in cmds.ls(nodes, type="joint", long=True) if nodes else []:
        linked = cmds.listConnections(f"{joint}.message", source=False, destination=True) or []
        if not any(_is_group(n) for n in cmds.ls(linked, long=True)):
            return joint
    return None


def _chain_from(joint):
    """The joint chain ``joint`` is in: from the joint above it holding a
    note left by Delete Guides (or ``joint`` itself) down its first child
    joints."""
    top, node = joint, joint
    while node:
        if cmds.attributeQuery(_NOTE_NAME, node=node, exists=True):
            top = node
            break
        parent = cmds.listRelatives(node, parent=True, type="joint", fullPath=True)
        node = parent[0] if parent else None
    chain = [top]
    while True:
        children = cmds.listRelatives(chain[-1], children=True, type="joint", fullPath=True)
        if not children:
            return chain
        chain.append(children[0])


def guides_from_joints(joint, name=None, aim=None, up=None):
    """Build guides for the joint chain ``joint`` is in, e.g. one extracted
    by :func:`delete_guides`, and make those same joints follow them live
    again: one guide on each joint, and the up guide where it was. A chain
    Delete Guides didn't leave takes ``name`` and the ``aim`` and ``up``
    axes (default +X, +Y), and gets its up guide to the side its top joint's
    up axis points to. Returns the guide group."""
    found = cmds.ls(joint, long=True, type="joint") if joint else []
    if not found:
        raise ValueError(f"{joint!r} isn't a joint.")
    chain = _chain_from(found[0])
    if len(chain) < 2:
        raise ValueError(f"{short_name(chain[0])} has no child joint: select a joint chain of 2 joints or more.")
    for node in chain:
        linked = cmds.listConnections(f"{node}.message", source=False, destination=True) or []
        if any(_is_group(n) for n in cmds.ls(linked, long=True)):
            raise ValueError(f"{short_name(chain[0])}'s chain already follows guides.")
    if cmds.listRelatives(chain[0], parent=True):
        raise ValueError(
            f"{short_name(chain[0])} must be at the world root while guides drive it; unparent it first."
        )
    top = chain[0]
    name = _note(top, _NOTE_NAME) or name
    _check_name(name)
    noted = (_note(top, _NOTE_AXES) or "").split()
    aim, up = (noted if len(noted) == 2 else (aim or "x", up or "y"))
    axes = _axes(aim, up)

    positions = [_position(node) for node in chain]
    start, end = positions[0], positions[-1]
    if cmds.attributeQuery(_NOTE_UP, node=top, exists=True):
        up_position = om.MVector(cmds.getAttr(f"{top}.{_NOTE_UP}")[0])
    else:
        side = orient.row(om.MMatrix(cmds.xform(top, query=True, worldSpace=True, matrix=True)), axes[1][0])
        up_position = (start + end) * 0.5 + side.normalize() * (axes[1][1] * (end - start).length() * 0.5)
    _plane(positions, up_position)  # raises if it can't be built
    _check_free(name, len(chain) - 2, owned=cmds.ls(chain, long=True))
    return _build_at(name, positions, up_position, axes, cmds.ls(chain, uuid=True))


def set_axes(group, aim="x", up="y"):
    """Turn ``group``'s joints and previews: ``aim`` points at the next joint
    and ``up`` towards the up guide's side (see :func:`build_guides`)."""
    _apply_axes(guide_group(group), *_axes(aim, up))


def delete_guides(group):
    """Delete ``group``, its guides and their preview, and extract their
    joints: they stay where they are, cut loose, with plain translate and
    joint orient values. Returns the joints, top first."""
    return _extract(guide_group(group))


def extract_problems(group):
    """Why :func:`delete_guides` can't extract ``group``'s joints, as
    messages; empty if it can."""
    try:
        _check_extract(guide_group(group))
    except ValueError as e:
        return [str(e)]
    return []


def leftover_joint(name):
    """The top joint :func:`delete_guides` left of guides named ``name``,
    if it doesn't follow guides again, else ``None``."""
    for joint in cmds.ls(f"*.{_NOTE_NAME}", objectsOnly=True, type="joint", long=True) or []:
        if _note(joint, _NOTE_NAME) == name and free_joint([joint]):
            return joint
    return None


def set_layout(group, positions, up_position, aim="x", up="y"):
    """Put ``group``'s guides on ``positions`` (start, middles, end) and its
    up guide on ``up_position``, turned to ``aim`` and ``up``. If the
    number of middle guides differs, they're made again first, as
    :func:`build_guides` does. Returns the guide group: a new one if the
    middle guides were made again."""
    group = guide_group(group)
    if len(positions) < 2:
        raise ValueError(f"The {short_name(group)} chain needs 2 guides or more.")
    axes = _axes(aim, up)
    positions, up_position = [om.MVector(p) for p in positions], om.MVector(up_position)
    _plane(positions, up_position)  # raises if it can't be built
    count = len(guides(group)["chain"])
    if count != len(positions) and parent_joint(group):
        raise ValueError(f"{short_name(group)} is attached to another chain: it keeps its {count} guides.")
    if count != len(positions):
        group = build_guides(cmds.getAttr(f"{group}.{_TAG}"), len(positions) - 2, aim=aim, up=up)
    else:
        _apply_axes(group, *axes)
    found = guides(group)
    for guide, position in zip(found["chain"], positions):
        cmds.xform(guide, worldSpace=True, translation=(position.x, position.y, position.z))
    cmds.xform(found["up"], worldSpace=True, translation=(up_position.x, up_position.y, up_position.z))
    return group


def taken_names(name, count):
    """The names that guides for ``name`` with ``count`` middle guides need
    and scene nodes already use."""
    return _taken(name, count)


def layout(group):
    """``group``'s chain as it is now, to build again with :func:`build_at`:
    ``{"name", "aim", "up", "guides": [start, middles..., end], "up_guide"}``,
    positions in world space."""
    group = guide_group(group)
    found = guides(group)
    aim, up = (cmds.getAttr(f"{group}.{_AXES_TEXT}") or "x y").split()
    return {
        "name": cmds.getAttr(f"{group}.{_TAG}"),
        "aim": aim,
        "up": up,
        "guides": [_rounded(_position(g)) for g in found["chain"]],
        "up_guide": _rounded(_position(found["up"])),
    }


def check_build(name, positions, up_position, aim="x", up="y", attached=False):
    """Raise ``ValueError`` if :func:`build_at` can't build these guides in
    the current scene (``attached`` under another chain's joint, if so).
    Changes nothing."""
    _check_name(name)
    if len(positions) < 2:
        raise ValueError(f"The {name} chain needs 2 guides or more.")
    _axes(aim, up)
    _plane(positions, up_position)
    _check_free(name, len(positions) - 2, attached=attached)


def build_at(name, positions, up_position, aim="x", up="y", parent=None):
    """Build guides for a chain named ``name`` with a guide on each of
    ``positions`` (start, middles, end) and the up guide on
    ``up_position``, and a joint chain that follows them live (see
    :func:`build_guides` for ``aim`` and ``up``). Returns the guide group.

    With ``parent``, a joint built from another chain's guides, the chain
    hangs under it: its start guide is that joint's guide (left where it
    is, so ``positions`` should start there), its joints from the second
    on are parented under ``parent``, and its group goes under the other
    chain's group."""
    if parent is not None:
        _guided(parent)  # raises if no guides drive it
    check_build(name, positions, up_position, aim, up, attached=parent is not None)
    positions = [om.MVector(p) for p in positions]
    return _build_at(name, positions, om.MVector(up_position), _axes(aim, up), parent=parent)

