"""Loft Tool: QC for lofted NURBS surfaces. No Qt.

The checks live in :data:`kaiju_suite.datatypes.loft.CHECKS`, so Builder's
Publish of a Loft item runs them too. :func:`run_qc` runs them on the
selected surfaces; :func:`select_problem` selects the surfaces, curves or
loft nodes a problem points at. Nothing here changes the scene, so there's
nothing to undo.
"""

from kaiju_suite import datatypes
from kaiju_suite.core import checks
from kaiju_suite.datatypes import loft

# Per-user settings (optionVars) are kept under this name.
SETTINGS_KEY = "loft_tool"
# The checks the QC tab runs (see run_qc).
QC_CHECKS = loft.CHECKS


def qc_settings():
    """The QC options this user saved (defaults for the rest); Builder's
    Publish of a Loft item uses the same ones."""
    return datatypes.qc_settings(loft)


def save_qc_setting(key, option, value):
    """Save one QC option for this user."""
    datatypes.save_qc_setting(loft, key, option, value)


def run_qc(selection, settings=None):
    """Run the loft checks on the NURBS surfaces in ``selection`` (long
    names; a shape or CV stands for its surface). Returns ``(check,
    problems)`` pairs. Changes nothing. Raises ``ValueError`` if no surfaces
    are selected."""
    if not loft.surfaces(selection):
        raise ValueError("No NURBS surfaces selected. Select the lofted surfaces to check.")
    return datatypes.run_qc(loft, selection, settings)


def select_problem(problem):
    """Select what ``problem`` points at that's still in the scene."""
    return checks.select_problem(problem)
