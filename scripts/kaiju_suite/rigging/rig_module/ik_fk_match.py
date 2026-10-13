"""IK/FK matching: switching an IK/FK limb (see :mod:`.modules.ik_fk`) to the
other side without a pop. Imports only Maya, no Qt.

The IK/FK rig module links its switch control to what matching needs, through
message attributes on the switch, so matching works from the switch alone
in an animation scene (references and namespaces keep the links):

    ikFkFkControls[i]   the FK controls, start to end
    ikFkFkJoints[i]     the FK chain's joints
    ikFkIkJoints[i]     the IK chain's joints
    ikFkIkControl       the IK control
    ikFkPoleControl     the pole vector control

:func:`match_fk_to_ik` poses the FK controls onto the IK chain and sets
``ikFk`` to 0; :func:`match_ik_to_fk` moves the IK and pole vector controls
onto the FK chain and sets it to 1. Either way the bind chain stays put.
"""

from collections import namedtuple

from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.rigging.rig_module import helpers

ATTR = "ikFk"
FK_CONTROLS = "ikFkFkControls"
FK_JOINTS = "ikFkFkJoints"
IK_JOINTS = "ikFkIkJoints"
IK_CONTROL = "ikFkIkControl"
POLE_CONTROL = "ikFkPoleControl"

Links = namedtuple("Links", "fk_controls fk_joints ik_joints ik_control pole_control")

_TRANSFORM = [f"{channel}{axis}" for channel in ("translate", "rotate") for axis in "XYZ"]


# -- the links ---------------------------------------------------------------------


def store(switch, fk_controls, fk_joints, ik_joints, ik_control, pole_control):
    """Link ``switch`` to its limb's controls and chains (see the module docstring)."""
    for attr, nodes in ((FK_CONTROLS, fk_controls), (FK_JOINTS, fk_joints), (IK_JOINTS, ik_joints)):
        cmds.addAttr(switch, longName=attr, attributeType="message", multi=True)
        for i, node in enumerate(nodes):
            cmds.connectAttr(f"{node}.message", f"{switch}.{attr}[{i}]")
    for attr, node in ((IK_CONTROL, ik_control), (POLE_CONTROL, pole_control)):
        cmds.addAttr(switch, longName=attr, attributeType="message")
        cmds.connectAttr(f"{node}.message", f"{switch}.{attr}")


def is_switch(node):
    """Whether ``node`` is an IK/FK switch control with its links."""
    return cmds.objExists(node) and all(
        cmds.attributeQuery(attr, node=node, exists=True)
        for attr in (ATTR, FK_CONTROLS, FK_JOINTS, IK_JOINTS, IK_CONTROL, POLE_CONTROL)
    )


def find_switch(node):
    """The switch control of the IK/FK limb ``node`` belongs to (``node``
    itself if it is one), or ``None``."""
    if is_switch(node):
        return helpers.short(node)
    if not cmds.objExists(node):
        return None
    for other in cmds.listConnections(f"{node}.message", source=False, destination=True) or []:
        if is_switch(other):
            return helpers.short(other)
    return None


def _source(plug):
    found = cmds.listConnections(plug, source=True, destination=False)
    return helpers.short(found[0]) if found else None


def _sources(node, attr):
    indices = cmds.getAttr(f"{node}.{attr}", multiIndices=True) or []
    return [_source(f"{node}.{attr}[{i}]") for i in indices]


def links(switch):
    """The :data:`Links` stored on ``switch``. Raises ``ValueError`` if it has
    none, or some are broken."""
    if not cmds.objExists(switch) or not cmds.attributeQuery(ATTR, node=switch, exists=True):
        raise ValueError(f"{switch} is not an IK/FK switch control.")
    if not is_switch(switch):
        raise ValueError(f"{switch} was built before IK/FK matching; rebuild the rig to match it.")
    found = Links(
        _sources(switch, FK_CONTROLS),
        _sources(switch, FK_JOINTS),
        _sources(switch, IK_JOINTS),
        _source(f"{switch}.{IK_CONTROL}"),
        _source(f"{switch}.{POLE_CONTROL}"),
    )
    chains = found.fk_controls, found.fk_joints, found.ik_joints
    if None in found.fk_controls + found.fk_joints + found.ik_joints or None in found[3:] \
            or len({len(c) for c in chains}) != 1 or len(found.ik_joints) < 3:
        raise ValueError(f"{switch}'s IK/FK links are broken; rebuild the rig to match it.")
    return found


# -- matching ------------------------------------------------------------------------


def _matrix(node):
    return om.MMatrix(cmds.xform(node, query=True, worldSpace=True, matrix=True))


def _position(node):
    return om.MVector(cmds.xform(node, query=True, worldSpace=True, translation=True))


def _channels(nodes):
    return [
        (node, attr) for node in nodes for attr in _TRANSFORM
        if cmds.getAttr(f"{node}.{attr}", settable=True)
    ]


def _switching(switch, moved, value, key, match):
    """Run ``match()``, which moves the controls ``moved``, and set ``ikFk``
    to ``value``. With ``key``, key them and ``ikFk`` on the frame before (as
    they were) and on the current one (after), ``ikFk`` stepped, as
    :func:`kaiju_suite.rigging.rig_module.space_switch.switch` does."""
    channels = _channels(moved)
    frame = cmds.currentTime(query=True)
    if key:
        cmds.setKeyframe(switch, attribute=ATTR, time=(frame - 1,))
        for node, attr in channels:
            cmds.setKeyframe(node, attribute=attr, time=(frame - 1,))
    match()
    cmds.setAttr(f"{switch}.{ATTR}", value)
    if key:
        cmds.setKeyframe(switch, attribute=ATTR, time=(frame,))
        for node, attr in channels:
            cmds.setKeyframe(node, attribute=attr, time=(frame,))
        cmds.keyTangent(switch, attribute=ATTR, outTangentType="step")


def match_fk_to_ik(switch, key=False):
    """Pose the FK controls so the FK chain lands on the IK chain, then set
    ``ikFk`` to 0 (FK). See :func:`_switching` for ``key``. Not an undo step
    by itself; wrap callers."""
    info = links(switch)

    def match():
        # Each FK joint follows its control with a fixed offset (a parent
        # constraint keeping its offset), so: control = offset^-1 * IK joint.
        offsets = [_matrix(j) * _matrix(c).inverse() for j, c in zip(info.fk_joints, info.fk_controls)]
        for control, offset, ik_joint in zip(info.fk_controls, offsets, info.ik_joints):
            cmds.xform(control, worldSpace=True, matrix=list(offset.inverse() * _matrix(ik_joint)))

    _switching(switch, info.fk_controls, 0, key, match)


def match_ik_to_fk(switch, key=False):
    """Move the pole vector control onto the FK chain's plane and the IK
    control onto the FK end joint, so the IK chain lands on the FK chain,
    then set ``ikFk`` to 1 (IK). See :func:`_switching` for ``key``. Not an
    undo step by itself; wrap callers."""
    info = links(switch)
    ik_control, pole = info.ik_control, info.pole_control

    def match():
        # The pole vector, as far from the middle joint as it is now.
        middle = len(info.ik_joints) // 2
        distance = (_position(pole) - _position(info.ik_joints[middle])).length()
        position = helpers.pole_position(info.fk_joints, distance)
        if position is not None:  # a straight FK chain has no plane: leave it
            cmds.xform(pole, worldSpace=True, translation=list(position))

        # The IK end joint's orientation follows the control with a fixed
        # offset (an orient constraint keeping its offset).
        offset = om.MTransformationMatrix(_matrix(info.ik_joints[-1]) * _matrix(ik_control).inverse())
        offset.setTranslation(om.MVector(), om.MSpace.kWorld)
        target = om.MTransformationMatrix(offset.asMatrix().inverse() * _matrix(info.fk_joints[-1]))
        target.setTranslation(_position(ik_control), om.MSpace.kWorld)
        cmds.xform(ik_control, worldSpace=True, matrix=list(target.asMatrix()))
        # Then move it so the IK handle, under it, reaches the FK end joint.
        handle = cmds.listRelatives(ik_control, type="ikHandle", fullPath=True) or []
        reach = _position(handle[0]) if handle else _position(info.ik_joints[-1])
        delta = _position(info.fk_joints[-1]) - reach
        cmds.xform(ik_control, worldSpace=True, relative=True, translation=list(delta))

    _switching(switch, [ik_control, pole], 1, key, match)
