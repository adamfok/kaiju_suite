"""Guide templates: a whole body of guide chains, built at once. No Qt here.

A template is a list of chains, each one the settings :func:`logic.build_guides`
takes, placed on a body (Y up, facing +Z, left side at +X; about 180 cm for
the biped) so that each chain starts where the one it hangs off ends. The
left chains mirror, so the right side follows them live.

:func:`align` then moves a built template's guides onto another skeleton
(see :data:`SKELETONS`): each chain's ends on two of its joints, not joint
for joint, so the template keeps its own joints and takes that skeleton's
proportions.
"""

from maya import cmds
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


# -- aligning to other skeletons --------------------------------------------------
#
# Each skeleton's table says, per template chain, which of its joints the
# chain's start and end guides go on (``end``: a joint; ``_extend(a, b)``:
# past ``b`` along ``a`` -> ``b``, for a skeleton with no joint there; or
# ``None``: keep the way and length the chain has), which joints its middle
# guides go on when the chain has that many (``mids``; otherwise they spread
# evenly), and whether its up guide goes where those joints bend (``bend``,
# like a pole vector; otherwise it stays on the side it's on).


def _extend(a, b, scale=0.8, flat=False):
    """Past joint ``b``, ``scale`` times as far as ``a`` -> ``b``, the same way
    (``flat``: level, along the ground)."""
    return {"extend": (a, b), "scale": scale, "flat": flat}


def _anchors(start, end=None, mids=(), bend=False):
    return {"start": start, "end": end, "mids": list(mids), "bend": bend}


def _ue5_finger(finger):
    joints = [f"{finger}_{i:02d}_l" for i in (1, 2, 3)]
    return _anchors(joints[0], _extend(joints[1], joints[2]), joints[1:], bend=True)


SKELETONS = {
    # MetaHuman bodies use the UE5 Mannequin's joint names.
    "ue5": {
        "label": "UE5 Mannequin / MetaHuman",
        "chains": {
            "root": _anchors("root"),
            "spine": _anchors("pelvis", "neck_01"),
            "neck": _anchors("neck_01", "head", ["neck_02"]),
            "head": _anchors("head"),
            "l_shoulder": _anchors("clavicle_l", "upperarm_l"),
            "l_arm": _anchors("upperarm_l", "hand_l", ["lowerarm_l"], bend=True),
            "l_hand": _anchors("hand_l", "middle_01_l"),
            **{
                f"l_{finger}_metacarpal": _anchors("hand_l", f"{finger}_01_l")
                for finger in ("index", "middle", "ring", "pinky")
            },
            "l_thumb": _ue5_finger("thumb"),
            **{f"l_{finger}": _ue5_finger(finger) for finger in ("index", "middle", "ring", "pinky")},
            "l_leg": _anchors("thigh_l", "foot_l", ["calf_l"], bend=True),
            "l_foot": _anchors("foot_l", _extend("foot_l", "ball_l", 0.6, flat=True), ["ball_l"]),
        },
    },
}


def _named_joints(nodes):
    """The joints in the hierarchy of the first of ``nodes``, by their names
    without namespaces (the first one found, if a name is there twice)."""
    found = cmds.ls(nodes, long=True) if nodes else []
    if not found:
        raise ValueError("Select a joint of the skeleton to align to.")
    top = "|" + found[0].split("|")[1]
    joints = cmds.ls(top, type="joint", long=True) or []
    joints += cmds.listRelatives(top, allDescendents=True, type="joint", fullPath=True) or []
    named = {}
    for joint in sorted(joints, key=lambda j: j.count("|")):
        named.setdefault(joint.rsplit("|", 1)[-1].rsplit(":", 1)[-1], joint)
    return named


def _needs(spec):
    """The joints ``spec`` uses, each once, in order."""
    names = [spec["start"], *spec["mids"]]
    if isinstance(spec["end"], str):
        names.append(spec["end"])
    elif isinstance(spec["end"], dict):
        names += list(spec["end"]["extend"])
    return list(dict.fromkeys(names))


def detect(nodes):
    """The key of the skeleton in :data:`SKELETONS` the hierarchy of ``nodes``
    matches best; ``ValueError`` if it matches none."""
    named = _named_joints(nodes)
    scores = {
        key: len({n for spec in skeleton["chains"].values() for n in _needs(spec)} & set(named))
        for key, skeleton in SKELETONS.items()
    }
    best = max(scores, key=scores.get)
    if not scores[best]:
        raise ValueError("The selected hierarchy doesn't look like any skeleton the Guide Tool knows.")
    return best


def _world(node):
    return om.MVector(cmds.xform(node, query=True, worldSpace=True, translation=True))


def _move(node, position):
    cmds.xform(node, worldSpace=True, translation=(position.x, position.y, position.z))


def _end(spec, start, at, chain):
    """Where ``chain``'s end guide goes for ``spec``'s end."""
    end = spec["end"]
    if isinstance(end, str):
        return at(end)
    if end is None:
        return start + (_world(chain[-1]) - _world(chain[0]))
    a, b = (at(n) for n in end["extend"])
    way = b - a
    if end["flat"]:
        way = om.MVector(way.x, 0, way.z)
    return b + way.normal() * ((b - a).length() * end["scale"])


def _up(spec, start, end, mids, old, up_side):
    """Where the up guide goes: to the side the middle joints bend to, for a
    ``bend`` chain bent enough; else on the side it was on (``old``: the
    start, end and up guides' old positions), or ``up_side``."""
    span = end - start
    length = span.length()

    def across(vector):
        side = vector - span * ((vector * span) / (length * length))
        return side if side.length() > length * 1e-3 else None

    side = None
    if spec["bend"] and mids:
        bend = sum(mids, om.MVector()) / len(mids)
        side = across(bend - start)
    if side is None:
        old_start, old_end, old_up = old
        old_span = old_end - old_start
        was = old_up - old_start
        side = across(was - old_span * ((was * old_span) / (old_span * old_span)))
    if side is None:
        side = across(om.MVector(up_side))
    if side is None:
        side = across(om.MVector(0, 1, 0)) or across(om.MVector(0, 0, 1))
    return start + span * 0.5 + side.normal() * (length * 0.5)


@undoable
def align(template, nodes, skeleton=None):
    """Move the guides of ``template``'s built chains onto the skeleton the
    first of ``nodes`` is in (``skeleton``: a key of :data:`SKELETONS`, or
    found by :func:`detect`). Chains that aren't built, or whose joints
    aren't there, are skipped. Returns ``{"skeleton", "aligned", "skipped"}``,
    ``skipped`` holding (chain, why) pairs. Raises ``ValueError``, changing
    nothing, if none of the template is built."""
    if template not in TEMPLATES:
        raise ValueError(f"There's no {template!r} template; pick one of {', '.join(TEMPLATES)}.")
    named = _named_joints(nodes)
    skeleton = skeleton or detect(nodes)
    table = SKELETONS[skeleton]["chains"]
    chains = TEMPLATES[template]
    if not any(cmds.objExists(f"{c['name']}_guides_grp") for c in chains):
        raise ValueError(f"Build the {template} template first, then align it.")
    aligned, skipped = [], []
    for chain in chains:
        name = chain["name"]
        if not cmds.objExists(f"{name}_guides_grp"):
            skipped.append((name, "not built"))
            continue
        spec = table.get(name)
        if spec is None:
            skipped.append((name, f"no joints for it in {SKELETONS[skeleton]['label']}"))
            continue
        missing = [n for n in _needs(spec) if n not in named]
        if missing:
            skipped.append((name, f"missing {', '.join(missing)}"))
            continue
        found = logic.guides(f"{name}_guides_grp")
        guided = found["chain"]

        def at(joint):
            return _world(named[joint])

        old = (_world(guided[0]), _world(guided[-1]), _world(found["up"]))
        start = at(spec["start"])
        end = _end(spec, start, at, guided)
        middles = guided[1:-1]
        mid_anchors = [at(n) for n in spec["mids"]]
        if len(mid_anchors) == len(middles):
            mids = mid_anchors
        else:
            mids = [start + (end - start) * (i / (len(middles) + 1.0)) for i in range(1, len(middles) + 1)]
        up = _up(spec, start, end, mid_anchors, old, chain["up_side"])
        for guide, position in zip(guided, [start, *mids, end]):
            _move(guide, position)
        _move(found["up"], up)
        aligned.append(name)
    return {"skeleton": skeleton, "aligned": aligned, "skipped": skipped}
