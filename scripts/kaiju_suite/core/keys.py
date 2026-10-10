"""Keys on anim curves, read as data and their tangents set back. No Qt here.

Works on time-based curves (``animCurveT*``, keyed by time) and on driven
key curves (``animCurveU*``, keyed by the driver's value): pass
``driven=True`` for the second. Each key is a dict holding its input
(``"time"``, or ``"driverValue"`` for a driven key), value, tangent types,
angles and weights, tangent and weight locks, and for time keys the
breakdown flag (driven keys have none). Values are in the scene's current
units, as ``cmds.keyframe`` gives them.
"""

from maya import cmds

_TANGENTS = ("inTangentType", "outTangentType", "inAngle", "outAngle", "inWeight", "outWeight")
_LOCKS = ("lock", "weightLock")

# Infinity names, as cmds.setInfinity uses them, by the curves' enum value.
_INFINITY = {0: "constant", 1: "linear", 3: "cycle", 4: "cycleRelative", 5: "oscillate"}


def _input(driven):
    """The key dict's input field and the matching key-range flag."""
    return ("driverValue", "float") if driven else ("time", "time")


def read_keys(curve, driven=False):
    """Every key of ``curve`` (an anim curve, or a plug it's wired into), in order."""
    field, _flag = _input(driven)
    inputs = cmds.keyframe(curve, query=True, **{"floatChange" if driven else "timeChange": True}) or []
    values = cmds.keyframe(curve, query=True, valueChange=True) or []
    breakdowns = set() if driven else set(cmds.keyframe(curve, query=True, breakdown=True) or [])
    queried = {flag: cmds.keyTangent(curve, query=True, **{flag: True}) or [] for flag in _TANGENTS + _LOCKS}
    keys = []
    for i, (x, value) in enumerate(zip(inputs, values)):
        key = {field: x, "value": value}
        key.update((flag, queried[flag][i]) for flag in _TANGENTS)
        if not driven:
            key["breakdown"] = x in breakdowns
        key.update((flag, bool(queried[flag][i])) for flag in _LOCKS)
        keys.append(key)
    return keys


def set_tangents(target, keys, weighted, driven=False):
    """Give the keys already on ``target`` (a curve, or a plug it's wired
    into) the tangents saved in ``keys``, as :func:`read_keys` gives them,
    and switch ``weighted`` tangents on or off first (switching later would
    reset the weights). Time keys get their breakdown flags back too."""
    field, flag = _input(driven)
    cmds.keyTangent(target, edit=True, weightedTangents=weighted)
    for key in keys:
        at = {flag: (key[field], key[field])}
        # Unlocked, so the in and out sides can be set apart; locks go back after.
        cmds.keyTangent(target, edit=True, lock=False, **at)
        if weighted:
            cmds.keyTangent(target, edit=True, weightLock=False, **at)
            cmds.keyTangent(
                target,
                edit=True,
                inAngle=key["inAngle"],
                outAngle=key["outAngle"],
                inWeight=key["inWeight"],
                outWeight=key["outWeight"],
                **at,
            )
        else:
            cmds.keyTangent(target, edit=True, inAngle=key["inAngle"], outAngle=key["outAngle"], **at)
        cmds.keyTangent(
            target, edit=True, inTangentType=key["inTangentType"], outTangentType=key["outTangentType"], **at
        )
        cmds.keyTangent(target, edit=True, lock=key["lock"], **at)
        if weighted:
            cmds.keyTangent(target, edit=True, weightLock=key["weightLock"], **at)
        if key.get("breakdown"):
            cmds.keyframe(target, edit=True, breakdown=True, **at)


def infinity(curve):
    """``(pre, post)`` infinity of the anim curve node ``curve``, e.g. ``("constant", "cycle")``.

    Read from the curve's attributes: ``cmds.setInfinity`` only answers
    through a plug the curve is wired straight into.
    """
    return tuple(_INFINITY[cmds.getAttr(f"{curve}.{side}Infinity")] for side in ("pre", "post"))


def set_infinity(curve, pre, post):
    """Set the anim curve node ``curve``'s infinity, by name (see :func:`infinity`)."""
    values = {name: value for value, name in _INFINITY.items()}
    cmds.setAttr(f"{curve}.preInfinity", values[pre])
    cmds.setAttr(f"{curve}.postInfinity", values[post])
