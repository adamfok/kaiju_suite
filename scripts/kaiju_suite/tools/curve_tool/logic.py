"""Curve Tool: QC for NURBS curves. No Qt.

The checks live in :data:`kaiju_suite.datatypes.curves.CHECKS`, so
Builder's Publish of a NurbsCurve item runs them too. :func:`run_qc` runs
them on the selected curves; :func:`select_problem` selects the curves a
problem points at. Nothing here changes the scene, so there's nothing to
undo.
"""

from kaiju_suite import datatypes
from kaiju_suite.core import checks
from kaiju_suite.datatypes import curves as curve_data

# Per-user settings (optionVars) are kept under this name.
SETTINGS_KEY = "curve_tool"
# The checks the QC tab runs (see run_qc).
QC_CHECKS = curve_data.CHECKS


def qc_settings():
    """The QC options this user saved (defaults for the rest); Builder's
    Publish of a NurbsCurve item uses the same ones."""
    return datatypes.qc_settings(curve_data)


def save_qc_setting(key, option, value):
    """Save one QC option for this user."""
    datatypes.save_qc_setting(curve_data, key, option, value)


def run_qc(selection, settings=None):
    """Run the curve checks on the curves in ``selection`` (long names; a
    shape or component stands for its curve). Returns ``(check, problems)``
    pairs. Changes nothing. Raises ``ValueError`` if no curves are selected."""
    if not curve_data.curve_transforms(selection):
        raise ValueError("No NURBS curves selected. Select the curves to check.")
    return datatypes.run_qc(curve_data, selection, settings)


def select_problem(problem):
    """Select what ``problem`` points at that's still in the scene."""
    return checks.select_problem(problem)
