"""Animation Tool: mirror and flip animation across sides. No Qt here.

Sides and the mirroring math are shared with the Pose Tool, in
:mod:`kaiju_suite.core.mirror`: opposites are found by name, a control with
no side mirrors onto itself, and values are mirrored across X from each
control's parent and joint orient, exactly as the Pose Tool mirrors a pose.

Keys are the time-based anim curves (``animCurveTL/TA/TU/TT``) wired straight
into a control's keyable attributes. Mirroring an attribute replaces the
destination's keys with a copy of the source's curve, moved by the frame
offset: key times, tangents, weights and infinity all stay the same, and
values (with tangent slopes) are multiplied by -1 where the channel flips.
If the source attribute has no keys but the destination has, those keys are
removed and the destination gets the source's mirrored value.

Where the two sides' frames aren't a plain axis flip of each other (e.g.
rotated parents that aren't a clean mirror, or different rotate orders),
translate or rotate channels mix, so instead that group is baked: the
mirrored values are worked out and keyed (with Maya's default tangents) at
each source key time and on every whole frame between the first and last.

Destination attributes that are missing, locked or driven by a connection
other than their own keys are skipped and reported.
"""

import math
from collections import namedtuple

from maya import cmds

from kaiju_suite.core import mirror as mirroring
from kaiju_suite.core.undo import undoable

Result = namedtuple("Result", "changed skipped")

CURVE_TYPES = ("animCurveTL", "animCurveTA", "animCurveTU", "animCurveTT")


def _curves(node):
    """``{attr: curve}`` for the time-based anim curves wired straight into ``node``."""
    found = cmds.listConnections(
        node, source=True, destination=False, connections=True, plugs=True, skipConversionNodes=False
    ) or []
    curves = {}
    for destination, source in zip(found[::2], found[1::2]):
        attr = destination.split(".", 1)[1]
        curve = source.split(".", 1)[0]
        if "." not in attr and "[" not in attr and cmds.nodeType(curve) in CURVE_TYPES:
            curves[cmds.attributeQuery(attr, node=node, longName=True)] = curve
    return curves


def _snapshot(node, time):
    """What mirroring needs from a source node, taken before anything changes.
    Its curves are copied, so changing the node later doesn't change them."""
    curves = {}
    values = mirroring.keyable(node)
    for attr, curve in _curves(node).items():
        if attr in values:
            curves[attr] = cmds.duplicate(curve, name=f"kaijuMirror_{curve}")[0]
    return {"node": node, "values": values, "curves": curves, "frames": mirroring.frames(node, time)}


def _value(source, attr, time):
    """The source's ``attr`` at ``time``, from its copied curve or its value."""
    curve = source["curves"].get(attr)
    if curve is None:
        return source["values"][attr]
    return cmds.keyframe(curve, query=True, eval=True, time=(time, time))[0]


def _clear(target, attr):
    """Remove ``target.attr``'s keys; ``True`` if it had any."""
    curve = _curves(target).get(attr)
    if curve:
        cmds.delete(curve)
    return bool(curve)


def _copy_curve(source, attr, target, sign, offset):
    """Wire the source's copied curve for ``attr`` into ``target.attr``,
    moved by ``offset`` frames and with values times ``sign``."""
    curve = source["curves"].pop(attr)
    if offset:
        cmds.keyframe(curve, edit=True, relative=True, timeChange=offset, option="over")
    if sign < 0:
        cmds.scaleKey(curve, valueScale=-1, valuePivot=0)
    curve = cmds.rename(curve, f"{mirroring.short(target)}_{attr}")
    cmds.connectAttr(f"{curve}.output", f"{target}.{attr}", force=True)


def _bake_group(source, attrs, target, solve, offset):
    """Key ``target``'s ``attrs`` (one translate or rotate group, already
    cleared) at each source key time, with ``solve(vector, near)`` giving the
    mirrored vector; or set them once if the source has no keys there."""
    keys = {t for attr in attrs if attr in source["curves"]
            for t in cmds.keyframe(source["curves"][attr], query=True, timeChange=True) or []}
    # Mixed channels don't interpolate like the source, so key every frame
    # between the first and last key too.
    whole = range(math.ceil(min(keys)), math.floor(max(keys)) + 1) if keys else []
    times = sorted(keys.union(whole))
    near = cmds.getAttr(f"{target}.{attrs[0][:-1]}")[0]
    for time in times or [None]:
        vector = solve([_value(source, attr, time) for attr in attrs], near)
        near = vector
        for attr, value in zip(attrs, vector):
            if time is None:
                cmds.setAttr(f"{target}.{attr}", value)
            else:
                cmds.setKeyframe(target, attribute=attr, time=time + offset, value=value)


def _apply(source, target, offset, time):
    """Replace ``target``'s animation with the mirror image of ``source``'s
    (a :func:`_snapshot`); returns the skipped plugs."""
    skipped, usable = [], []
    for attr in source["values"]:
        reason = mirroring.skip_reason(target, attr)
        if reason is None:
            usable.append(attr)
        elif attr in source["curves"] or (reason != "missing" and attr in _curves(target)):
            skipped.append(f"{mirroring.short(target)}.{attr} ({reason})")

    frames = mirroring.frames(target, time + offset)
    signs_t, signs_r = mirroring.channel_signs(source["frames"], frames)
    groups = (
        (mirroring.TRANSLATE, signs_t, lambda v, near: mirroring.mirror_translate(v, source["frames"], frames)),
        (mirroring.ROTATE, signs_r, lambda v, near: mirroring.mirror_rotate(v, source["frames"], frames, near)),
    )
    signs = {}
    for attrs, group_signs, solve in groups:
        if group_signs:
            signs.update(group_signs)
        elif all(attr in usable for attr in attrs):
            had_keys = [_clear(target, attr) for attr in attrs]
            if any(had_keys) or any(attr in source["curves"] for attr in attrs):
                _bake_group(source, attrs, target, solve, offset)
        else:
            # Channels mix, so one skipped channel spoils the rest of the group.
            for attr in attrs:
                if attr in usable:
                    usable.remove(attr)
                    if attr in source["curves"]:
                        skipped.append(f"{mirroring.short(target)}.{attr} (its group has a skipped channel)")

    for attr in usable:
        if attr in (mirroring.TRANSLATE + mirroring.ROTATE) and attr not in signs:
            continue  # baked above
        sign = signs.get(attr, 1)
        had_keys = _clear(target, attr)
        if attr in source["curves"]:
            _copy_curve(source, attr, target, sign, offset)
        elif had_keys:
            value = source["values"][attr]
            cmds.setAttr(f"{target}.{attr}", value * sign if not isinstance(value, bool) else value)
    return skipped


def _run(jobs, offset):
    """Apply ``[(source snapshot, target)]``, parents before children, so each
    target's frame is read once its parent has its new animation; then delete
    the copied curves that weren't used."""
    skipped = []
    time = cmds.currentTime(query=True)
    try:
        for source, target in sorted(jobs, key=lambda job: job[1].count("|")):
            skipped += _apply(source, target, offset, time)
    finally:
        leftovers = [c for source, _ in jobs for c in source["curves"].values() if cmds.objExists(c)]
        if leftovers:
            cmds.delete(leftovers)
    return skipped


@undoable
def mirror(nodes, offset=0):
    """Give each node's opposite (a centre node: itself) the mirror image of
    the node's animation, ``offset`` frames later; returns a :data:`Result`
    of the nodes changed and what was skipped. Raises ``ValueError``,
    changing nothing, if a node and its opposite are both given: pick one
    side, or use :func:`flip`."""
    pairs, skipped = mirroring.sides(nodes)
    both = mirroring.both_sides(pairs)
    if both:
        raise ValueError(f"Both sides given: {', '.join(both)}. Pick the side to mirror from.")
    time = cmds.currentTime(query=True)
    jobs = [(_snapshot(source, time), target) for source, target in pairs]
    skipped += _run(jobs, offset)
    return Result([target for _, target in pairs], skipped)


@undoable
def flip(nodes, offset=0):
    """Swap the animation of each node and its opposite, each mirrored and
    moved ``offset`` frames (a centre node is mirrored in place). Giving
    both sides of a pair flips it once."""
    pairs, skipped = mirroring.sides(nodes)
    time = cmds.currentTime(query=True)
    seen, jobs = set(), []
    for source, target in pairs:
        if (source, target) in seen:
            continue
        seen.update({(source, target), (target, source)})
        jobs.append((_snapshot(source, time), target))
        if source != target:
            jobs.append((_snapshot(target, time), source))
    skipped += _run(jobs, offset)
    return Result([target for _, target in jobs], skipped)
