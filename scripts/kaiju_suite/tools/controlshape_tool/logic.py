"""ControlShape Tool: QC for controls. The Utilities tab is empty for now. No Qt here.

The QC tab runs the control shape checks
(:data:`kaiju_suite.datatypes.controlshape.CHECKS`) on the selected controls
with :func:`run_qc`, with options saved per user and shared with Builder's
Publish; :func:`select_problem` selects what a problem points at.
"""

from kaiju_suite import datatypes
from kaiju_suite.core import checks
from kaiju_suite.datatypes import controlshape as controlshape_data

# The checks the QC tab runs (see run_qc).
QC_CHECKS = controlshape_data.CHECKS


# -- QC ---------------------------------------------------------------------


def qc_settings():
    """The QC options this user saved (defaults for the rest); Builder's
    Publish of a ControlShape item uses the same ones."""
    return datatypes.qc_settings(controlshape_data)


def save_qc_setting(key, option, value):
    """Save one QC option for this user."""
    datatypes.save_qc_setting(controlshape_data, key, option, value)


def run_qc(selection, settings=None):
    """Run the control shape checks on the controls in ``selection`` (long
    names; a curve shape stands for its control). Returns ``(check,
    problems)`` pairs. Changes nothing. Raises ``ValueError`` if nothing is
    selected."""
    if not selection:
        raise ValueError("Nothing selected. Select the controls to check.")
    return datatypes.run_qc(controlshape_data, selection, settings)


def select_problem(problem):
    """Select the controls or shapes ``problem`` points at that are still in the scene."""
    return checks.select_problem(problem)
