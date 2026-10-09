"""FK Chain: one circle control per joint, each nested under the one before,
so rotating a control carries every control and joint below it.

Builds, every node named after ``name`` (``L_finger`` here)::

    L_finger_fkChain_grp            under ``parent``, or the world
      L_finger_01_fk_ctrl_grp       at the start joint, matching its orientation
        L_finger_01_fk_ctrl         circle; the start joint follows it
          L_finger_02_fk_ctrl_grp   at the next joint
            L_finger_02_fk_ctrl
              ...                   down to the end joint

Each joint is parent constrained to its control, keeping its offset, so it
follows both the control's rotation and translation, and building doesn't
move or rotate it. With ``end_control`` off, the end joint gets no control,
for a chain that ends in a tip; it still follows the joint above, as its
child. The chain needs at least 2 joints. Every control gets ``color``.
"""

from maya import cmds

from kaiju_suite.rig import helpers
from kaiju_suite.rig.module import Param, RigModule


class FkChainModule(RigModule):
    key = "fk_chain"
    name = "FK Chain"
    params = (
        Param("name", "Name", "string", "fk", required=True, tooltip="Prefix of every node it creates, e.g. L_finger."),
        Param("start_joint", "Start joint", "node", "", required=True, tooltip="First joint of the chain, e.g. the knuckle."),
        Param("end_joint", "End joint", "node", "", required=True, tooltip="Last joint of the chain, e.g. the fingertip."),
        Param("end_control", "End control", "bool", True, tooltip="Give the end joint a control too; turn off when it's just a tip."),
        Param("control_size", "Control size", "float", 1.0),
        Param("color", "Color", "color", 17, tooltip="Maya index color of the controls; 0 keeps Maya's default."),
        Param("parent", "Parent", "node", "", tooltip="Where the module's group goes; blank for the world."),
    )

    def check(self, params):
        name = params["name"].strip()
        found = helpers.name_problems(name, f"{name}_fkChain_grp", self.name)
        found.extend(helpers.chain_problems(params["start_joint"].strip(), params["end_joint"].strip(), 2))
        if params["control_size"] <= 0:
            found.append("Control size must be above 0.")
        found.extend(helpers.parent_problems(params["parent"]))
        return found

    def create(self, params):
        name = params["name"].strip()
        chain = helpers.chain(params["start_joint"].strip(), params["end_joint"].strip())
        # Without an end control, a 2-joint chain still gets its start joint's.
        joints = chain if params["end_control"] else chain[:-1]
        size = float(params["control_size"])

        controls = []
        with helpers.kept_selection():
            group = helpers.group(f"{name}_fkChain_grp", params["parent"].strip())
            above = group
            for number, joint in enumerate(joints, start=1):
                control_name = f"{name}_{number:02d}_fk_ctrl"
                control_group = helpers.group(f"{control_name}_grp", above)
                cmds.matchTransform(control_group, joint, position=True, rotation=True)
                control = helpers.circle(control_name, size, control_group)
                # Keeps the offset, so a tiny mismatch can't snap the joint.
                cmds.parentConstraint(control, joint, maintainOffset=True, name=f"{control_name}_parentConstraint")
                helpers.set_color(control, params["color"])
                controls.append(control)
                above = control

        # Text only: the Assembler prints the values joined.
        return {
            "group": helpers.short(group),
            "controls": ", ".join(helpers.short(control) for control in controls),
        }


MODULE = FkChainModule()
