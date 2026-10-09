"""Spine IK: a spline IK handle on a joint chain, along a curve bent by a hip
and a chest control, which also twist the chain.

Builds, every node named after ``name`` (``spine`` here)::

    spine_spine_grp             under ``parent``, or the world
      spine_hip_ctrl_grp        at the start joint, matching its orientation
        spine_hip_ctrl          circle around the chain
          spine_hip_drv_jnt     hidden; bends the curve's start
      spine_chest_ctrl_grp      at the end joint, matching its orientation
        spine_chest_ctrl
          spine_chest_drv_jnt   hidden; bends the curve's end
      spine_spine_crv           hidden; skinned to the two driver joints
      spine_ikHandle            start joint to end joint, along the curve, hidden

With no ``curve``, the curve goes through the joints, so building doesn't
move them. A given ``curve`` is copied (the copy is ``spine_spine_crv``)
and left as it is; the joints snap onto the copy. The chain needs at least
3 joints. The controls twist the chain through the handle's Advanced Twist
Controls: the hip control turns the start joint, the chest control the end
one, and the joints between blend. Both controls get ``color``.
"""

from maya import cmds

from kaiju_suite.rig import helpers
from kaiju_suite.rig.module import Param, RigModule

# The handle's Forward Axis (dForwardAxis) for each local axis and sign, and
# its Up Axis (dWorldUpAxis) for each positive axis.
_FORWARD = {(0, 1): 0, (0, -1): 1, (1, 1): 2, (1, -1): 3, (2, 1): 4, (2, -1): 5}
_UP = {0: 6, 1: 0, 2: 3}
_OBJECT_ROTATION_UP_START_END = 4  # dWorldUpType


def _curve_problems(curve):
    """Problems with an optional ``curve`` parameter; blank is fine."""
    curve = curve.strip()
    if not curve:
        return []
    found = helpers.node_problems("Curve", curve)
    if not found and not _curve_shapes(curve):
        found.append(f"Curve {curve!r} is not a NURBS curve.")
    return found


def _curve_shapes(node):
    shapes = cmds.listRelatives(node, shapes=True, fullPath=True, type="nurbsCurve") or []
    return [s for s in shapes if not cmds.getAttr(f"{s}.intermediateObject")]


def _forward(chain):
    """``(axis, sign)`` of the start joint's local axis that points down the
    chain, i.e. at its child: axis 0, 1 or 2 for X, Y or Z."""
    local = cmds.getAttr(f"{chain[1]}.translate")[0]
    axis = max(range(3), key=lambda i: abs(local[i]))
    return axis, 1 if local[axis] >= 0 else -1


def _copy_curve(curve, name, parent):
    """A copy of ``curve``'s transform and curve shape named ``name``, under ``parent``."""
    copy = cmds.duplicate(curve, name=name, returnRootsOnly=True)[0]
    extras = set(cmds.listRelatives(copy, children=True, fullPath=True) or []) - set(_curve_shapes(copy))
    if extras:
        cmds.delete(list(extras))
    return cmds.parent(copy, parent)[0]


def _control(name, joint, size, normal, parent):
    """An offset group at ``joint`` matching its orientation, a circle control
    in it, and a hidden driver joint under the control."""
    control_group = helpers.group(f"{name}_ctrl_grp", parent)
    cmds.matchTransform(control_group, joint, position=True, rotation=True)
    control = helpers.circle(f"{name}_ctrl", size, control_group, normal=normal)
    driver = cmds.createNode("joint", name=f"{name}_drv_jnt", parent=control, skipSelect=True)
    cmds.setAttr(f"{driver}.visibility", False)
    return helpers.short(control), helpers.short(driver)


class SpineIkModule(RigModule):
    key = "spine_ik"
    name = "Spine IK"
    params = (
        Param("name", "Name", "string", "spine", required=True, tooltip="Prefix of every node it creates, e.g. spine."),
        Param("start_joint", "Start joint", "node", "", required=True, tooltip="First joint of the chain, e.g. the hips."),
        Param("end_joint", "End joint", "node", "", required=True, tooltip="Last joint of the chain, e.g. the chest."),
        Param("curve", "Curve", "node", "", tooltip="A NURBS curve for the spine to follow; blank makes one through the joints."),
        Param("control_size", "Control size", "float", 1.0),
        Param("color", "Color", "color", 17, tooltip="Maya index color of the controls; 0 keeps Maya's default."),
        Param("parent", "Parent", "node", "", tooltip="Where the module's group goes; blank for the world."),
    )

    def check(self, params):
        name = params["name"].strip()
        found = helpers.name_problems(name, f"{name}_spine_grp", self.name)
        found.extend(helpers.chain_problems(params["start_joint"].strip(), params["end_joint"].strip(), 3))
        found.extend(_curve_problems(params["curve"]))
        if params["control_size"] <= 0:
            found.append("Control size must be above 0.")
        found.extend(helpers.parent_problems(params["parent"]))
        return found

    def create(self, params):
        name = params["name"].strip()
        chain = helpers.chain(params["start_joint"].strip(), params["end_joint"].strip())
        size = float(params["control_size"])
        axis, sign = _forward(chain)
        normal = [0, 0, 0]
        normal[axis] = 1

        with helpers.kept_selection():
            group = helpers.group(f"{name}_spine_grp", params["parent"].strip())

            hip, hip_driver = _control(f"{name}_hip", chain[0], size, normal, group)
            chest, chest_driver = _control(f"{name}_chest", chain[-1], size, normal, group)

            # Through the joints, before the handle exists, so they stay put.
            curve_name = f"{name}_spine_crv"
            if params["curve"].strip():
                curve = _copy_curve(params["curve"].strip(), curve_name, group)
            else:
                points = [list(helpers.world(joint)) for joint in chain]
                curve = cmds.parent(cmds.curve(name=curve_name, degree=3, editPoint=points), group)[0]
            for shape in _curve_shapes(curve):
                cmds.rename(shape, f"{curve_name}Shape")
            # The skin already moves the curve with the controls; the group mustn't move it again.
            cmds.setAttr(f"{curve}.inheritsTransform", False)
            cmds.setAttr(f"{curve}.visibility", False)
            cmds.skinCluster(
                hip_driver, chest_driver, curve, toSelectedBones=True, maximumInfluences=2, name=f"{name}_spine_skinCluster"
            )

            handle, effector = cmds.ikHandle(
                name=f"{name}_ikHandle",
                startJoint=chain[0],
                endEffector=chain[-1],
                solver="ikSplineSolver",
                createCurve=False,
                curve=curve,
                parentCurve=False,
            )
            cmds.rename(effector, f"{name}_effector")
            handle = cmds.parent(handle, group)[0]
            cmds.setAttr(f"{handle}.visibility", False)

            # Twist: the joints' forward axis follows the chain; their next
            # axis turns toward that axis of the hip control at the start and
            # of the chest control at the end. The controls match the joints'
            # orientation, so the chain keeps its twist until they turn.
            up = (axis + 1) % 3
            vector = [0, 0, 0]
            vector[up] = 1
            cmds.setAttr(f"{handle}.dTwistControlEnable", True)
            cmds.setAttr(f"{handle}.dWorldUpType", _OBJECT_ROTATION_UP_START_END)
            cmds.setAttr(f"{handle}.dForwardAxis", _FORWARD[axis, sign])
            cmds.setAttr(f"{handle}.dWorldUpAxis", _UP[up])
            cmds.setAttr(f"{handle}.dWorldUpVector", *vector)
            cmds.setAttr(f"{handle}.dWorldUpVectorEnd", *vector)
            cmds.connectAttr(f"{hip}.worldMatrix[0]", f"{handle}.dWorldUpMatrix")
            cmds.connectAttr(f"{chest}.worldMatrix[0]", f"{handle}.dWorldUpMatrixEnd")

            for node in (hip, chest):
                helpers.set_color(node, params["color"])

        return {
            "group": helpers.short(group),
            "handle": helpers.short(handle),
            "curve": helpers.short(curve),
            "hip_control": helpers.short(hip),
            "chest_control": helpers.short(chest),
        }


MODULE = SpineIkModule()
