"""Feet for leg guide modules (Leg Guide, and later Quad Leg Guide).

A foot is a planar chain (:mod:`.planar_chain`) from the ankle to the
ball and the toe, attached under the leg's end joint: it shares the
ankle guide, and its plane is its own, so the foot can point forward
while the knee splays. With it come the reverse foot's pivots, **heel**,
**inner** and **outer**: move-only locators, not joints, that a foot rig
module finds by name (``<name>_heel_pivot``...).

Its part of a leg layout: positions in world space, and the foot chain's
own aim and up axes (a layout without them takes the leg's ``aim`` and
``up``)::

    {"foot": [ball, toe], "foot_up": [x, y, z],
     "heel": [x, y, z], "inner": [x, y, z], "outer": [x, y, z],
     "foot_aim": "x", "foot_up_axis": "y"}

``leg`` is always the guide group of the leg chain the foot hangs under
the end of. Like :mod:`.planar_chain`, nothing here opens an undo chunk.
"""

from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.rigging.guide_module import planar_chain
from kaiju_suite.rigging.guide_module.guide_module import flip_x, flipped_axis

PIVOTS = ("heel", "inner", "outer")
KEYS = ("foot", "foot_up") + PIVOTS  # required; the axes below aren't
AXES = ("foot_aim", "foot_up_axis")
# On the foot chain's guide group: message links to the pivots, in PIVOTS order.
_PIVOTS = "footPivots"
_PIVOT_COLOR = 13  # red


def chain_name(name):
    """The name of the foot chain of the leg named ``name``."""
    return f"{name}_foot"


def pivot_names(name):
    return [f"{name}_{pivot}_pivot" for pivot in PIVOTS]


def axes(layout):
    """``(aim, up)`` of the foot chain in ``layout``: its own, else the leg's."""
    return layout.get("foot_aim", layout["aim"]), layout.get("foot_up_axis", layout["up"])


def problems(name, ankle, layout):
    """Why the foot in ``layout`` can't be built under an ankle at
    ``ankle`` in the current scene, as messages. Its positions must already
    be ``[x, y, z]`` lists."""
    if len(layout["foot"]) != 2:
        return [f"{name}: foot needs 2 guides (ball, toe)."]
    aim, up = axes(layout)
    try:
        planar_chain.check_build(chain_name(name), [ankle] + layout["foot"], layout["foot_up"], aim, up, attached=True)
    except ValueError as e:
        return [f"{name} foot: {e}"]
    taken = [n for n in pivot_names(name) if cmds.objExists(n)]
    if taken:
        return [f"These names are already used, rename or delete them first: {', '.join(taken)}"]
    return []


def check(layout, ankle):
    """Raise ``ValueError`` if :func:`reset` can't put ``layout``'s foot
    back with the ankle at ``ankle``. Changes nothing."""
    if len(layout["foot"]) != 2:
        raise ValueError("foot needs 2 guides (ball, toe).")
    planar_chain.check_axes(*axes(layout))
    planar_chain.planar_positions([ankle] + layout["foot"], layout["foot_up"])


def build(leg, name, layout):
    """Build the foot of ``layout`` (checked) under the end joint of the
    ``leg`` chain, and its pivots. Returns the foot's guide group."""
    ankle = planar_chain.joints(leg)[-1]
    start = planar_chain.guides(leg)["chain"][-1]
    ankle_position = cmds.xform(start, query=True, worldSpace=True, translation=True)
    group = planar_chain.build_at(
        chain_name(name), [ankle_position] + layout["foot"], layout["foot_up"], *axes(layout), parent=ankle
    )
    cmds.addAttr(group, longName=_PIVOTS, attributeType="message", multi=True)
    size = (om.MVector(layout["foot"][-1]) - om.MVector(ankle_position)).length() * 0.05
    for i, (key, pivot_name) in enumerate(zip(PIVOTS, pivot_names(name))):
        pivot = planar_chain.guide_locator(pivot_name, group, om.MVector(layout[key]), size)
        cmds.setAttr(f"{pivot}.overrideEnabled", True)
        cmds.setAttr(f"{pivot}.overrideColor", _PIVOT_COLOR)
        cmds.connectAttr(f"{pivot}.message", f"{group}.{_PIVOTS}[{i}]")
    cmds.select(clear=True)
    return group


def group(leg):
    """The guide group of the foot hanging under the end of the ``leg``
    chain. Raises ``ValueError`` if there's none."""
    found = planar_chain.attached(planar_chain.joints(leg)[-1]) if planar_chain.joints(leg) else []
    if not found:
        raise ValueError(f"The foot guides of {cmds.ls(leg)[0]} are missing; delete them and build them again.")
    return found[0]


def pivots(leg):
    """``{"heel", "inner", "outer"}``: the foot's pivot locators, long names."""
    foot = group(leg)
    found = {}
    for index in cmds.getAttr(f"{foot}.{_PIVOTS}", multiIndices=True) or []:
        source = cmds.listConnections(f"{foot}.{_PIVOTS}[{index}]", source=True, destination=False)
        if source and index < len(PIVOTS):
            found[PIVOTS[index]] = cmds.ls(source[0], long=True)[0]
    missing = [p for p in PIVOTS if p not in found]
    if missing:
        raise ValueError(f"The {', '.join(missing)} pivot of {cmds.ls(leg)[0]} is missing.")
    return found


def _rounded(node):
    return [round(c, 6) + 0.0 for c in cmds.xform(node, query=True, worldSpace=True, translation=True)]


def layout(leg):
    """The foot's part of the leg layout, as its guides are now."""
    chain = planar_chain.layout(group(leg))
    return {
        "foot": chain["guides"][1:],
        "foot_up": chain["up_guide"],
        **{key: _rounded(pivot) for key, pivot in pivots(leg).items()},
        "foot_aim": chain["aim"],
        "foot_up_axis": chain["up"],
    }


def set_axes(leg, aim, up):
    """Turn the foot's joints: ``aim`` points at the next joint and ``up``
    towards the foot's up guide."""
    planar_chain.set_axes(group(leg), aim, up)


def reset(leg, layout):
    """Put the foot's guides, pivots and axes back as ``layout`` has them
    (see :func:`check`)."""
    foot = group(leg)
    ankle = planar_chain.layout(leg)["guides"][-1]
    found = pivots(leg)
    planar_chain.set_layout(foot, [ankle] + layout["foot"], layout["foot_up"], *axes(layout))
    for key, pivot in found.items():
        cmds.xform(pivot, worldSpace=True, translation=layout[key])


def mirrored(layout):
    """The foot's part of ``layout`` mirrored across X, its axes reversed.
    Inner stays inner: it's still the pivot nearer the middle."""
    aim, up = axes(layout)
    return {
        "foot": [flip_x(p) for p in layout["foot"]],
        **{key: flip_x(layout[key]) for key in ("foot_up",) + PIVOTS},
        "foot_aim": flipped_axis(aim),
        "foot_up_axis": flipped_axis(up),
    }
