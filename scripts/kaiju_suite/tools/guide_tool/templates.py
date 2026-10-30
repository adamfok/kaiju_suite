"""Guide templates: a whole body of guide chains, built at once. No Qt here.

A template is a list of chains, each one the settings :func:`logic.build_guides`
takes, placed on a body (Y up, facing +Z, left side at +X; about 180 cm for
the biped) so that each chain starts where the one it hangs off ends. The
left chains mirror, so the right side follows them live.
"""

from maya.api import OpenMaya as om

from kaiju_suite.core.undo import undoable
from kaiju_suite.tools.guide_tool import logic


def _placed(preset, start, end=None):
    """``preset``'s settings, moved to start at ``start`` (and end at
    ``end``, if given, else as far and the same way as the preset goes)."""
    chain = dict(logic.PRESETS[preset])
    way = om.MVector(chain["end"]) - om.MVector(chain["start"])
    chain["start"] = start
    chain["end"] = end if end is not None else tuple(om.MVector(start) + way)
    return chain


def _chain(name, count, start, end, up_side=(0, 1, 0)):
    """A left-side chain aiming +X with up +Y, with an end joint."""
    return {
        "name": name,
        "count": count,
        "start": start,
        "end": end,
        "aim": "x",
        "up": "y",
        "up_side": up_side,
        "end_joint": True,
        "mirror": name.startswith("l_"),
    }


_HAND = (70, 147, 0)
# Each finger's first knuckle, across the palm (index in front, at +Z), and its tip.
_KNUCKLES = {"index": (79, 147, 3), "middle": (79, 147, 1), "ring": (79, 147, -1), "pinky": (78, 147, -3)}
_TIPS = {"index": (89, 147, 3), "middle": (90, 147, 1), "ring": (89, 147, -1), "pinky": (86, 147, -3)}

TEMPLATES = {
    "biped": [
        _placed("root", (0, 0, 0)),
        _placed("spine", (0, 100, 0)),
        _placed("neck", (0, 145, 0)),
        _placed("head", (0, 160, 0)),
        _placed("l_shoulder", (3, 145, 0)),
        _placed("l_arm", (17, 147, 0)),
        _placed("l_hand", _HAND),
        # A metacarpal from the hand to each finger's first knuckle; the
        # thumb's first joint already sits where its metacarpal would.
        *(_chain(f"l_{finger}_metacarpal", 0, _HAND, knuckle) for finger, knuckle in _KNUCKLES.items()),
        _chain("l_thumb", 2, (72, 146, 3), (78, 144, 8)),
        *(_chain(f"l_{finger}", 2, _KNUCKLES[finger], _TIPS[finger]) for finger in _KNUCKLES),
        _placed("l_leg", (10, 95, 0)),
        _placed("l_foot", (10, 10, 0)),
    ],
}


@undoable
def build_template(name):
    """Build every chain of the template ``name`` (see :data:`TEMPLATES`) and
    return their guide groups, in order. Chains already built are built
    again in place, as :func:`logic.build_guides` does. Raises ``ValueError``,
    building nothing, if any chain can't be built."""
    if name not in TEMPLATES:
        raise ValueError(f"There's no {name!r} template; pick one of {', '.join(TEMPLATES)}.")
    chains = TEMPLATES[name]
    for chain in chains:
        logic.check_build(**chain)
    return [logic.build_guides(**chain) for chain in chains]
