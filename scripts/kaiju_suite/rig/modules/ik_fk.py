"""IK/FK: a joint chain that switches between an IK and an FK chain.

The joints from start to end (the "bind" chain) are copied twice, into an IK
chain and an FK chain. The bind joints aren't reparented: each follows its
IK and FK copy through a parent constraint, blended by the switch control's
``ikFk`` attribute (0 is FK, 1 is IK).

Builds, every node named after ``name`` (``L_arm`` here)::

    L_arm_ikfk_grp            under ``parent``, or the world
      L_arm_jnt_grp           hidden
        L_arm_01_ik_jnt > L_arm_02_ik_jnt > ...
        L_arm_01_fk_jnt > L_arm_02_fk_jnt > ...
      L_arm_ik_ctrls_grp      shown while ikFk > 0
        L_arm_ik_ctrl_grp     at the end joint, matching its orientation
          L_arm_ik_ctrl       circle; the end IK joint's rotation follows it
            L_arm_ikHandle    on the IK chain, hidden
        L_arm_pv_ctrl_grp
          L_arm_pv_ctrl
      L_arm_fk_ctrls_grp      shown while ikFk < 1
        L_arm_01_fk_ctrl_grp  at the first joint, matching its orientation
          L_arm_01_fk_ctrl    circle; the first FK joint follows it
            L_arm_02_fk_ctrl_grp
              L_arm_02_fk_ctrl ...
      L_arm_switch_ctrl_grp   follows the end joint
        L_arm_switch_ctrl     box with the ikFk attribute

The IK side works like Simple IK: the pole vector control goes on the
chain's plane, ``pole_distance`` out from the middle joint on the side the
chain bends to, so the chain needs a bend and at least 3 joints. The switch
sits beside the end joint, on the side away from the bend. Every control
gets ``color``.
"""

from maya import cmds

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


def _copy_chain(chain, name, side, parent):
    """Copies of the joints in ``chain``, named ``{name}_01_{side}_jnt``, ...,
    each under the one before and the first under ``parent``."""
    copies = []
    for i, joint in enumerate(chain, 1):
        copy = cmds.duplicate(joint, parentOnly=True, name=f"{name}_{i:02d}_{side}_jnt")[0]
        # Joints keep their world position when reparented.
        copy = cmds.parent(copy, copies[-1] if copies else parent)[0]
        copies.append(helpers.short(copy))
    return copies


def _visibility(switch, group, operation, value, name):
    """Show ``group`` only while ``switch.ikFk`` compares to ``value`` by
    ``operation`` (a condition node's: 2 is greater than, 4 less than)."""
    condition = cmds.createNode("condition", name=name, skipSelect=True)
    cmds.setAttr(f"{condition}.operation", operation)
    cmds.setAttr(f"{condition}.secondTerm", value)
    cmds.setAttr(f"{condition}.colorIfTrueR", 1)
    cmds.setAttr(f"{condition}.colorIfFalseR", 0)
    cmds.connectAttr(f"{switch}.ikFk", f"{condition}.firstTerm")
    cmds.connectAttr(f"{condition}.outColorR", f"{group}.visibility")


class IkFkModule(RigModule):
    key = "ik_fk"
    name = "IK/FK"
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
        found = helpers.name_problems(name, f"{name}_ikfk_grp", self.name)

        start, end = params["start_joint"].strip(), params["end_joint"].strip()
        chain_problems = helpers.chain_problems(start, end, 3)
        found.extend(chain_problems)
        if not chain_problems and _pole_position(helpers.chain(start, end), 1.0) is None:
            found.append("The chain is straight, so the pole vector has no side to go on. Bend the middle joint slightly.")

        if params["control_size"] <= 0:
            found.append("Control size must be above 0.")
        if params["pole_distance"] <= 0:
            found.append("Pole distance must be above 0.")
        found.extend(helpers.parent_problems(params["parent"]))
        return found

    def create(self, params):
        name = params["name"].strip()
        chain = [helpers.short(j) for j in helpers.chain(params["start_joint"].strip(), params["end_joint"].strip())]
        size = float(params["control_size"])
        # Before anything is built, while the chain is as the user posed it.
        pole = _pole_position(chain, float(params["pole_distance"]))
        away = (helpers.world(chain[len(chain) // 2]) - pole).normal()
        controls = []

        with helpers.kept_selection():
            group = helpers.group(f"{name}_ikfk_grp", params["parent"].strip())

            joint_group = helpers.group(f"{name}_jnt_grp", group)
            cmds.setAttr(f"{joint_group}.visibility", False)
            ik_chain = _copy_chain(chain, name, "ik", joint_group)
            fk_chain = _copy_chain(chain, name, "fk", joint_group)

            # IK side, as in Simple IK, on the IK chain.
            ik_group = helpers.group(f"{name}_ik_ctrls_grp", group)
            control_group = helpers.group(f"{name}_ik_ctrl_grp", ik_group)
            cmds.matchTransform(control_group, chain[-1], position=True, rotation=True)
            ik_control = helpers.circle(f"{name}_ik_ctrl", size, control_group)

            handle, effector = cmds.ikHandle(
                name=f"{name}_ikHandle", startJoint=ik_chain[0], endEffector=ik_chain[-1], solver="ikRPsolver"
            )
            cmds.rename(effector, f"{name}_effector")
            handle = cmds.parent(handle, ik_control)[0]
            cmds.setAttr(f"{handle}.visibility", False)
            cmds.orientConstraint(ik_control, ik_chain[-1], maintainOffset=True, name=f"{name}_ik_end_orientConstraint")

            pole_group = helpers.group(f"{name}_pv_ctrl_grp", ik_group)
            cmds.xform(pole_group, worldSpace=True, translation=list(pole))
            pole_control = helpers.diamond(f"{name}_pv_ctrl", size, pole_group)
            cmds.poleVectorConstraint(pole_control, handle, name=f"{name}_poleVectorConstraint")
            controls += [ik_control, pole_control]

            # FK side: one control per joint, each under the one before.
            fk_group = helpers.group(f"{name}_fk_ctrls_grp", group)
            fk_controls = []
            for i, joint in enumerate(fk_chain, 1):
                fk_control_group = helpers.group(f"{name}_{i:02d}_fk_ctrl_grp", fk_controls[-1] if fk_controls else fk_group)
                cmds.matchTransform(fk_control_group, joint, position=True, rotation=True)
                fk_control = helpers.circle(f"{name}_{i:02d}_fk_ctrl", size, fk_control_group)
                cmds.parentConstraint(fk_control, joint, maintainOffset=True, name=f"{name}_{i:02d}_fk_parentConstraint")
                fk_controls.append(fk_control)
            controls += fk_controls

            # The switch, beside the end joint and following it.
            switch_group = helpers.group(f"{name}_switch_ctrl_grp", group)
            cmds.xform(switch_group, worldSpace=True, translation=list(helpers.world(chain[-1]) + away * size * 2))
            switch = helpers.box(f"{name}_switch_ctrl", size * 0.5, switch_group)
            for attr in ("translate", "rotate", "scale"):
                for axis in "XYZ":
                    cmds.setAttr(f"{switch}.{attr}{axis}", lock=True, keyable=False, channelBox=False)
            cmds.addAttr(switch, longName="ikFk", niceName="IK FK", attributeType="double", min=0, max=1, defaultValue=0, keyable=True)
            cmds.parentConstraint(chain[-1], switch_group, maintainOffset=True, name=f"{name}_switch_parentConstraint")
            controls.append(switch)

            # Each bind joint follows its IK joint by ikFk and its FK joint by 1 - ikFk.
            reverse = cmds.createNode("reverse", name=f"{name}_ikFk_reverse", skipSelect=True)
            cmds.connectAttr(f"{switch}.ikFk", f"{reverse}.inputX")
            for i, (joint, ik_joint, fk_joint) in enumerate(zip(chain, ik_chain, fk_chain), 1):
                constraint = cmds.parentConstraint(
                    ik_joint, fk_joint, joint, maintainOffset=True, name=f"{name}_{i:02d}_ikfk_parentConstraint"
                )[0]
                ik_weight, fk_weight = cmds.parentConstraint(constraint, query=True, weightAliasList=True)
                cmds.connectAttr(f"{switch}.ikFk", f"{constraint}.{ik_weight}")
                cmds.connectAttr(f"{reverse}.outputX", f"{constraint}.{fk_weight}")

            _visibility(switch, ik_group, 2, 0, f"{name}_ik_vis_condition")
            _visibility(switch, fk_group, 4, 1, f"{name}_fk_vis_condition")

            for node in controls:
                helpers.set_color(node, params["color"])

        return {
            "group": helpers.short(group),
            "switch": helpers.short(switch),
            "handle": helpers.short(handle),
            "ik_control": helpers.short(ik_control),
            "pole_vector": helpers.short(pole_control),
            "fk_controls": ", ".join(helpers.short(c) for c in fk_controls),
        }


MODULE = IkFkModule()
