"""Pose Tool: QC for poses. The Utilities tab is empty for now. No Qt here.

The QC tab runs the pose checks (:data:`kaiju_suite.datatypes.pose.CHECKS`)
on the selected nodes with :func:`run_qc`, with options saved per user and
shared with Builder's Publish; :func:`select_problem` selects what a
problem points at.
"""

from kaiju_suite import datatypes
from kaiju_suite.core import checks
from kaiju_suite.datatypes import pose as pose_data

# Per-user settings (optionVars) are kept under this name.
SETTINGS_KEY = "pose_tool"
# The checks the QC tab runs (see run_qc).
QC_CHECKS = pose_data.CHECKS


# -- QC ---------------------------------------------------------------------


def qc_settings():
    """The QC options this user saved (defaults for the rest); Builder's
    Publish of a Pose item uses the same ones."""
    return datatypes.qc_settings(pose_data)


def save_qc_setting(key, option, value):
    """Save one QC option for this user."""
    datatypes.save_qc_setting(pose_data, key, option, value)


def run_qc(selection, settings=None):
    """Run the pose checks on the nodes in ``selection`` (long names).
    Returns ``(check, problems)`` pairs. Changes nothing. Raises
    ``ValueError`` if nothing is selected."""
    if not selection:
        raise ValueError("Nothing selected. Select the nodes to check.")
    return datatypes.run_qc(pose_data, selection, settings)


def select_problem(problem):
    """Select the nodes ``problem`` points at that are still in the scene."""
    return checks.select_problem(problem)
