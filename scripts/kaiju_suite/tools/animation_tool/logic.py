"""Animation Tool: QC for animated nodes. The Utilities tab is empty for now. No Qt here.

The QC tab runs the animation checks
(:data:`kaiju_suite.datatypes.animation.CHECKS`) on the selected nodes with
:func:`run_qc`, with settings shared with Builder's Publish;
:func:`select_problem` selects what a problem points at.
"""

from kaiju_suite import datatypes
from kaiju_suite.core import checks
from kaiju_suite.datatypes import animation as animation_data

# The checks the QC tab runs (see run_qc).
QC_CHECKS = animation_data.CHECKS


# -- QC ---------------------------------------------------------------------


def qc_settings():
    """The QC options this user saved (defaults for the rest); Builder's
    Publish of an Animation item uses the same ones."""
    return datatypes.qc_settings(animation_data)


def save_qc_setting(key, option, value):
    """Save one QC option for this user."""
    datatypes.save_qc_setting(animation_data, key, option, value)


def run_qc(selection, settings=None):
    """Run the animation checks on the nodes in ``selection`` (long names).
    Returns ``(check, problems)`` pairs. Changes nothing. Raises
    ``ValueError`` if nothing is selected."""
    if not selection:
        raise ValueError("Nothing selected. Select the animated nodes to check.")
    return datatypes.run_qc(animation_data, selection, settings)


def select_problem(problem):
    """Select the nodes ``problem`` points at that are still in the scene."""
    return checks.select_problem(problem)
