"""Mirroring across the world YZ plane (X flips), shared by the Pose and
Animation tools. No Qt here.

A node's opposite is the node whose name has the other side (``L_arm_ctrl``
and ``R_arm_ctrl``, see :func:`kaiju_suite.core.naming.opposite_name`); a
node with no side in its name is a centre node and mirrors onto itself.

Translate and rotate are worked out from both nodes' rest frames (the
parent's world matrix, and the joint orient on joints), so world-aligned
controls, and joints mirrored with either Behavior or Orientation, all come
out mirrored in the world. ``rotateAxis`` isn't taken into account. Every
other attribute is copied as it is.
"""

from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.core.naming import opposite_name

TRANSLATE = ("translateX", "translateY", "translateZ")
ROTATE = ("rotateX", "rotateY", "rotateZ")
_MIRROR = om.MMatrix([[-1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
# How far off ±1 or 0 a frame-to-frame matrix entry may be and still count
# as a plain axis flip.
_TOLERANCE = 1e-5


def short(node):
    return cmds.ls(node)[0]


# -- sides ------------------------------------------------------------------


def opposite(node):
    """The long name of ``node``'s opposite, or ``None`` if its name has no
    side or no single node has the opposite name."""
    name = opposite_name(short(node))
    found = cmds.ls(name, long=True) if name else []
    return found[0] if len(found) == 1 else None


def opposites(nodes):
    """The opposites of ``nodes`` that exist, in order, each once."""
    return list(dict.fromkeys(filter(None, (opposite(node) for node in nodes))))


def sides(nodes):
    """``(pairs, skipped)``: ``(node, opposite)`` for each node, a centre
    node paired with itself, and messages for nodes whose opposite is missing."""
    pairs, skipped = [], []
    for node in dict.fromkeys(cmds.ls(nodes, long=True) or []):
        name = opposite_name(short(node))
        if name is None:
            pairs.append((node, node))
            continue
        other = opposite(node)
        if other is None:
            count = len(cmds.ls(name))
            reason = f"several nodes are named {name}" if count > 1 else f"no {name} in the scene"
            skipped.append(f"{short(node)}: {reason}")
        else:
            pairs.append((node, other))
    return pairs, skipped


def both_sides(pairs):
    """``"A and B"`` for each pair whose opposite was given before it, i.e.
    both sides of a pair were given."""
    sources = [source for source, _ in pairs]
    return [f"{short(s)} and {short(t)}" for s, t in pairs if s != t and t in sources[: sources.index(s)]]


# -- attributes -------------------------------------------------------------


def keyable(node):
    """``{attr: value}`` of ``node``'s keyable, unlocked, scalar attributes
    (no multis or their children, so each can be set as ``node.attr``)."""
    values = {}
    for attr in cmds.listAttr(node, keyable=True, unlocked=True, scalar=True) or []:
        if "." in attr or cmds.attributeQuery(attr, node=node, multi=True):
            continue
        value = cmds.getAttr(f"{node}.{attr}")
        if isinstance(value, (bool, int, float)):
            values[attr] = value
    return values


def skip_reason(node, attr):
    """Why ``node.attr`` can't be set (``"missing"``, ``"locked"``, or
    ``"connected"`` to something other than its own keys), else ``None``."""
    if not cmds.attributeQuery(attr, node=node, exists=True):
        return "missing"
    plug = f"{node}.{attr}"
    if cmds.getAttr(plug, lock=True):
        return "locked"
    sources = cmds.listConnections(plug, source=True, destination=False, skipConversionNodes=True) or []
    if any(not cmds.nodeType(source).startswith("animCurveT") for source in sources):
        return "connected"
    return None


# -- frames -----------------------------------------------------------------


def _get(plug, time):
    return cmds.getAttr(plug) if time is None else cmds.getAttr(plug, time=time)


def parent_frame(node, time=None):
    """The parent's world matrix without its translation (at ``time``, or now)."""
    m = om.MMatrix(_get(f"{node}.parentMatrix[0]", time))
    m.setElement(3, 0, 0)
    m.setElement(3, 1, 0)
    m.setElement(3, 2, 0)
    return m


def rotate_frame(node, time=None):
    """The world orientation ``node``'s rotate channels turn in: its parent's
    rotation, after the joint orient on a joint."""
    parent = om.MTransformationMatrix(parent_frame(node, time)).asRotateMatrix()
    if cmds.nodeType(node) != "joint":
        return parent
    orient = [om.MAngle(v, om.MAngle.kDegrees).asRadians() for v in _get(f"{node}.jointOrient", time)[0]]
    return om.MEulerRotation(orient).asMatrix() * parent


def frames(node, time=None):
    """What mirroring needs to know about where ``node``'s channels live."""
    return {
        "parent_frame": parent_frame(node, time),
        "rotate_frame": rotate_frame(node, time),
        "order": cmds.getAttr(f"{node}.rotateOrder"),
    }


def flips(source, target):
    """``(translate flip, rotate flip)`` matrices from ``source``'s frames to
    ``target``'s (both :func:`frames`)."""
    return (
        source["parent_frame"] * _MIRROR * target["parent_frame"].inverse(),
        source["rotate_frame"] * _MIRROR * target["rotate_frame"].inverse(),
    )


def axis_signs(m):
    """The diagonal of ``m``'s rotation part if it's a plain axis flip, else ``None``."""
    signs = []
    for i in range(3):
        for j in range(3):
            value = m.getElement(i, j)
            if i == j and abs(abs(value) - 1) > _TOLERANCE or i != j and abs(value) > _TOLERANCE:
                return None
        signs.append(1 if m.getElement(i, i) > 0 else -1)
    return signs


def channel_signs(source, target):
    """``{attr: ±1}`` for translate and rotate when each target channel is
    just its source channel times ±1 (a plain axis flip and the same rotate
    order), else ``None`` for that group: ``(translate signs, rotate signs)``."""
    flip_t, flip_r = flips(source, target)
    signs_t = axis_signs(flip_t)
    signs_r = axis_signs(flip_r) if source["order"] == target["order"] else None
    return (
        dict(zip(TRANSLATE, signs_t)) if signs_t else None,
        # Negating the frame flips the rotation's handedness: angle * -sign.
        dict(zip(ROTATE, (-sign for sign in signs_r))) if signs_r else None,
    )


def mirror_translate(translate, source, target):
    """``translate`` (in ``source``'s parent space) mirrored into ``target``'s."""
    # Row vectors, as in OpenMaya: to world, mirrored, to the target's parent space.
    flip_t, _ = flips(source, target)
    vector = om.MVector(translate) * flip_t
    return [vector.x, vector.y, vector.z]


def mirror_rotate(rotate, source, target, near=None):
    """``rotate`` (degrees, in ``source``'s frame and order) mirrored into
    ``target``'s, as the Euler solution closest to ``near`` (degrees)."""
    _, flip_r = flips(source, target)
    signs = axis_signs(flip_r)
    if signs and source["order"] == target["order"]:
        # A plain axis flip: negate angles, keeping values past 180 as they are.
        return [-sign * angle for sign, angle in zip(signs, rotate)]
    # A rotation in the source's frame, mirrored in the world, in the
    # target's frame: K⁻¹ R K, with K the frame-to-frame flip.
    radians = [om.MAngle(a, om.MAngle.kDegrees).asRadians() for a in rotate]
    matrix = flip_r.transpose() * om.MEulerRotation(radians, source["order"]).asMatrix() * flip_r
    euler = om.MTransformationMatrix(matrix).rotation().reorder(target["order"])
    if near is not None:
        near = [om.MAngle(a, om.MAngle.kDegrees).asRadians() for a in near]
        euler = euler.closestSolution(om.MEulerRotation(near, target["order"]))
    return [om.MAngle(a).asDegrees() for a in (euler.x, euler.y, euler.z)]
