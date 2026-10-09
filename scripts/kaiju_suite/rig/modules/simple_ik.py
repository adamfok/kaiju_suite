"""Simple IK: a rotate-plane IK handle on a joint chain, driven by a control,
with a pole vector control.

Builds, every node named after ``name`` (``L_arm`` here)::

    L_arm_ik_grp              under ``parent``, or the world
      L_arm_ik_ctrl_grp       at the end joint, matching its orientation
        L_arm_ik_ctrl         circle; the end joint's rotation follows it
          L_arm_ikHandle      start joint to end joint, hidden
      L_arm_pv_ctrl_grp
        L_arm_pv_ctrl

The pole vector control goes on the chain's plane, ``pole_distance`` out
from the middle joint on the side the chain bends to, so adding it doesn't
move the chain. A straight chain has no such side, so it needs a bend, and
the chain needs at least 3 joints. Both controls get ``color``.
"""

from maya import cmds

from kaiju_suite.rig import helpers
from kaiju_suite.rig.module import Param, RigModule


class SimpleIkModule(RigModule):
    key = "simple_ik"
    name = "Simple IK"
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
        found = helpers.name_problems(name, f"{name}_ik_grp", self.name)

        start, end = params["start_joint"].strip(), params["end_joint"].strip()
        chain_problems = helpers.chain_problems(start, end, 3)
        found.extend(chain_problems)
        if not chain_problems and helpers.pole_position(helpers.chain(start, end), 1.0) is None:
            found.append("The chain is straight, so the pole vector has no side to go on. Bend the middle joint slightly.")

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
        pole = helpers.pole_position(chain, float(params["pole_distance"]))

        with helpers.kept_selection():
            group = helpers.group(f"{name}_ik_grp", params["parent"].strip())

            control_group = helpers.group(f"{name}_ik_ctrl_grp", group)
            cmds.matchTransform(control_group, chain[-1], position=True, rotation=True)
            control = helpers.circle(f"{name}_ik_ctrl", size, control_group)

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

            for node in (control, pole_control):
                helpers.set_color(node, params["color"])

        return {
            "group": helpers.short(group),
            "handle": helpers.short(handle),
            "control": helpers.short(control),
            "pole_vector": helpers.short(pole_control),
        }


MODULE = SimpleIkModule()
