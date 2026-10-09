"""Single FK: one joint driven by a control.

Builds, every node named after ``name`` (``L_elbow`` here)::

    L_elbow_fk_grp            under ``parent``, or the world
      L_elbow_fk_ctrl_grp     at the joint, matching its orientation
        L_elbow_fk_ctrl       circle; the joint follows it

The joint follows the control's translation and rotation through one parent
constraint. The control starts exactly on the joint, so building doesn't move
or rotate it; the constraint keeps any tiny offset rather than snapping the
joint. The control gets ``color``.
"""

from maya import cmds

from kaiju_suite.rig import helpers
from kaiju_suite.rig.module import Param, RigModule


class SingleFkModule(RigModule):
    key = "single_fk"
    name = "Single FK"
    params = (
        Param("name", "Name", "string", "fk", required=True, tooltip="Prefix of every node it creates, e.g. L_elbow."),
        Param("joint", "Joint", "node", "", required=True, tooltip="The joint the control drives."),
        Param("control_size", "Control size", "float", 1.0),
        Param("color", "Color", "color", 17, tooltip="Maya index color of the control; 0 keeps Maya's default."),
        Param("parent", "Parent", "node", "", tooltip="Where the module's group goes; blank for the world."),
    )

    def check(self, params):
        name = params["name"].strip()
        found = helpers.name_problems(name, f"{name}_fk_grp", self.name)
        found.extend(helpers.node_problems("Joint", params["joint"].strip(), joint=True))
        if params["control_size"] <= 0:
            found.append("Control size must be above 0.")
        found.extend(helpers.parent_problems(params["parent"]))
        return found

    def create(self, params):
        name = params["name"].strip()
        joint = cmds.ls(params["joint"].strip(), long=True)[0]

        with helpers.kept_selection():
            group = helpers.group(f"{name}_fk_grp", params["parent"].strip())

            control_group = helpers.group(f"{name}_fk_ctrl_grp", group)
            cmds.matchTransform(control_group, joint, position=True, rotation=True)
            control = helpers.circle(f"{name}_fk_ctrl", float(params["control_size"]), control_group)
            cmds.parentConstraint(control, joint, maintainOffset=True, name=f"{name}_fk_parentConstraint")

            helpers.set_color(control, params["color"])

        return {
            "group": helpers.short(group),
            "control_group": helpers.short(control_group),
            "control": helpers.short(control),
        }


MODULE = SingleFkModule()
