"""Stretchy IK: Simple IK whose chain lengthens when its control is pulled
past the chain's reach.

Builds, every node named after ``name`` (``L_arm`` here)::

    L_arm_stretchIk_grp       under ``parent``, or the world
      L_arm_ik_ctrl_grp       at the end joint, matching its orientation
        L_arm_ik_ctrl         circle, with ``stretch``; the end joint's rotation follows it
          L_arm_ikHandle      start joint to end joint, hidden
      L_arm_pv_ctrl_grp
        L_arm_pv_ctrl
      L_arm_stretchStart_loc  follows the start joint, hidden
      L_arm_stretchEnd_loc    follows the IK control, hidden

The IK and pole vector controls work as in Simple IK: the pole vector control
goes on the chain's plane, ``pole_distance`` out from the middle joint, so the
chain needs a bend and at least 3 joints. Both controls get ``color``.

Stretch: ``L_arm_stretch_dist`` measures from the start joint to the IK
control, in the group's space, so scaling the rig together with the skeleton
doesn't stretch it. Past the chain's rest length, every joint below the start
joint has its rest translation scaled by distance / rest length, whatever axis
the joints aim down, so the end joint reaches the control. Within reach the
joints keep their rest translation (no squash). The control's ``stretch``
attribute (0 to 1) blends stretching off and on. The joints below the start
joint have their translation driven, so it can't be locked or connected.
"""

from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.rig import helpers
from kaiju_suite.rig.module import Param, RigModule


def _pole_position(chain, distance):
    """Where the pole vector goes: ``distance`` out from the middle joint, away
    from the start-end line, on the chain's plane. ``None`` if the chain is straight."""
    start, mid, end = (helpers.world(chain[i]) for i in (0, len(chain) // 2, -1))
    line = end - start
    out = (mid - start) - line * (((mid - start) * line) / (line * line))
    if out.length() < 1e-4 * line.length():
        return None
    return mid + out.normal() * distance


def _translate_problems(joints):
    """Problems with stretch driving the translation of ``joints``: it can't
    be locked or already connected."""
    found = []
    for joint in joints:
        plugs = [f"{joint}.{attr}" for attr in ("translate", "translateX", "translateY", "translateZ")]
        if any(cmds.getAttr(p, lock=True) or cmds.connectionInfo(p, isExactDestination=True) for p in plugs):
            found.append(f"{helpers.short(joint)}'s translate is locked or connected; stretching needs to drive it.")
    return found


def _rest_length(chain, space):
    """The chain's length along its bones, measured in the space of the node
    ``space`` (so a scaled parent doesn't change it)."""
    inverse = om.MMatrix(cmds.getAttr(f"{space}.worldInverseMatrix[0]"))
    points = [om.MPoint(helpers.world(joint)) * inverse for joint in chain]
    return sum((b - a).length() for a, b in zip(points, points[1:]))


def _locator(name, parent):
    """A hidden locator named ``name`` under ``parent``."""
    locator = cmds.spaceLocator(name=name)[0]
    locator = cmds.parent(locator, parent, relative=True)[0]
    cmds.setAttr(f"{locator}.visibility", False)
    return locator


def _node(node_type, name):
    return cmds.createNode(node_type, name=name, skipSelect=True)


class StretchyIkModule(RigModule):
    key = "stretchy_ik"
    name = "Stretchy IK"
    params = (
        Param("name", "Name", "string", "arm", required=True, tooltip="Prefix of every node it creates, e.g. L_arm."),
        Param("start_joint", "Start joint", "node", "", required=True, tooltip="First joint of the chain, e.g. the shoulder."),
        Param("end_joint", "End joint", "node", "", required=True, tooltip="Last joint of the chain, e.g. the wrist."),
        Param("pole_distance", "Pole distance", "float", 5.0, tooltip="How far the pole vector control sits from the middle joint."),
        Param("control_size", "Control size", "float", 1.0),
        Param("color", "Color", "color", 17, tooltip="Maya index color of the controls; 0 keeps Maya's default."),
        Param("parent", "Parent", "node", "", tooltip="Where the module's group goes; blank for the world."),
    )

    def check(self, params):
        name = params["name"].strip()
        found = helpers.name_problems(name, f"{name}_stretchIk_grp", self.name)

        start, end = params["start_joint"].strip(), params["end_joint"].strip()
        chain_problems = helpers.chain_problems(start, end, 3)
        found.extend(chain_problems)
        if not chain_problems:
            chain = helpers.chain(start, end)
            if _pole_position(chain, 1.0) is None:
                found.append("The chain is straight, so the pole vector has no side to go on. Bend the middle joint slightly.")
            found.extend(_translate_problems(chain[1:]))

        if params["control_size"] <= 0:
            found.append("Control size must be above 0.")
        if params["pole_distance"] <= 0:
            found.append("Pole distance must be above 0.")
        found.extend(helpers.parent_problems(params["parent"]))
        return found

    def create(self, params):
        name = params["name"].strip()
        chain = helpers.chain(params["start_joint"].strip(), params["end_joint"].strip())
        size = float(params["control_size"])
        # Before the handle exists, while the chain is as the user posed it.
        pole = _pole_position(chain, float(params["pole_distance"]))
        rest_translates = [cmds.getAttr(f"{joint}.translate")[0] for joint in chain[1:]]

        with helpers.kept_selection():
            group = helpers.group(f"{name}_stretchIk_grp", params["parent"].strip())
            rest_length = _rest_length(chain, group)

            control_group = helpers.group(f"{name}_ik_ctrl_grp", group)
            cmds.matchTransform(control_group, chain[-1], position=True, rotation=True)
            control = helpers.circle(f"{name}_ik_ctrl", size, control_group)
            cmds.addAttr(control, longName="stretch", attributeType="double", minValue=0, maxValue=1, defaultValue=1, keyable=True)

            handle, effector = cmds.ikHandle(
                name=f"{name}_ikHandle", startJoint=chain[0], endEffector=chain[-1], solver="ikRPsolver"
            )
            cmds.rename(effector, f"{name}_effector")
            handle = cmds.parent(handle, control)[0]
            cmds.setAttr(f"{handle}.visibility", False)
            cmds.orientConstraint(control, chain[-1], maintainOffset=True, name=f"{name}_end_orientConstraint")

            pole_group = helpers.group(f"{name}_pv_ctrl_grp", group)
            cmds.xform(pole_group, worldSpace=True, translation=list(pole))
            pole_control = helpers.diamond(f"{name}_pv_ctrl", size, pole_group)
            cmds.poleVectorConstraint(pole_control, handle, name=f"{name}_poleVectorConstraint")

            # Measure start joint to control in the group's space. The start
            # locator follows only the start joint's position, which the IK
            # doesn't drive, so there's no cycle.
            start_locator = _locator(f"{name}_stretchStart_loc", group)
            cmds.pointConstraint(chain[0], start_locator, name=f"{name}_stretchStart_pointConstraint")
            end_locator = _locator(f"{name}_stretchEnd_loc", group)
            cmds.pointConstraint(control, end_locator, name=f"{name}_stretchEnd_pointConstraint")
            distance = _node("distanceBetween", f"{name}_stretch_dist")
            cmds.connectAttr(f"{start_locator}.translate", f"{distance}.point1")
            cmds.connectAttr(f"{end_locator}.translate", f"{distance}.point2")

            # factor = distance / rest length past reach, else 1; blended to 1 by stretch.
            ratio = _node("multiplyDivide", f"{name}_stretch_ratio")
            cmds.setAttr(f"{ratio}.operation", 2)  # divide
            cmds.connectAttr(f"{distance}.distance", f"{ratio}.input1X")
            cmds.setAttr(f"{ratio}.input2X", rest_length)
            beyond = _node("condition", f"{name}_stretch_cnd")
            cmds.setAttr(f"{beyond}.operation", 2)  # greater than
            cmds.connectAttr(f"{distance}.distance", f"{beyond}.firstTerm")
            cmds.setAttr(f"{beyond}.secondTerm", rest_length)
            cmds.connectAttr(f"{ratio}.outputX", f"{beyond}.colorIfTrueR")
            cmds.setAttr(f"{beyond}.colorIfFalseR", 1)
            blend = _node("blendColors", f"{name}_stretch_blend")
            cmds.connectAttr(f"{control}.stretch", f"{blend}.blender")
            cmds.connectAttr(f"{beyond}.outColorR", f"{blend}.color1R")
            cmds.setAttr(f"{blend}.color2R", 1)

            # Scale each child joint's rest translation by the factor.
            for index, (joint, translate) in enumerate(zip(chain[1:], rest_translates), start=1):
                scale = _node("multiplyDivide", f"{name}_stretch{index}_mul")
                cmds.setAttr(f"{scale}.input1", *translate)
                for axis in "XYZ":
                    cmds.connectAttr(f"{blend}.outputR", f"{scale}.input2{axis}")
                cmds.connectAttr(f"{scale}.output", f"{joint}.translate")

            for node in (control, pole_control):
                helpers.set_color(node, params["color"])

        return {
            "group": helpers.short(group),
            "handle": helpers.short(handle),
            "control": helpers.short(control),
            "pole_vector": helpers.short(pole_control),
            "distance": helpers.short(distance),
        }


MODULE = StretchyIkModule()
