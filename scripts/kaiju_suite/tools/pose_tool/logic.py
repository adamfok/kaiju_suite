"""Pose Tool: mirror, flip and reset poses. No Qt here.

Sides and the mirroring math are in :mod:`kaiju_suite.core.mirror` (across
X; a node with no side mirrors onto itself). Scale and every other keyable
attribute are copied as they are.

Only keyable, unlocked attributes of the source are copied; on the target,
attributes that are missing, locked or driven by a connection other than
their own keys are skipped and reported.
"""

from collections import namedtuple

from maya import cmds

from kaiju_suite.core import mirror as mirroring
from kaiju_suite.core.mirror import opposite, opposites  # noqa: F401  (part of this tool's API)
from kaiju_suite.core.undo import undoable

Result = namedtuple("Result", "changed skipped")

_short = mirroring.short
_keyable = mirroring.keyable


def _set_all(changes):
    """Set ``[(node, {attr: value})]``; returns the plugs skipped, with why."""
    skipped = []
    for node, values in changes:
        for attr, value in values.items():
            reason = mirroring.skip_reason(node, attr)
            if reason:
                skipped.append(f"{_short(node)}.{attr} ({reason})")
            else:
                cmds.setAttr(f"{node}.{attr}", value)
    return skipped


# -- mirroring --------------------------------------------------------------


def _snapshot(node):
    """What mirroring needs from a source node, taken before anything changes."""
    return {
        "values": _keyable(node),
        "translate": cmds.getAttr(f"{node}.translate")[0],
        "rotate": cmds.getAttr(f"{node}.rotate")[0],
        "frames": mirroring.frames(node),
    }


def _mirrored_values(source, target):
    """``{attr: value}`` that puts ``target`` in the mirror image of the
    pose in ``source`` (a :func:`_snapshot`, maybe of the same node). The
    target's parent must already be where it'll stay."""
    values = dict(source["values"])
    frames = mirroring.frames(target)
    translate = mirroring.mirror_translate(source["translate"], source["frames"], frames)
    near = cmds.getAttr(f"{target}.rotate")[0]
    rotate = mirroring.mirror_rotate(source["rotate"], source["frames"], frames, near)
    for attrs, vector in ((mirroring.TRANSLATE, translate), (mirroring.ROTATE, rotate)):
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


@undoable
def mirror(nodes):
    """Pose each node's opposite as the mirror image of the node (a centre
    node: itself); returns a :data:`Result` of the nodes changed and what
    was skipped. Raises ``ValueError``, changing nothing, if a node and its
    opposite are both given: pick one side, or use :func:`flip`."""
    pairs, skipped = mirroring.sides(nodes)
    both = mirroring.both_sides(pairs)
    if both:
        raise ValueError(f"Both sides given: {', '.join(both)}. Pick the side to mirror from.")
    skipped += _apply_mirrored([(_snapshot(source), target) for source, target in pairs])
    return Result([target for _, target in pairs], skipped)


@undoable
def flip(nodes):
    """Swap the poses of each node and its opposite, each mirrored (a centre
    node is mirrored in place). Giving both sides of a pair flips it once."""
    pairs, skipped = mirroring.sides(nodes)
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
