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

import re

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
# chain's start and end guides go on, which joints its middle guides go on
# when the chain has that many (``mids``; otherwise they spread evenly), and
# whether its up guide goes where those joints bend (``bend``, like a pole
# vector; otherwise it stays on the side it's on). An end is a joint name,
# ``_extend(a, b)`` (past ``b``, along ``a`` -> ``b``) or ``None`` (keep the
# chain's own way and length), or a list of those tried in order, for joints
# a skeleton may not have. Joints are found by name, without namespaces, or
# for HumanIK by the character slot they're assigned to.


def _extend(a, b, scale=0.8, flat=False):
    """Past joint ``b``, ``scale`` times as far as ``a`` -> ``b``, the same way
    (``flat``: level, along the ground)."""
    return {"extend": (a, b), "scale": scale, "flat": flat}


def _anchors(start, end=None, mids=(), bend=False):
    return {"start": start, "end": end if isinstance(end, list) else [end], "mids": list(mids), "bend": bend}


def _ue5_finger(finger):
    joints = [f"{finger}_{i:02d}_l" for i in (1, 2, 3)]
    return _anchors(joints[0], _extend(joints[1], joints[2]), joints[1:], bend=True)


def _hik_finger(finger):
    joints = [f"LeftHand{finger}{i}" for i in (1, 2, 3, 4)]
    return _anchors(joints[0], [joints[3], _extend(joints[1], joints[2])], joints[1:3], bend=True)


def _hik_chains(root=None):
    """The chains for HumanIK slot names, which Mixamo uses for its joints too."""
    fingers = ("Index", "Middle", "Ring", "Pinky")
    chains = {
        "spine": _anchors("Hips", "Neck"),
        "neck": _anchors("Neck", "Head", ["Neck1"]),
        "head": _anchors("Head", ["HeadTop_End", None]),
        "l_shoulder": _anchors("LeftShoulder", "LeftArm"),
        "l_arm": _anchors("LeftArm", "LeftHand", ["LeftForeArm"], bend=True),
        "l_hand": _anchors("LeftHand", "LeftHandMiddle1"),
        **{f"l_{f.lower()}_metacarpal": _anchors("LeftHand", f"LeftHand{f}1") for f in fingers},
        "l_thumb": _hik_finger("Thumb"),
        **{f"l_{f.lower()}": _hik_finger(f) for f in fingers},
        "l_leg": _anchors("LeftUpLeg", "LeftFoot", ["LeftLeg"], bend=True),
        "l_foot": _anchors(
            "LeftFoot", ["LeftToe_End", _extend("LeftFoot", "LeftToeBase", 0.6, flat=True)], ["LeftToeBase"]
        ),
    }
    if root:
        chains["root"] = _anchors(root)
    return chains


SKELETONS = {
    # MetaHuman bodies use the UE5 Mannequin's joint names.
    "ue5": {
        "label": "UE5 Mannequin / MetaHuman",
        "find": "names",
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
    # Joints assigned to a HumanIK character, whatever they're called. Before
    # Mixamo, so a characterized Mixamo skeleton goes by its character.
    "humanik": {"label": "HumanIK", "find": "humanik", "chains": _hik_chains(root="Reference")},
    # Mixamo names its joints after the HumanIK slots, in a mixamorig
    # namespace or with a mixamorig_ prefix; it has no root joint.
    "mixamo": {"label": "Mixamo", "find": "names", "chains": _hik_chains()},
}

# A prefix Mixamo puts on its joint names when they aren't in a namespace.
_MIXAMO_PREFIX = re.compile(r"^mixamorig\d*_")


def _hierarchy(nodes):
    """The joints in the hierarchy of the first of ``nodes``, top first."""
    found = cmds.ls(nodes, long=True) if nodes else []
    if not found:
        raise ValueError("Select a joint of the skeleton to align to.")
    top = "|" + found[0].split("|")[1]
    joints = cmds.ls(top, type="joint", long=True) or []
    joints += cmds.listRelatives(top, allDescendents=True, type="joint", fullPath=True) or []
    return sorted(joints, key=lambda j: j.count("|"))


def _by_name(joints):
    """``joints`` by their names without namespaces or a Mixamo prefix (the
    first one found, if a name is there twice)."""
    named = {}
    for joint in joints:
        name = joint.rsplit("|", 1)[-1].rsplit(":", 1)[-1]
        named.setdefault(name, joint)
        named.setdefault(_MIXAMO_PREFIX.sub("", name), joint)
    return named


def _by_humanik_slot(joints):
    """``joints`` by the HumanIK character slot they're assigned to, for the
    character most of them belong to."""
    characters = {}
    for joint in joints:
        if not cmds.attributeQuery("Character", node=joint, exists=True):
            continue
        for plug in cmds.listConnections(f"{joint}.Character", source=False, plugs=True) or []:
            character, slot = plug.split(".", 1)
            if cmds.nodeType(character) == "HIKCharacterNode":
                characters.setdefault(character, {}).setdefault(slot, joint)
    return max(characters.values(), key=len) if characters else {}


def _joints(skeleton, hierarchy):
    finder = _by_humanik_slot if SKELETONS[skeleton]["find"] == "humanik" else _by_name
    return finder(hierarchy)


def _ends_needs(end):
    if isinstance(end, str):
        return [end]
    if isinstance(end, dict):
        return list(end["extend"])
    return []


def _missing(spec, named):
    """The joints ``spec`` can't do without that aren't in ``named``, each
    once: its start, its middle joints if it bends, and, if no end option
    can be placed, what its first one needs."""
    names = [spec["start"], *(spec["mids"] if spec["bend"] else [])]
    if not any(all(n in named for n in _ends_needs(end)) for end in spec["end"]):
        names += _ends_needs(spec["end"][0])
    return [n for n in dict.fromkeys(names) if n not in named]


def _every_joint(spec):
    names = [spec["start"], *spec["mids"]]
    for end in spec["end"]:
        names += _ends_needs(end)
    return set(names)


def detect(nodes):
    """The key of the skeleton in :data:`SKELETONS` the hierarchy of ``nodes``
    matches best; ``ValueError`` if it matches none."""
    hierarchy = _hierarchy(nodes)
    scores = {}
    for key, skeleton in SKELETONS.items():
        wanted = set().union(*(_every_joint(spec) for spec in skeleton["chains"].values()))
        scores[key] = len(wanted & set(_joints(key, hierarchy)))
    best = max(scores, key=scores.get)
    if not scores[best]:
        raise ValueError("The selected hierarchy doesn't look like any skeleton the Guide Tool knows.")
    return best


def _world(node):
    return om.MVector(cmds.xform(node, query=True, worldSpace=True, translation=True))


def _move(node, position):
    cmds.xform(node, worldSpace=True, translation=(position.x, position.y, position.z))


def _end(spec, start, named, chain):
    """Where ``chain``'s end guide goes: its first end the skeleton has the
    joints for, or ``None`` if none."""
    for end in spec["end"]:
        if not all(n in named for n in _ends_needs(end)):
            continue
        if isinstance(end, str):
            return _world(named[end])
        if end is None:
            return start + (_world(chain[-1]) - _world(chain[0]))
        a, b = (_world(named[n]) for n in end["extend"])
        way = b - a
        if end["flat"]:
            way = om.MVector(way.x, 0, way.z)
        return b + way.normal() * ((b - a).length() * end["scale"])
    return None


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
    hierarchy = _hierarchy(nodes)
    skeleton = skeleton or detect(nodes)
    named = _joints(skeleton, hierarchy)
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
        missing = _missing(spec, named)
        if missing:
            skipped.append((name, f"missing {', '.join(missing)}"))
            continue
        found = logic.guides(f"{name}_guides_grp")
        guided = found["chain"]
        start = _world(named[spec["start"]])
        end = _end(spec, start, named, guided)
        middles = guided[1:-1]
        mid_anchors = [_world(named[n]) for n in spec["mids"] if n in named]
        if spec["mids"] and len(mid_anchors) == len(spec["mids"]) == len(middles):
            mids = mid_anchors
        else:
            mids = [start + (end - start) * (i / (len(middles) + 1.0)) for i in range(1, len(middles) + 1)]
        old = (_world(guided[0]), _world(guided[-1]), _world(found["up"]))
        up = _up(spec, start, end, mid_anchors, old, chain["up_side"])
        for guide, position in zip(guided, [start, *mids, end]):
            _move(guide, position)
        _move(found["up"], up)
        aligned.append(name)
    return {"skeleton": skeleton, "aligned": aligned, "skipped": skipped}
