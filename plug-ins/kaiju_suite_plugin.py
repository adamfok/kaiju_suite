"""Kaiju Suite plug-in entry point.

Kept deliberately thin: loading builds the menu, unloading removes it.
All real code lives in the ``kaiju_suite`` package under ``scripts/``.
"""

import kaiju_suite
from kaiju_suite.ui import menu

maya_useNewAPI = True


def _has_ui():
    from maya import cmds

    return not cmds.about(batch=True)


def initializePlugin(plugin):
    from maya.api import OpenMaya as om

    om.MFnPlugin(plugin, "Kaiju", kaiju_suite.__version__)
    if _has_ui():
        menu.build()


def uninitializePlugin(plugin):
    if _has_ui():
        menu.remove()
