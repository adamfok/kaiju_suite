"""IK module: an IK handle on a joint chain, driven by a control, with an
optional pole vector control.

Builds, every node named after ``name`` (``L_arm`` here)::

    L_arm_ik_grp              under ``parent``, or the world
      L_arm_ik_ctrl_grp       at the end joint, matching its orientation
        L_arm_ik_ctrl         circle; the end joint's rotation follows it
          L_arm_ikHandle      start joint to end joint, hidden
      L_arm_pv_ctrl_grp       rp solver with a pole vector only
        L_arm_pv_ctrl

The pole vector control goes on the chain's plane, ``pole_distance`` out
from the middle joint on the side the chain bends to, so adding it doesn't
move the chain. A straight chain has no such side, so it needs a bend.
"""

import re

from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.rig.module import Param, RigModule

SOLVERS = {"rp": "ikRPsolver", "sc": "ikSCsolver"}

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _world(node):
    return om.MVector(cmds.xform(node, query=True, worldSpace=True, translation=True))


def _node_problems(label, name, joint=False):
    matches = cmds.ls(name, long=True) or []
    if not matches:
        return [f"{label} {name!r} isn't in the scene."]
    if len(matches) > 1:
        return [f"Several nodes are named {name!r} ({', '.join(matches)}); the {label.lower()} needs a unique name."]
    if joint and cmds.nodeType(matches[0]) != "joint":
        return [f"{label} {name!r} is not a joint."]
    if not joint and not cmds.objectType(matches[0], isAType="transform"):
        return [f"{label} {name!r} is not a transform."]
    return []


def _chain(start, end):
    """Long paths from ``start`` down to ``end``, both included, or ``None``
    if ``end`` isn't below ``start``."""
    start_path, end_path = cmds.ls(start, long=True)[0], cmds.ls(end, long=True)[0]
    if not end_path.startswith(start_path + "|"):
        return None
    chain = [end_path]
    while chain[-1] != start_path:
        chain.append(cmds.listRelatives(chain[-1], parent=True, fullPath=True)[0])
    return chain[::-1]


def _pole_position(chain, distance):
    """Where the pole vector goes: ``distance`` out from the middle joint, away
    from the start-end line, on the chain's plane. ``None`` if the chain is straight."""
    start, mid, end = _world(chain[0]), _world(chain[len(chain) // 2]), _world(chain[-1])
    line = end - start
    out = (mid - start) - line * (((mid - start) * line) / (line * line))
    if out.length() < 1e-4 * line.length():
        return None
    return mid + out.normal() * distance


def _circle(name, size, parent):
    curve = cmds.circle(name=name, normal=(1, 0, 0), radius=size, constructionHistory=False)[0]
    return cmds.parent(curve, parent, relative=True)[0]


def _diamond(name, size, parent):
    s = size * 0.5
    points = [(0, s, 0), (s, 0, 0), (0, -s, 0), (-s, 0, 0), (0, s, 0), (0, 0, s), (0, -s, 0), (0, 0, -s), (0, s, 0)]
    curve = cmds.curve(name=name, degree=1, point=points)
    return cmds.parent(curve, parent, relative=True)[0]


def _short(node):
    return cmds.ls(node)[0]


class IkModule(RigModule):
    key = "ik"
    name = "IK Module"
    params = (
        Param("name", "Name", "string", "arm", required=True, tooltip="Prefix of every node it creates, e.g. L_arm."),
        Param("start_joint", "Start joint", "node", "", required=True, tooltip="First joint of the chain, e.g. the shoulder."),
        Param("end_joint", "End joint", "node", "", required=True, tooltip="Last joint of the chain, e.g. the wrist."),
        Param("solver", "Solver", "choice", "rp", choices=tuple(SOLVERS), tooltip="rp: rotate plane, with a pole vector. sc: single chain."),
        Param("pole_vector", "Pole vector", "bool", True, tooltip="rp solver only: add a pole vector control."),
        Param("pole_distance", "Pole distance", "float", 5.0, tooltip="How far the pole vector control sits from the middle joint."),
        Param("control_size", "Control size", "float", 1.0),
        Param("parent", "Parent", "node", "", tooltip="Where the module's group goes; blank for the world."),
    )

    def check(self, params):
        found = []
        name = params["name"].strip()
        if not _NAME.match(name):
            found.append(f"Name {name!r} can't be used in node names: use letters, digits and _, not starting with a digit.")
        elif cmds.objExists(f"{name}_ik_grp"):
            found.append(f"{name}_ik_grp already exists: another IK module is named {name}. Pick another name.")

        use_pole = params["solver"] == "rp" and params["pole_vector"]
        start, end = params["start_joint"].strip(), params["end_joint"].strip()
        joint_problems = _node_problems("Start joint", start, joint=True) + _node_problems("End joint", end, joint=True)
        found.extend(joint_problems)
        if not joint_problems:
            chain = _chain(start, end)
            if chain is None:
                found.append(f"End joint {end!r} is not below start joint {start!r}.")
            elif any(cmds.nodeType(node) != "joint" for node in chain):
                others = [_short(node) for node in chain if cmds.nodeType(node) != "joint"]
                found.append(f"Everything from start joint to end joint must be a joint; these aren't: {', '.join(others)}.")
            elif use_pole and len(chain) < 3:
                found.append("A pole vector needs at least 3 joints from start joint to end joint. Turn Pole vector off, or use the sc solver.")
            elif use_pole and _pole_position(chain, 1.0) is None:
                found.append("The chain is straight, so the pole vector has no side to go on. Bend the middle joint slightly, or turn Pole vector off.")

        if params["control_size"] <= 0:
            found.append("Control size must be above 0.")
        if use_pole and params["pole_distance"] <= 0:
            found.append("Pole distance must be above 0.")
        if params["parent"].strip():
            found.extend(_node_problems("Parent", params["parent"].strip()))
        return found

    def create(self, params):
        name = params["name"].strip()
        chain = _chain(params["start_joint"].strip(), params["end_joint"].strip())
        parent = params["parent"].strip()
        size = float(params["control_size"])
        use_pole = params["solver"] == "rp" and params["pole_vector"]
        # Before the handle exists, while the chain is as the user posed it.
        pole = _pole_position(chain, float(params["pole_distance"])) if use_pole else None

        selection = cmds.ls(selection=True, long=True)
        group = cmds.createNode("transform", name=f"{name}_ik_grp", skipSelect=True)
        if parent:
            group = cmds.parent(group, parent)[0]

        control_group = cmds.createNode("transform", name=f"{name}_ik_ctrl_grp", parent=group, skipSelect=True)
        cmds.matchTransform(control_group, chain[-1], position=True, rotation=True)
        control = _circle(f"{name}_ik_ctrl", size, control_group)

        handle, effector = cmds.ikHandle(
            name=f"{name}_ikHandle", startJoint=chain[0], endEffector=chain[-1], solver=SOLVERS[params["solver"]]
        )
        cmds.rename(effector, f"{name}_effector")
        handle = cmds.parent(handle, control)[0]
        cmds.setAttr(f"{handle}.visibility", False)
        cmds.orientConstraint(control, chain[-1], maintainOffset=True, name=f"{name}_end_orientConstraint")

        pole_control = None
        if pole is not None:
            pole_group = cmds.createNode("transform", name=f"{name}_pv_ctrl_grp", parent=group, skipSelect=True)
            cmds.xform(pole_group, worldSpace=True, translation=list(pole))
            pole_control = _diamond(f"{name}_pv_ctrl", size, pole_group)
            cmds.poleVectorConstraint(pole_control, handle, name=f"{name}_poleVectorConstraint")

        cmds.select(selection, replace=True) if selection else cmds.select(clear=True)
        return {
            "group": _short(group),
            "handle": _short(handle),
            "control": _short(control),
            "pole_vector": _short(pole_control) if pole_control else None,
        }


MODULE = IkModule()
