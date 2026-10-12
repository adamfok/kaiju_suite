from maya import cmds
from maya.api import OpenMaya as om


def run():
    from kaiju_suite.tools.reset_controls import logic

    done, message = logic.reset_controls()
    if done:
        om.MGlobal.displayInfo(f"Kaiju: {message}")
    else:
        cmds.warning(f"Kaiju: {message}")


TOOL = {
    "name": "Reset Controls",
    "category": "Utilities",
    "launch": run,
    "description": "Put the selected rig controls, or every one if nothing is selected, back to the values they were built with.",
}
