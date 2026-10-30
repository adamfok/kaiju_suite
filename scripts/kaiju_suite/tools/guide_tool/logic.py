"""Guide Tool: place a joint chain with guide locators. No Qt here.

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

Every function that changes the scene is one undo step and raises
``ValueError``, changing nothing, when its input is wrong.
"""

import re

from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.core import orient
from kaiju_suite.core.naming import mirrored_name
from kaiju_suite.core.selection import short_name
from kaiju_suite.core.undo import undoable

NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# On the guide group: the chain's name, then message links to its nodes.
_TAG = "kaijuGuides"
_CHAIN = "guideChain"  # start, middle and end guides, in order
_UP = "guideUp"
_JOINTS = "guideJoints"  # the joints built from the guides, top first
_MIRRORS = "guideMirrors"  # the joints mirroring them across X, top first (if mirrored)
_CURVES = "guideCurves"  # the display curves: through the chain, start to up
_PREVIEWS = "guidePreviews"  # one transform per joint, placed as the joint will be
_PLANE = "guidePlane"
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
_NOTE_END = "kaijuGuideEnd"  # the end guide's position, left when it had no joint
# Mirroring a world matrix across X with behavior is _FLIP_AXES * matrix *
# _FLIP_X: X of the position flips, and each axis is mirrored then reversed.
_FLIP_AXES = [-1, 0, 0, 0, 0, -1, 0, 0, 0, 0, -1, 0, 0, 0, 0, 1]
_FLIP_X = [-1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
# Closer than this counts as the same spot.
_TOLERANCE = 1e-4
_UP_COLOR = 17  # yellow
_DISC_COLOR = 18  # light blue
# The solid color the discs and the plane share: shaded, so they show where
# they cut a mesh.
_SHADE = (0.35, 0.75, 1.0)  # light blue
# Turns a disc or cylinder made around X to lie around the axis with this index.
_DISC_ROTATE = {0: (0, 0, 0), 1: (0, 0, 90), 2: (0, -90, 0)}


def _preset(name, count, end, aim, up, up_side, end_joint=True):
    return {
        "name": name,
        "count": count,
        "start": (0, 0, 0),
        "end": end,
        "aim": aim,
        "up": up,
        "up_side": up_side,
        "end_joint": end_joint,
        "mirror": name.startswith("l_"),
    }


# Ready-made chains, each starting at the origin and going the way it goes
# on a ~180 cm body (Y up, facing +Z, left side at +X): build_guides(**PRESETS[name]).
# ``up_side`` is where the up guide goes, so the up axis points that way.
PRESETS = {
    preset["name"]: preset
    for preset in (
        _preset("root", 0, (0, 0, 10), "z", "y", (0, 1, 0), end_joint=False),
        _preset("spine", 3, (0, 45, 0), "y", "z", (0, 0, -1)),
        _preset("neck", 1, (0, 15, 0), "y", "z", (0, 0, -1)),
        _preset("head", 0, (0, 20, 0), "y", "z", (0, 0, 1)),
        _preset("l_shoulder", 0, (14, 2, 0), "x", "y", (0, 1, 0)),
        _preset("l_arm", 1, (53, 0, 0), "x", "y", (0, 0, -1)),  # elbow up guide behind
        _preset("l_hand", 0, (8, 0, 0), "x", "y", (0, 1, 0)),
        _preset("l_finger", 2, (10, 0, 0), "x", "y", (0, 1, 0)),
        _preset("l_leg", 1, (0, -85, 0), "x", "y", (0, 0, 1)),
        _preset("l_foot", 1, (0, -10, 20), "x", "y", (0, 1, 0)),
        # A hind leg: hip, stifle, hock, fetlock and the toe tip.
        _preset("l_quad_leg", 3, (0, -95, 0), "x", "y", (0, 0, 1)),
        _preset("forward_spine", 3, (0, 0, 60), "x", "y", (0, 1, 0)),
        _preset("tail", 4, (0, 0, -60), "x", "y", (0, 1, 0)),
    )
}


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


def _lock_to_scale_only(node):
    """Lock ``node``'s translate and rotate; its scale is the user's."""
    for attr in ("tx", "ty", "tz", "rx", "ry", "rz"):
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


# A node network places the joints live: it projects the middle
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


def _visual(node, color=None, shaded=False, selectable=False):
    """Draw ``node`` as wireframe unless ``shaded``, unselectable unless ``selectable``."""
    cmds.setAttr(f"{node}.overrideEnabled", True)
    cmds.setAttr(f"{node}.overrideDisplayType", 0 if selectable else 2)  # normal or reference
    cmds.setAttr(f"{node}.overrideShading", shaded)
    if color is not None:
        cmds.setAttr(f"{node}.overrideColor", color)


def _placed(group, node, matrix):
    """Put ``node`` under ``group``, placed in world space by ``matrix``."""
    node = _long(cmds.parent(node, group, relative=True)[0])
    cmds.setAttr(f"{node}.inheritsTransform", False)
    cmds.connectAttr(matrix, f"{node}.offsetParentMatrix")
    return node


def _material(group, name, color):
    """A shading group with a solid lambert of ``color``."""
    material = _util(group, "lambert", f"{name}_mat")
    cmds.setAttr(f"{material}.color", *color)
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
    _visual(disc, _DISC_COLOR, shaded=True, selectable=True)
    _lock_to_scale_only(disc)
    cmds.sets(cmds.listRelatives(disc, shapes=True, fullPath=True), edit=True, forceElement=engine)
    return disc


def _cylinder(name, parent, radius, length, engine):
    """A cylinder through ``parent`` along X, turned onto the rotate axis by
    ``_apply_axes``: the axis the joint bends around."""
    cylinder = cmds.cylinder(
        axis=(1, 0, 0), radius=radius, heightRatio=length / radius, sections=12, constructionHistory=False
    )[0]
    cylinder = cmds.rename(cmds.parent(cylinder, parent, relative=True)[0], name)
    cylinder = _long(f"{parent}|{cylinder}")
    _visual(cylinder, _DISC_COLOR, shaded=True, selectable=True)
    _lock_to_scale_only(cylinder)
    cmds.sets(cmds.listRelatives(cylinder, shapes=True, fullPath=True), edit=True, forceElement=engine)
    return cylinder


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
        _disc(f"{label}_disc", preview, size * 2, engine)  # first child
        _cylinder(f"{label}_axis", preview, size * 0.3, size * 6, engine)  # second child
        _link(preview, group, f"{_PREVIEWS}[{i}]")

    matrix = _aligned(group, f"{name}_plane", start, (1, 0, 0), span, (0, 0, 1), normal)
    # The space sits on the first joint, follows the guides and sizes the
    # plane to them (one unit of X is start to end); the plane under it keeps
    # its own scale free for the user, and scales from the first joint.
    space = _placed(group, cmds.createNode("transform", name=f"{name}_plane_space"), matrix)
    # Centered between start and end, reaching a tenth of the span past each.
    surface = cmds.nurbsPlane(
        name=f"{name}_plane",
        axis=(0, 0, 1),
        pivot=(0.5, 0, 0),
        width=1.2,
        lengthRatio=1 / 1.2,
        patchesU=4,
        patchesV=2,
        constructionHistory=False,
    )[0]
    surface = _long(cmds.parent(surface, space, relative=True)[0])
    length = _util(group, "distanceBetween", f"{name}_length")
    cmds.connectAttr(start, f"{length}.point1")
    cmds.connectAttr(end, f"{length}.point2")
    scale = _util(group, "multiplyDivide", f"{name}_plane_size")
    cmds.setAttr(f"{scale}.input2", 1, 0.6, 1)
    for letter in "XY":
        cmds.connectAttr(f"{length}.distance", f"{scale}.input1{letter}")
        cmds.connectAttr(f"{scale}.output{letter}", f"{space}.scale{letter}")
    _visual(surface, shaded=True, selectable=True)
    _lock_to_scale_only(surface)
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
        # The disc rings the aim axis; the cylinder lies along the third axis.
        for node, index in zip(_parts(preview), (aim[0], third)):
            for attr in ("rx", "ry", "rz"):
                cmds.setAttr(f"{node}.{attr}", lock=False)
            cmds.setAttr(f"{node}.rotate", *_DISC_ROTATE[index])
            for attr in ("rx", "ry", "rz"):
                cmds.setAttr(f"{node}.{attr}", lock=True)


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


def mirrored_joints(group):
    """The joints mirroring ``group``'s joints across X, top first, or ``[]``."""
    group = guide_group(group)
    if not cmds.attributeQuery(_MIRRORS, node=group, exists=True):
        return []
    return _connected(group, _MIRRORS)


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


def _chain_names(name, count):
    middles = [f"{name}_mid_{i:02d}_guide" for i in range(1, count + 1)]
    return [f"{name}_start_guide"] + middles + [f"{name}_end_guide"]


def _joint_names(name, count, end_joint=True):
    """The joints' names for ``count`` middle guides: one per guide, the
    last one ``<name>_<N>_jnt_end``; or, without ``end_joint``, none on the
    end guide."""
    if not end_joint:
        return [f"{name}_{i:02d}_jnt" for i in range(1, count + 2)]
    return [f"{name}_{i:02d}_jnt" for i in range(1, count + 2)] + [f"{name}_{count + 2:02d}_jnt_end"]


def _names(name, count, end_joint=True):
    """Every name building ``count`` middle guides for ``name`` uses."""
    names = [f"{name}_guides_grp", f"{name}_up_guide", f"{name}_guide_crv", f"{name}_up_crv", f"{name}_plane"]
    names += _chain_names(name, count) + _joint_names(name, count, end_joint)
    return names + [f"{name}_{i:02d}_{kind}" for i in range(1, count + 3) for kind in ("preview", "disc")]


def _create_guides(name, count, start, end, axes, up_side=None):
    """Make the guide group, guides and preview for a chain named ``name``:
    start and end guides at ``start`` and ``end``, ``count`` middle guides
    evenly between them, and an up guide off to the side."""
    start, end = om.MVector(start), om.MVector(end)
    span = end - start
    chain_names = _chain_names(name, count)

    group = _long(cmds.createNode("transform", name=f"{name}_guides_grp"))
    cmds.addAttr(group, longName=_TAG, dataType="string")
    cmds.setAttr(f"{group}.{_TAG}", name, type="string")
    for attr in (_CHAIN, _JOINTS, _MIRRORS, _CURVES, _PREVIEWS, _NODES):
        cmds.addAttr(group, longName=attr, attributeType="message", multi=True)
    for attr in (_UP, _PLANE):
        cmds.addAttr(group, longName=attr, attributeType="message")
    cmds.addAttr(group, longName=_AXES_TEXT, dataType="string")
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

    if up_side is not None:
        side = om.MVector(up_side).normalize()
    else:
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


def _live_joints(group, name, uuids=None, end_joint=True):
    """Make the chain's joints follow the previews (``uuids`` are joints to
    reuse, top first; new ones are made if not given). Each joint's offset
    parent matrix is its preview's world matrix in the space of the preview
    above it, which is where its parent joint is (the top joint takes its
    preview's world matrix, so it must stay at the world root). Reading the
    joints' own parentInverseMatrix instead goes stale. Translate and rotate
    stay zero, locked. Without ``end_joint`` no joint follows the end
    guide's preview, which is hidden."""
    if uuids is None:
        uuids, parent = [], None
        for joint_name in _joint_names(name, len(previews(group)) - 2, end_joint):
            joint = _long(cmds.createNode("joint", name=joint_name, **({"parent": parent} if parent else {})))
            if parent:
                cmds.connectAttr(f"{parent}.scale", f"{joint}.inverseScale", force=True)
            uuids.append(cmds.ls(joint, uuid=True)[0])
            parent = joint
    shown = previews(group)
    cmds.setAttr(f"{shown[-1]}.visibility", end_joint)
    for i, (uuid, preview) in enumerate(zip(uuids, shown)):
        joint = _by_uuid(uuid)
        for attr in _MOVES:
            cmds.setAttr(f"{joint}.{attr}", lock=False)
        for attr in ("translate", "rotate", "rotateAxis", "jointOrient"):
            cmds.setAttr(f"{joint}.{attr}", 0, 0, 0)
        for attr in _MOVES:
            cmds.setAttr(f"{joint}.{attr}", lock=True)
        # Reference while the guides drive them, so a click picks a guide.
        cmds.setAttr(f"{joint}.overrideEnabled", True)
        cmds.setAttr(f"{joint}.overrideDisplayType", 2)
        if i == 0:
            cmds.connectAttr(f"{preview}.worldMatrix[0]", f"{joint}.offsetParentMatrix", force=True)
        else:
            mult = _util(group, "multMatrix", f"{name}_{i + 1:02d}_joint_mult")
            cmds.connectAttr(f"{preview}.worldMatrix[0]", f"{mult}.matrixIn[0]")
            cmds.connectAttr(f"{shown[i - 1]}.worldInverseMatrix[0]", f"{mult}.matrixIn[1]")
            cmds.connectAttr(f"{mult}.matrixSum", f"{joint}.offsetParentMatrix", force=True)
        _link(joint, group, f"{_JOINTS}[{i}]")


def _mirror_joints(group, uuids=None):
    """Make joints that mirror ``group``'s joints across X with behavior and
    follow them live (``uuids`` are joints to reuse, top first; new ones,
    named for the other side, are made if not given). The top one takes its
    joint's mirrored world matrix, so it must stay at the world root; the
    others take their joint's matrix relative to its parent, flipped, which
    is the mirrored one relative to the mirrored parent. Translate and
    rotate stay zero, locked."""
    guided = joints(group)
    if uuids is None:
        uuids, parent = [], None
        for joint_name in [mirrored_name(short_name(j)) for j in guided]:
            joint = _long(cmds.createNode("joint", name=joint_name, **({"parent": parent} if parent else {})))
            if parent:
                cmds.connectAttr(f"{parent}.scale", f"{joint}.inverseScale", force=True)
            uuids.append(cmds.ls(joint, uuid=True)[0])
            parent = joint
    name = cmds.getAttr(f"{group}.{_TAG}")
    for i, (uuid, source) in enumerate(zip(uuids, guided)):
        joint = _by_uuid(uuid)
        for attr in _MOVES:
            cmds.setAttr(f"{joint}.{attr}", lock=False)
        for attr in ("translate", "rotate", "rotateAxis", "jointOrient"):
            cmds.setAttr(f"{joint}.{attr}", 0, 0, 0)
        for attr in _MOVES:
            cmds.setAttr(f"{joint}.{attr}", lock=True)
        cmds.setAttr(f"{joint}.overrideEnabled", True)
        cmds.setAttr(f"{joint}.overrideDisplayType", 2)
        mult = _util(group, "multMatrix", f"{name}_{i + 1:02d}_mirror_mult")
        cmds.setAttr(f"{mult}.matrixIn[0]", _FLIP_AXES, type="matrix")
        cmds.connectAttr(f"{source}.worldMatrix[0]", f"{mult}.matrixIn[1]")
        if i == 0:
            cmds.setAttr(f"{mult}.matrixIn[2]", _FLIP_X, type="matrix")
        else:
            cmds.connectAttr(f"{guided[i - 1]}.worldInverseMatrix[0]", f"{mult}.matrixIn[2]")
            cmds.setAttr(f"{mult}.matrixIn[3]", _FLIP_AXES, type="matrix")
        cmds.connectAttr(f"{mult}.matrixSum", f"{joint}.offsetParentMatrix", force=True)
        _link(joint, group, f"{_MIRRORS}[{i}]")


def _extract(group):
    """Delete ``group`` and everything it made, and cut its joints loose
    where they are, with plain translate and joint orient values (rotate
    zero). Returns them, top first."""
    found = guides(group)
    _plane([_position(g) for g in found["chain"]], _position(found["up"]))  # raises if it can't be built
    uuids = cmds.ls(joints(group), uuid=True)
    every = uuids + cmds.ls(mirrored_joints(group), uuid=True)
    worlds = [om.MMatrix(cmds.xform(_by_uuid(u), query=True, worldSpace=True, matrix=True)) for u in every]
    # With no joint on the end guide, the note keeps where it was.
    end = _position(found["chain"][-1]) if len(uuids) < len(found["chain"]) else None
    note = (
        cmds.getAttr(f"{group}.{_TAG}"),
        cmds.getAttr(f"{group}.{_AXES_TEXT}") or "x y",
        _position(found["up"]),
        end,
    )
    # One delete takes the drivers too, so the joints keep their last value.
    _remove(group)
    for uuid in every:
        joint = _by_uuid(uuid)
        cmds.setAttr(f"{joint}.offsetParentMatrix", list(om.MMatrix()), type="matrix")
        for attr in _MOVES:
            cmds.setAttr(f"{joint}.{attr}", lock=False)
        _unreference(joint)
    for uuid, world in zip(every, worlds):
        joint = _by_uuid(uuid)
        cmds.xform(joint, worldSpace=True, translation=(world[12], world[13], world[14]))
        orient.set_world_rotation(joint, world)
    if uuids:
        _leave_note(_by_uuid(uuids[0]), *note)
    return [_by_uuid(uuid) for uuid in uuids]


def _unreference(joint):
    """Draw ``joint`` normally again, keeping a color override if it has one."""
    cmds.setAttr(f"{joint}.overrideDisplayType", 0)
    if not cmds.getAttr(f"{joint}.overrideColor") and not cmds.getAttr(f"{joint}.overrideRGBColors"):
        cmds.setAttr(f"{joint}.overrideEnabled", False)


def _leave_note(joint, name, axes, up, end=None):
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
    if cmds.attributeQuery(_NOTE_END, node=joint, exists=True):
        cmds.deleteAttr(f"{joint}.{_NOTE_END}")
    if end is not None:
        cmds.addAttr(joint, longName=_NOTE_END, attributeType="double3")
        for letter in "XYZ":
            cmds.addAttr(joint, longName=f"{_NOTE_END}{letter}", attributeType="double", parent=_NOTE_END)
        cmds.setAttr(f"{joint}.{_NOTE_END}", end.x, end.y, end.z)


def _note(joint, attr):
    return cmds.getAttr(f"{joint}.{attr}") if cmds.attributeQuery(attr, node=joint, exists=True) else None


def _check_name(name):
    if not isinstance(name, str) or not NAME.match(name):
        raise ValueError(
            f"Name {name!r} can't be used in node names: use letters, digits and _, not starting with a digit."
        )


def _remove(group):
    nodes = _connected(group, _NODES)
    # While the delete cuts their inputs, a normalizing cross product would
    # print "found a zero-length output vector" as an error.
    for node in cmds.ls(nodes, type="vectorProduct"):
        cmds.setAttr(f"{node}.normalizeOutput", False)
    cmds.delete(nodes + [group])


@undoable
def build_guides(
    name, count, start=(0, 0, 0), end=(10, 0, 0), aim=None, up=None, mirror=False, end_joint=True, up_side=None
):
    """Build guides for a chain named ``name`` with ``count`` middle guides,
    and a joint chain that follows them live (``aim`` points at the next
    joint and ``up`` towards the up guide's side, ``"x"``, ``"-y"``...).

    New guides go from ``start`` to ``end`` with the up guide to the side
    (towards ``up_side``, a direction, if given), aiming +X with up +Y
    unless given. :data:`PRESETS` holds ready-made settings. If guides named ``name`` exist, their
    start, end and up guides stay where they are and the middle guides are
    replaced by ``count`` new ones, evenly between start and end; the axes
    stay unless given. Their joints stay too, unless the number of joints
    changes: then the old joints are replaced by new ones.
    The last joint, on the end guide, is ``<name>_<N>_jnt_end``; without
    ``end_joint`` there's no joint on the end guide (it still aims the last
    joint). With ``mirror``, a second chain named for the other side (see
    :func:`~kaiju_suite.core.naming.mirrored_name`) mirrors the joints across
    X with behavior and follows them live; building again without it removes
    that chain. Returns the guide group."""
    _check_name(name)
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("The number of middle guides must be 0 or more.")
    old = f"{name}_guides_grp"
    old = _long(old) if cmds.objExists(old) and _is_group(old) else None
    owned, keep, doomed, scales, keep_mirror = set(), None, [], None, None
    if old:
        found = guides(old)
        start, end = _position(found["chain"][0]), _position(found["chain"][-1])
        up_position = _position(found["up"])
        # Guides made before the axes were kept have none: use the defaults.
        kept = cmds.attributeQuery(_AXES_TEXT, node=old, exists=True) and cmds.getAttr(f"{old}.{_AXES_TEXT}")
        kept = kept.split() if kept else ("x", "y")
        aim, up = aim or kept[0], up or kept[1]
        linked = joints(old)
        scales = _scales(old)
        if len(linked) == count + (2 if end_joint else 1):
            keep = cmds.ls(linked, uuid=True)
        else:
            doomed = cmds.ls(linked, uuid=True)
        mirrors = mirrored_joints(old)
        if mirror and keep and len(mirrors) == len(keep):
            keep_mirror = cmds.ls(mirrors, uuid=True)
        else:
            doomed += cmds.ls(mirrors, uuid=True)
        linked += mirrors
        # Names the old guides (and joints about to go) use are free to reuse.
        owned = set(cmds.ls(old, dag=True, long=True)) | set(cmds.ls(_connected(old, _NODES), long=True))
        owned |= set(cmds.ls(linked, dag=True, long=True))
    axes = _axes(aim or "x", up or "y")
    if (om.MVector(end) - om.MVector(start)).length() < _TOLERANCE:
        raise ValueError("The start and end guides can't be on the same spot.")
    names = _names(name, count, end_joint)
    if mirror and keep_mirror is None:
        joint_names = [short_name(j) for j in cmds.ls(keep, long=True)] if keep else _joint_names(name, count, end_joint)
        names += [mirrored_name(n) for n in joint_names]
    taken = [n for n in names if set(cmds.ls(n, long=True)) - owned]
    if taken:
        raise ValueError(f"These names are already used, rename or delete them first: {', '.join(taken)}")

    if old:
        _remove(old)
        for uuid in doomed:
            if cmds.ls(uuid):
                cmds.delete(cmds.ls(uuid, long=True))
    group = _create_guides(name, count, start, end, axes, up_side)
    if old:
        cmds.xform(guides(group)["up"], worldSpace=True, translation=(up_position.x, up_position.y, up_position.z))
    _live_joints(group, name, keep, end_joint)
    if mirror:
        _mirror_joints(group, keep_mirror)
    if scales:
        _set_scales(group, *scales)
    return group


def _scales(group):
    """The user's scale of ``group``'s plane, and of each joint's disc and cylinder."""
    parts = [n for p in previews(group) for n in _parts(p)]
    return cmds.getAttr(f"{plane(group)}.scale")[0], [cmds.getAttr(f"{n}.scale")[0] for n in parts]


def _set_scales(group, plane_scale, part_scales):
    """Give ``group`` the plane scale, and the disc and cylinder scales if it
    has as many joints."""
    cmds.setAttr(f"{plane(group)}.scale", *plane_scale)
    parts = [n for p in previews(group) for n in _parts(p)]
    if len(parts) == len(part_scales):
        for node, scale in zip(parts, part_scales):
            cmds.setAttr(f"{node}.scale", *scale)


def _parts(preview):
    """A preview's disc and cylinder, in the order ``_preview_network`` made them."""
    return cmds.listRelatives(preview, children=True, type="transform", fullPath=True) or []


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


@undoable
def guides_from_joints(joint, name=None, aim=None, up=None, mirror=False):
    """Build guides for the joint chain ``joint`` is in, e.g. one extracted
    by :func:`delete_guides`, and make those same joints follow them live
    again: one guide on each joint, and the up guide where it was. A chain
    the Guide Tool didn't make takes ``name`` and the ``aim`` and ``up``
    axes (default +X, +Y), and gets its up guide to the side its top joint's
    up axis points to. With ``mirror``, the joints are mirrored as by
    :func:`build_guides`, reusing a free chain already named for the other
    side (e.g. one Delete Guides cut loose). A chain cut loose with no joint
    on its end guide gets that guide back where it was. Returns the guide group."""
    found = cmds.ls(joint, long=True, type="joint") if joint else []
    if not found:
        raise ValueError(f"{joint!r} isn't a joint.")
    chain = _chain_from(found[0])
    noted_end = cmds.attributeQuery(_NOTE_END, node=chain[0], exists=True)
    if len(chain) < (1 if noted_end else 2):
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
    if noted_end:
        positions.append(om.MVector(cmds.getAttr(f"{top}.{_NOTE_END}")[0]))
    start, end = positions[0], positions[-1]
    if cmds.attributeQuery(_NOTE_UP, node=top, exists=True):
        up_position = om.MVector(cmds.getAttr(f"{top}.{_NOTE_UP}")[0])
    else:
        side = orient.row(om.MMatrix(cmds.xform(top, query=True, worldSpace=True, matrix=True)), axes[1][0])
        up_position = (start + end) * 0.5 + side.normalize() * (axes[1][1] * (end - start).length() * 0.5)
    _plane(positions, up_position)  # raises if it can't be built
    count = len(positions) - 2
    owned = set(cmds.ls(chain, long=True))
    names, reuse = _names(name, count, not noted_end), None
    if mirror:
        reuse = _free_mirror(chain)
        if reuse is None:
            names += [mirrored_name(short_name(node)) for node in chain]
    taken = [n for n in names if set(cmds.ls(n, long=True)) - owned]
    if taken:
        raise ValueError(f"These names are already used, rename or delete them first: {', '.join(taken)}")

    uuids = cmds.ls(chain, uuid=True)
    group = _create_guides(name, count, start, end, axes)
    for guide, position in zip(guides(group)["chain"], positions):
        cmds.xform(guide, worldSpace=True, translation=(position.x, position.y, position.z))
    cmds.xform(guides(group)["up"], worldSpace=True, translation=(up_position.x, up_position.y, up_position.z))
    _live_joints(group, name, uuids, not noted_end)
    if mirror:
        _mirror_joints(group, reuse)
    return group


def _free_mirror(chain):
    """The uuids of a free joint chain at the world root named for the other
    side of ``chain``, joint for joint, or ``None`` if there isn't one."""
    found = cmds.ls(mirrored_name(short_name(chain[0])), long=True, type="joint")
    if len(found) != 1 or cmds.listRelatives(found[0], parent=True) or not free_joint(found):
        return None
    mirror = _chain_from(found[0])
    if [short_name(n) for n in mirror] != [mirrored_name(short_name(n)) for n in chain]:
        return None
    return cmds.ls(mirror, uuid=True)


@undoable
def set_axes(group, aim="x", up="y"):
    """Turn ``group``'s joints and previews: ``aim`` points at the next joint
    and ``up`` towards the up guide's side (see :func:`build_guides`)."""
    _apply_axes(guide_group(group), *_axes(aim, up))


@undoable
def delete_guides(group):
    """Delete ``group``, its guides and their preview, and extract their
    joints: they stay where they are, cut loose, with plain translate and
    joint orient values. Returns the joints, top first."""
    return _extract(guide_group(group))
