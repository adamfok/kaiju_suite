"""ProximityWrap Tool: QC for the proximityWraps on meshes. No Qt.

The checks live in :data:`kaiju_suite.datatypes.proximity_wrap.CHECKS`, so
Scripter's Publish of a ProximityWrap item runs them too. :func:`run_qc`
runs them on the selected meshes; :func:`select_problem` selects the nodes
a problem points at. Nothing here changes the scene, so there's nothing to
undo.
"""

from kaiju_suite import datatypes
from kaiju_suite.core import checks
from kaiju_suite.datatypes import proximity_wrap

# Per-user settings (optionVars) are kept under this name.
SETTINGS_KEY = "proximitywrap_tool"
# The checks the QC tab runs (see run_qc).
QC_CHECKS = proximity_wrap.CHECKS


def qc_settings():
    """The QC options this user saved (defaults for the rest); Scripter's
    Publish of a ProximityWrap item uses the same ones."""
    return datatypes.qc_settings(proximity_wrap)


def save_qc_setting(key, option, value):
    """Save one QC option for this user."""
    datatypes.save_qc_setting(proximity_wrap, key, option, value)


def run_qc(selection, settings=None):
    """Run the proximityWrap checks on the meshes in ``selection`` (long
    names; a shape or component stands for its mesh). Returns ``(check,
    problems)`` pairs. Changes nothing. Raises ``ValueError`` if no meshes
    are selected."""
    if not selection or not datatypes.meshes(selection):
        raise ValueError("No meshes selected. Select the meshes with a proximityWrap to check.")
    return datatypes.run_qc(proximity_wrap, selection, settings)


def select_problem(problem):
    """Select what ``problem`` points at that's still in the scene."""
    return checks.select_problem(problem)
