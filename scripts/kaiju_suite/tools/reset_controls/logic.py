"""Reset Controls: put rig controls back to the values they were built with
(see :mod:`kaiju_suite.rigging.rig_module.controls`). No Qt here."""

from maya import cmds

from kaiju_suite.rigging.rig_module import controls


def reset_controls():
    """Reset the selected rig controls, or every one if nothing is selected,
    as one undo step. Returns ``(controls reset, message)``; nothing was
    reset if the list is empty, and the message says why."""
    selection = cmds.ls(selection=True, long=True)
    if selection:
        done = controls.reset(selection)
        if not done:
            return [], "None of the selected nodes is a rig control."
        return done, f"Reset {len(done)} control{'s' if len(done) != 1 else ''}."
    done = controls.reset()
    if not done:
        return [], "The scene has no rig controls."
    return done, f"Reset all {len(done)} control{'s' if len(done) != 1 else ''}."
