"""Joint Tool: QC for joints. The Utilities tab is empty for now. No Qt here.

The QC tab runs the joint checks (:data:`kaiju_suite.datatypes.joints.CHECKS`)
on the selected joints and the joints below them with :func:`run_qc`, with
options saved per user and shared with Builder's Publish;
:func:`select_problem` selects what a problem points at.
"""

from maya import cmds

from kaiju_suite import datatypes
from kaiju_suite.core import checks
from kaiju_suite.datatypes import joints as joint_data

# The checks the QC tab runs (see run_qc).
QC_CHECKS = joint_data.CHECKS


# -- QC ---------------------------------------------------------------------


def qc_settings():
    """The QC options this user saved (defaults for the rest); Builder's
    Publish of a Joints item uses the same ones."""
    return datatypes.qc_settings(joint_data)


def save_qc_setting(key, option, value):
    """Save one QC option for this user."""
    datatypes.save_qc_setting(joint_data, key, option, value)


def run_qc(selection, settings=None):
    """Run the joint checks on the joints in ``selection`` (long names) and
    every joint below them. Returns ``(check, problems)`` pairs. Changes
    nothing. Raises ``ValueError`` if no joints are selected."""
    if not selection or not cmds.ls(selection, type="joint"):
        raise ValueError("No joints selected. Select the root joints to check.")
    return datatypes.run_qc(joint_data, selection, settings)


def select_problem(problem):
    """Select the joints ``problem`` points at that are still in the scene."""
    return checks.select_problem(problem)
