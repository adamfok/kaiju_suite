"""BlendShape Tool: QC for meshes' blendShapes. The Utilities tab is empty for now. No Qt here.

The QC tab runs the blendShape checks
(:data:`kaiju_suite.datatypes.blendshape.CHECKS`) on the selected meshes with
:func:`run_qc`, with options saved per user and shared with Builder's
Publish; :func:`select_problem` selects what a problem points at.
"""

from maya import cmds

from kaiju_suite import datatypes
from kaiju_suite.core import checks
from kaiju_suite.datatypes import blendshape as blendshape_data


# The checks the QC tab runs (see run_qc).
QC_CHECKS = blendshape_data.CHECKS


# -- finding ----------------------------------------------------------------


def _shape(transform):
    shapes = cmds.listRelatives(transform, shapes=True, noIntermediate=True, type="mesh", fullPath=True)
    return shapes[0] if shapes else None


def meshes(selection):
    """The mesh transforms in ``selection`` (a shape or component stands for
    its transform), in order, each once."""
    found = []
    for node in cmds.ls(selection, objectsOnly=True, long=True) or []:
        if cmds.nodeType(node) == "mesh":
            node = cmds.listRelatives(node, parent=True, fullPath=True)[0]
        if cmds.objectType(node, isAType="transform") and _shape(node):
            found.append(node)
    return list(dict.fromkeys(found))


# -- QC ---------------------------------------------------------------------


def qc_settings():
    """The QC options this user saved (defaults for the rest); Builder's
    Publish of a BlendShapes item uses the same ones."""
    return datatypes.qc_settings(blendshape_data)


def save_qc_setting(key, option, value):
    """Save one QC option for this user."""
    datatypes.save_qc_setting(blendshape_data, key, option, value)


def run_qc(selection, settings=None):
    """Run the blendShape checks on the meshes in ``selection`` (long names).
    Returns ``(check, problems)`` pairs. Changes nothing. Raises
    ``ValueError`` if no meshes are selected."""
    if not selection or not meshes(selection):
        raise ValueError("No meshes selected. Select the meshes to check.")
    return datatypes.run_qc(blendshape_data, selection, settings)


def select_problem(problem):
    """Select the meshes ``problem`` points at that are still in the scene."""
    return checks.select_problem(problem)
