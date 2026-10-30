"""Example scenario: Outliner Tool's Unparent and Reparent buttons.

Copy this for a one-off check of the feature you changed; it runs inside the
test Maya with ``ui`` (kaiju_ui_agent.Scenario) and ``cmds`` already defined:

    mayapy dev/maya_ui/maya_ui.py check dev/maya_ui/example_scenario.py
"""

cmds.file(new=True, force=True)
group = cmds.group(empty=True, name="rig_grp")
joints = [cmds.joint(name=f"jnt_{i}") for i in range(2)]
cmds.select(clear=True)

with ui.step("Open Outliner Tool"):
    window = ui.open_tool("Outliner Tool")

with ui.step("Unparent moves the selection to the world"):
    cmds.select(joints[1])
    ui.click(window, "Unparent")
    assert cmds.listRelatives(joints[1], parent=True) is None, cmds.listRelatives(joints[1], parent=True)

with ui.step("Reparent puts it back under its previous parent"):
    cmds.select(joints[1])
    ui.click(window, "Reparent")
    assert cmds.listRelatives(joints[1], parent=True) == [joints[0]], cmds.listRelatives(joints[1], parent=True)

ui.screenshot(window, "outliner_after_reparent")
ui.close_tool(window)
