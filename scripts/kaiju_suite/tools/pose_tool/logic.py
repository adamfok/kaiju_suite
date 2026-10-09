"""Pose Tool: mirror, flip and reset poses. No Qt here.

A node's opposite is the node whose name has the other side (``L_arm_ctrl``
and ``R_arm_ctrl``, see :func:`kaiju_suite.core.naming.opposite_name`); a
node with no side in its name is a centre node and mirrors onto itself.

Mirroring works across the world YZ plane (X flips). Translate and rotate
are worked out from both nodes' rest frames (the parent's world matrix,
and the joint orient on joints), so world-aligned controls, and joints
mirrored with either Behavior or Orientation, all come out mirrored in the
world. ``rotateAxis`` isn't taken into account. Scale and every other
keyable attribute are copied as they are.

Only keyable, unlocked attributes of the source are copied; on the target,
attributes that are missing, locked or driven by a connection other than
their own keys are skipped and reported.
"""

from collections import namedtuple

from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.core.naming import opposite_name
from kaiju_suite.core.undo import undoable

Result = namedtuple("Result", "changed skipped")

_TRANSLATE = ("translateX", "translateY", "translateZ")
_ROTATE = ("rotateX", "rotateY", "rotateZ")
_MIRROR = om.MMatrix([[-1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
# How far off ±1 or 0 a frame-to-frame matrix entry may be and still count
# as a plain axis flip.
_TOLERANCE = 1e-5


def _short(node):
    return cmds.ls(node)[0]


def opposite(node):
    """The long name of ``node``'s opposite, or ``None`` if its name has no
    side or no single node has the opposite name."""
    name = opposite_name(_short(node))
    found = cmds.ls(name, long=True) if name else []
    return found[0] if len(found) == 1 else None


def opposites(nodes):
    """The opposites of ``nodes`` that exist, in order, each once."""
    return list(dict.fromkeys(filter(None, (opposite(node) for node in nodes))))


# -- attributes -------------------------------------------------------------


def _keyable(node):
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


def _skip_reason(node, attr):
    if not cmds.attributeQuery(attr, node=node, exists=True):
        return "missing"
    plug = f"{node}.{attr}"
    if cmds.getAttr(plug, lock=True):
        return "locked"
    sources = cmds.listConnections(plug, source=True, destination=False, skipConversionNodes=True) or []
    if any(not cmds.nodeType(source).startswith("animCurveT") for source in sources):
        return "connected"
    return None


def _set_all(changes):
    """Set ``[(node, {attr: value})]``; returns the plugs skipped, with why."""
    skipped = []
    for node, values in changes:
        for attr, value in values.items():
            reason = _skip_reason(node, attr)
            if reason:
                skipped.append(f"{_short(node)}.{attr} ({reason})")
            else:
                cmds.setAttr(f"{node}.{attr}", value)
    return skipped


# -- mirroring --------------------------------------------------------------


def _parent_frame(node):
    """The parent's world matrix without its translation."""
    m = om.MMatrix(cmds.getAttr(f"{node}.parentMatrix[0]"))
    m.setElement(3, 0, 0)
    m.setElement(3, 1, 0)
    m.setElement(3, 2, 0)
    return m


def _rotate_frame(node):
    """The world orientation ``node``'s rotate channels turn in: its parent's
    rotation, after the joint orient on a joint."""
    parent = om.MTransformationMatrix(_parent_frame(node)).asRotateMatrix()
    if cmds.nodeType(node) != "joint":
        return parent
    orient = om.MEulerRotation([om.MAngle(v, om.MAngle.kDegrees).asRadians() for v in cmds.getAttr(f"{node}.jointOrient")[0]])
    return orient.asMatrix() * parent


def _diagonal(m):
    """The diagonal of ``m``'s rotation part if it's a plain axis flip, else ``None``."""
    signs = []
    for i in range(3):
        for j in range(3):
            value = m.getElement(i, j)
            if i == j and abs(abs(value) - 1) > _TOLERANCE or i != j and abs(value) > _TOLERANCE:
                return None
        signs.append(1 if m.getElement(i, i) > 0 else -1)
    return signs


def _snapshot(node):
    """What mirroring needs from a source node, taken before anything changes."""
    return {
        "values": _keyable(node),
        "translate": cmds.getAttr(f"{node}.translate")[0],
        "rotate": cmds.getAttr(f"{node}.rotate")[0],
        "order": cmds.getAttr(f"{node}.rotateOrder"),
        "parent_frame": _parent_frame(node),
        "rotate_frame": _rotate_frame(node),
    }


def _mirrored_values(source, target):
    """``{attr: value}`` that puts ``target`` in the mirror image of the
    pose in ``source`` (a :func:`_snapshot`, maybe of the same node). The
    target's parent must already be where it'll stay."""
    values = dict(source["values"])

    # Row vectors, as in OpenMaya: a translate in the source's parent space,
    # to world, mirrored, to the target's parent space.
    flip_t = source["parent_frame"] * _MIRROR * _parent_frame(target).inverse()
    translate = om.MVector(source["translate"]) * flip_t

    # A rotation in the source's frame, mirrored in the world, in the
    # target's frame: K⁻¹ R K, with K the frame-to-frame flip.
    flip_r = source["rotate_frame"] * _MIRROR * _rotate_frame(target).inverse()
    target_order = cmds.getAttr(f"{target}.rotateOrder")
    signs = _diagonal(flip_r)
    if signs and source["order"] == target_order:
        # A plain axis flip: negate angles, keeping values past 180 as they are.
        rotate = [-sign * angle for sign, angle in zip(signs, source["rotate"])]
    else:
        radians = [om.MAngle(a, om.MAngle.kDegrees).asRadians() for a in source["rotate"]]
        matrix = flip_r.transpose() * om.MEulerRotation(radians, source["order"]).asMatrix() * flip_r
        euler = om.MTransformationMatrix(matrix).rotation().reorder(target_order)
        current = [om.MAngle(a, om.MAngle.kDegrees).asRadians() for a in cmds.getAttr(f"{target}.rotate")[0]]
        euler = euler.closestSolution(om.MEulerRotation(current, target_order))
        rotate = [om.MAngle(a).asDegrees() for a in (euler.x, euler.y, euler.z)]

    for attrs, vector in ((_TRANSLATE, translate), (_ROTATE, rotate)):
        for attr, value in zip(attrs, vector):
            if attr in values:
                values[attr] = value
    return values


def _apply_mirrored(jobs):
    """Pose each target of ``[(source snapshot, target)]`` as its source's
    mirror image, parents before children, so each target is solved
    against its parent's new pose; returns the skipped plugs."""
    skipped = []
    for source, target in sorted(jobs, key=lambda job: job[1].count("|")):
        skipped += _set_all([(target, _mirrored_values(source, target))])
    return skipped


def _sides(nodes):
    """``(pairs, skipped)``: ``(node, opposite)`` for each node, a centre
    node paired with itself, and messages for nodes whose opposite is missing."""
    pairs, skipped = [], []
    for node in dict.fromkeys(cmds.ls(nodes, long=True) or []):
        name = opposite_name(_short(node))
        if name is None:
            pairs.append((node, node))
            continue
        other = opposite(node)
        if other is None:
            count = len(cmds.ls(name))
            reason = f"several nodes are named {name}" if count > 1 else f"no {name} in the scene"
            skipped.append(f"{_short(node)}: {reason}")
        else:
            pairs.append((node, other))
    return pairs, skipped


@undoable
def mirror(nodes):
    """Pose each node's opposite as the mirror image of the node (a centre
    node: itself); returns a :data:`Result` of the nodes changed and what
    was skipped. Raises ``ValueError``, changing nothing, if a node and its
    opposite are both given: pick one side, or use :func:`flip`."""
    pairs, skipped = _sides(nodes)
    sources = [source for source, _ in pairs]
    both = [f"{_short(s)} and {_short(t)}" for s, t in pairs if s != t and t in sources[: sources.index(s)]]
    if both:
        raise ValueError(f"Both sides given: {', '.join(both)}. Pick the side to mirror from.")
    skipped += _apply_mirrored([(_snapshot(source), target) for source, target in pairs])
    return Result([target for _, target in pairs], skipped)


@undoable
def flip(nodes):
    """Swap the poses of each node and its opposite, each mirrored (a centre
    node is mirrored in place). Giving both sides of a pair flips it once."""
    pairs, skipped = _sides(nodes)
    seen, jobs = set(), []
    for source, target in pairs:
        if (source, target) in seen:
            continue
        seen.update({(source, target), (target, source)})
        jobs.append((_snapshot(source), target))
        if source != target:
            jobs.append((_snapshot(target), source))
    skipped += _apply_mirrored(jobs)
    return Result([target for _, target in jobs], skipped)


@undoable
def reset(nodes):
    """Set every keyable, unlocked attribute of ``nodes`` to its default;
    returns a :data:`Result` (attributes driven by a connection are skipped)."""
    changes = []
    for node in dict.fromkeys(cmds.ls(nodes, long=True) or []):
        defaults = {}
        for attr in _keyable(node):
            default = cmds.attributeQuery(attr, node=node, listDefault=True)
            if default:
                defaults[attr] = default[0]
        changes.append((node, defaults))
    return Result([node for node, _ in changes], _set_all(changes))
