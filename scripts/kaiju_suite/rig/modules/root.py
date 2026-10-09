"""Root: the top of a rig, at the world origin, with a root (global) control
and an offset control under it. Needs no joints.

Builds, every node named after ``name`` (``main`` here)::

    main_root_grp             under ``parent``, or the world
      main_root_ctrl          flat circle, ``control_size`` in radius
        main_offset_ctrl      flat circle, 0.8 of that

Both controls lie on the ground (facing +Y). The root control moves, turns
and scales the whole rig; its ``globalScale`` attribute drives its uniform
scale, whose own attributes are locked and hidden. The offset control moves
the rig relative to the root control: build the rest of the rig under it.
Both controls get ``color``.
"""

from maya import cmds

from kaiju_suite.rig import helpers
from kaiju_suite.rig.module import Param, RigModule

UP = (0, 1, 0)
OFFSET_SIZE = 0.8  # the offset control's size, relative to the root control's


def _add_global_scale(control):
    """A keyable ``globalScale`` on ``control`` driving its uniform scale; the
    scale attributes are locked and hidden, so it is the only way to scale."""
    cmds.addAttr(control, longName="globalScale", attributeType="double", defaultValue=1.0, minValue=0.001, keyable=True)
    for axis in "XYZ":
        cmds.connectAttr(f"{control}.globalScale", f"{control}.scale{axis}")
        cmds.setAttr(f"{control}.scale{axis}", lock=True, keyable=False, channelBox=False)


class RootModule(RigModule):
    key = "root"
    name = "Root"
    params = (
        Param("name", "Name", "string", "main", required=True, tooltip="Prefix of every node it creates, e.g. main."),
        Param("control_size", "Control size", "float", 10.0),
        Param("color", "Color", "color", 17, tooltip="Maya index color of the controls; 0 keeps Maya's default."),
        Param("parent", "Parent", "node", "", tooltip="Where the module's group goes; blank for the world."),
    )

    def check(self, params):
        name = params["name"].strip()
        found = helpers.name_problems(name, f"{name}_root_grp", self.name)
        if params["control_size"] <= 0:
            found.append("Control size must be above 0.")
        found.extend(helpers.parent_problems(params["parent"]))
        return found

    def create(self, params):
        name = params["name"].strip()
        size = float(params["control_size"])

        with helpers.kept_selection():
            group = helpers.group(f"{name}_root_grp", params["parent"].strip())
            control = helpers.circle(f"{name}_root_ctrl", size, group, normal=UP)
            _add_global_scale(control)
            offset = helpers.circle(f"{name}_offset_ctrl", size * OFFSET_SIZE, control, normal=UP)

            for node in (control, offset):
                helpers.set_color(node, params["color"])

        return {
            "group": helpers.short(group),
            "control": helpers.short(control),
            "offset": helpers.short(offset),
        }


MODULE = RootModule()
