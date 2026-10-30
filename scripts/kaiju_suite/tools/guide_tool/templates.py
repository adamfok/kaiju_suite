"""Guide templates: a whole body of guide chains, built at once. No Qt here.

A template is a list of chains, each one the settings :func:`logic.build_guides`
takes, placed on a body (Y up, facing +Z, left side at +X; about 180 cm for
the biped, 100 cm at the withers for the quadruped) so that each chain starts where the one it hangs off ends. The
left chains mirror, so the right side follows them live.

:func:`align` then moves a built template's guides onto another skeleton
(see :data:`SKELETONS`): each chain's ends on two of its joints, not joint
for joint, so the template keeps its own joints and takes that skeleton's
proportions.
"""

import re

from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.core import hierarchy
from kaiju_suite.core.naming import mirrored_name
from kaiju_suite.core.selection import short_name
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
        _placed("pelvis", (0, 100, 0)),
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
    # About 100 cm at the withers, the spine level from the hips forward.
    "quadruped": [
        _placed("root", (0, 0, 0)),
        # One joint at the hips, aiming forward along the spine, aligned with the world like root.
        {**_placed("root", (0, 100, -45), (0, 100, -35)), "name": "pelvis"},
        # Aims +Y forward with -Z up: the biped spine's axes, tipped forward.
        {**_placed("forward_spine", (0, 100, -45), (0, 100, 45)), "name": "spine", "aim": "y", "up": "-z"},
        _placed("neck", (0, 100, 45), (0, 125, 70)),
        _placed("head", (0, 125, 70)),
        _placed("tail", (0, 100, -45)),
        _placed("l_scapula", (7, 112, 37)),
        _placed("l_front_leg", (10, 92, 45), (10, 0, 45)),
        _placed("l_quad_leg", (10, 95, -40)),
    ],
}


# Which chain each chain hangs off: it goes under that chain's end joint, or its last
# joint if it has none. Build saves it as each chain's first joint's default parent (see
# kaiju_suite.core.hierarchy), the right side's under the right side's chain, and
# Delete parents the joints there.
PARENTS = {
    "biped": {
        "pelvis": "root",
        "spine": "pelvis",
        "neck": "spine",
        "head": "neck",
        "l_shoulder": "spine",
        "l_arm": "l_shoulder",
        "l_hand": "l_arm",
        **{f"l_{finger}_metacarpal": "l_hand" for finger in _KNUCKLES},
        "l_thumb": "l_hand",
        **{f"l_{finger}": f"l_{finger}_metacarpal" for finger in _KNUCKLES},
        "l_leg": "pelvis",
        "l_foot": "l_leg",
    },
    "quadruped": {
        "pelvis": "root",
        "spine": "pelvis",
        "neck": "spine",
        "head": "neck",
        "tail": "pelvis",
        "l_scapula": "spine",
        "l_front_leg": "l_scapula",
        "l_quad_leg": "pelvis",
    },
}


@undoable
def build_template(name):
    """Build every chain of the template ``name`` (see :data:`TEMPLATES`) and
    return their guide groups, in order. Chains already built are built
    again in place, as :func:`logic.build_guides` does. Chains Delete cut
    loose (even parented into a skeleton) get their guides back on those same
    joints, where they are: they and their mirrors go back to the world first,
    since guides need that. Each chain's first joint (and its mirror's) gets
    its default parent (see :data:`PARENTS`); nothing is parented yet.
    Raises ``ValueError``, building nothing, if any new chain can't be built."""
    if name not in TEMPLATES:
        raise ValueError(f"There's no {name!r} template; pick one of {', '.join(TEMPLATES)}.")
    chains = TEMPLATES[name]
    built = set(_built(name))
    loose = {}
    for chain in chains:
        top = None if f"{chain['name']}_guides_grp" in built else logic.loose_chain(chain["name"])
        if top:
            loose[chain["name"]] = top
        else:
            logic.check_build(**chain)

    # Unparent every loose chain before picking any up, so each one is on its own again.
    tops = []
    for chain in chains:
        top = loose.get(chain["name"])
        if top:
            mirror = cmds.ls(mirrored_name(short_name(top)), long=True, type="joint") if chain["mirror"] else []
            tops += cmds.ls([top, *mirror[:1]], uuid=True)
    for uuid in tops:
        top = cmds.ls(uuid, long=True)[0]
        if cmds.listRelatives(top, parent=True):
            cmds.parent(top, world=True)

    groups = []
    for chain in chains:
        if chain["name"] in loose:
            top = logic.loose_chain(chain["name"])
            groups.append(logic.guides_from_joints(top, mirror=chain["mirror"]))
        else:
            groups.append(logic.build_guides(**chain))

    built = {chain["name"]: (chain, group) for chain, group in zip(chains, groups)}
    for child, parent in PARENTS[name].items():
        (chain, group), (parent_chain, parent_group) = built[child], built[parent]
        hierarchy.set_default_parent(logic.joints(group)[0], logic.joints(parent_group)[-1])  # its end joint
        if chain["mirror"]:
            mirrored_parent = logic.mirrored_joints(parent_group) if parent_chain["mirror"] else logic.joints(parent_group)
            hierarchy.set_default_parent(logic.mirrored_joints(group)[0], mirrored_parent[-1])
    return groups


def _built(name):
    """The guide groups of the template ``name``'s chains that are built, in order."""
    if name not in TEMPLATES:
        raise ValueError(f"There's no {name!r} template; pick one of {', '.join(TEMPLATES)}.")
    groups = [f"{chain['name']}_guides_grp" for chain in TEMPLATES[name]]
    return [g for g in groups if cmds.objExists(g) and cmds.attributeQuery("kaijuGuides", node=g, exists=True)]


@undoable
def delete_template(name):
    """Delete the guides of every built chain of the template ``name``, as
    :func:`logic.delete_guides` does, then parent each chain's joints (and
    its mirror's) under their default parent (see :data:`PARENTS`), keeping
    them where they are; a chain whose parent is gone stays at the world.
    Returns the joints, chain by chain. Raises ``ValueError``, changing
    nothing, if none of it is built."""
    groups = _built(name)
    if not groups:
        raise ValueError(f"None of the {name} template is built.")
    tops = []
    for group in groups:
        tops += [logic.joints(group)[0], *logic.mirrored_joints(group)[:1]]
    tops = cmds.ls(tops, uuid=True)
    joints = cmds.ls([joint for group in groups for joint in logic.delete_guides(group)], uuid=True)

    tops = [cmds.ls(uuid, long=True)[0] for uuid in tops]
    if any(hierarchy.has_default_parent(top) for top in tops):
        hierarchy.reparent(tops, skip_missing=True)
    return [cmds.ls(uuid, long=True)[0] for uuid in joints]


# -- aligning to other skeletons --------------------------------------------------
#
# Each skeleton fits one template, and its table says, per chain of that
# template, which of its joints the
# chain's start and end guides go on, which joints its middle guides go on
# when the chain has that many (``mids``; otherwise they spread evenly), and
# whether its up guide goes where those joints bend (``bend``, like a pole
# vector, or ``"first"``: where the first of them bends, for legs whose
# joints bend both ways; otherwise it stays on the side it's on). An end is a
# joint name, ``_extend(a, b)`` (past ``b``, along ``a`` -> ``b``) or ``None`` (keep the
# chain's own way and length), or a list of those tried in order, for joints
# a skeleton may not have. Joints are found by name, without namespaces, or
# for HumanIK by the character slot they're assigned to.


def _extend(a, b, scale=0.8, flat=False):
    """Past joint ``b``, ``scale`` times as far as ``a`` -> ``b``, the same way
    (``flat``: level, along the ground; forward, +Z, if that way is straight
    down)."""
    return {"extend": (a, b), "scale": scale, "flat": flat}


def _anchors(start, end=None, mids=(), bend=False):
    return {"start": start, "end": end if isinstance(end, list) else [end], "mids": list(mids), "bend": bend}


def _ue5_finger(finger):
    joints = [f"{finger}_{i:02d}_l" for i in (1, 2, 3)]
    return _anchors(joints[0], _extend(joints[1], joints[2]), joints[1:], bend=True)


def _hik_finger(finger):
    joints = [f"LeftHand{finger}{i}" for i in (1, 2, 3, 4)]
    return _anchors(joints[0], [joints[3], _extend(joints[1], joints[2])], joints[1:3], bend=True)


def _mgear_finger(component):
    joints = [f"{component}_{i}_jnt" for i in (0, 1, 2)]
    return _anchors(joints[0], _extend(joints[1], joints[2]), joints[1:], bend=True)


def _mgear_leg(leg, foot):
    """An mGear 3-joint leg: twist joints, with its elbow or stifle on the 3rd,
    its wrist or hock on the 6th, and a foot joint at the toe."""
    joints = [f"{leg}_{i}_jnt" for i in ("0", "3", "6", "end")]
    return _anchors(
        joints[0], [f"{foot}_0_jnt", _extend(joints[2], joints[3], 0.4, flat=True)], joints[1:], bend="first"
    )


def _hik_chains(root=None):
    """The chains for HumanIK slot names, which Mixamo uses for its joints too."""
    fingers = ("Index", "Middle", "Ring", "Pinky")
    chains = {
        "pelvis": _anchors("Hips"),
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
        "template": "biped",
        "find": "names",
        "chains": {
            "root": _anchors("root"),
            "pelvis": _anchors("pelvis"),
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
    "humanik": {"label": "HumanIK", "template": "biped", "find": "humanik", "chains": _hik_chains(root="Reference")},
    # Mixamo names its joints after the HumanIK slots, in a mixamorig
    # namespace or with a mixamorig_ prefix; it has no root joint.
    "mixamo": {"label": "Mixamo", "template": "biped", "find": "names", "chains": _hik_chains()},
    # The joints mGear's Shifter builds from its own biped template: twist
    # joints along the arm and leg (the elbow and knee are the 4th of 9),
    # fingers L0-L3 from index to pinky, no root joint.
    "mgear": {
        "label": "mGear biped",
        "template": "biped",
        "find": "names",
        "chains": {
            "pelvis": _anchors("spine_C0_0_jnt"),
            "spine": _anchors("spine_C0_0_jnt", "neck_C0_0_jnt"),
            "neck": _anchors("neck_C0_0_jnt", "neck_C0_head_jnt", ["neck_C0_1_jnt"]),
            "head": _anchors("neck_C0_head_jnt"),
            "l_shoulder": _anchors("shoulder_L0_shoulder_jnt", "arm_L0_0_jnt"),
            "l_arm": _anchors("arm_L0_0_jnt", "arm_L0_end_jnt", ["arm_L0_4_jnt"], bend=True),
            "l_hand": _anchors("arm_L0_end_jnt", "finger_L1_0_jnt"),
            **{
                f"l_{finger}_metacarpal": _anchors("arm_L0_end_jnt", f"finger_L{i}_0_jnt")
                for i, finger in enumerate(("index", "middle", "ring", "pinky"))
            },
            "l_thumb": _mgear_finger("thumb_L0"),
            **{f"l_{finger}": _mgear_finger(f"finger_L{i}") for i, finger in enumerate(("index", "middle", "ring", "pinky"))},
            "l_leg": _anchors("leg_L0_0_jnt", "leg_L0_end_jnt", ["leg_L0_4_jnt"], bend=True),
            "l_foot": _anchors("leg_L0_end_jnt", "foot_L0_1_jnt", ["foot_L0_0_jnt"]),
        },
    },
    # The joints mGear's Shifter builds from its own quadruped template; no
    # root or tail joints.
    "mgear_quadruped": {
        "label": "mGear quadruped",
        "template": "quadruped",
        "find": "names",
        "chains": {
            "pelvis": _anchors("spine_C0_0_jnt"),
            "spine": _anchors("spine_C0_0_jnt", "neck_C0_0_jnt"),
            "neck": _anchors("neck_C0_0_jnt", "neck_C0_head_jnt", ["neck_C0_2_jnt"]),
            "head": _anchors("neck_C0_head_jnt"),
            "l_scapula": _anchors("shoulder_L0_0_jnt", "legFront_L0_0_jnt"),
            "l_front_leg": _mgear_leg("legFront_L0", "footFront_L0"),
            "l_quad_leg": _mgear_leg("legBack_L0", "footBack_L0"),
        },
    },
    # A HumanIK quadruped: front legs in the arm slots (the scapula in the
    # shoulder's, the paw in the finger base's), hind legs in the leg slots
    # (the fetlock in the toe base's). There are no toe tip or tail slots.
    "humanik_quadruped": {
        "label": "HumanIK quadruped",
        "template": "quadruped",
        "find": "humanik",
        "chains": {
            "root": _anchors("Reference"),
            "pelvis": _anchors("Hips"),
            "spine": _anchors("Hips", "Neck"),
            "neck": _anchors("Neck", "Head"),
            "head": _anchors("Head"),
            "l_scapula": _anchors("LeftShoulder", "LeftArm"),
            "l_front_leg": _anchors(
                "LeftArm", _extend("LeftHand", "LeftFingerBase", 0.4, flat=True),
                ["LeftForeArm", "LeftHand", "LeftFingerBase"], bend="first",
            ),
            "l_quad_leg": _anchors(
                "LeftUpLeg", _extend("LeftFoot", "LeftToeBase", 0.4, flat=True),
                ["LeftLeg", "LeftFoot", "LeftToeBase"], bend="first",
            ),
        },
    },
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


def detect(nodes, template=None):
    """The key of the skeleton in :data:`SKELETONS` (one for ``template``, if
    given) the hierarchy of ``nodes`` matches best; ``ValueError`` if it
    matches none."""
    hierarchy = _hierarchy(nodes)
    scores = {}
    for key, skeleton in SKELETONS.items():
        if template and skeleton["template"] != template:
            continue
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
            if way.length() < (b - a).length() * 1e-3:
                way = om.MVector(0, 0, 1)
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
        bend = mids[0] if spec["bend"] == "first" else sum(mids, om.MVector()) / len(mids)
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
    skeleton = skeleton or detect(nodes, template)
    fits = SKELETONS[skeleton]["template"]
    if fits != template:
        raise ValueError(f"{SKELETONS[skeleton]['label']} is a {fits} skeleton; it can't align the {template} template.")
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
