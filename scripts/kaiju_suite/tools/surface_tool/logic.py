"""Surface Tool: QC for NURBS surfaces. No Qt.

The checks live in :data:`kaiju_suite.datatypes.nurbs_surface.CHECKS`, so
Scripter's Publish of a NurbsSurface item runs them too. :func:`run_qc` runs
them on the selected surfaces; :func:`select_problem` selects the surfaces
or CVs a problem points at. Nothing here changes the scene, so there's
nothing to undo.
"""

from kaiju_suite import datatypes
from kaiju_suite.core import checks
from kaiju_suite.datatypes import nurbs_surface

# Per-user settings (optionVars) are kept under this name.
SETTINGS_KEY = "surface_tool"
# The checks the QC tab runs (see run_qc).
QC_CHECKS = nurbs_surface.CHECKS


def qc_settings():
    """The QC options this user saved (defaults for the rest); Scripter's
    Publish of a NurbsSurface item uses the same ones."""
    return datatypes.qc_settings(nurbs_surface)


def save_qc_setting(key, option, value):
    """Save one QC option for this user."""
    datatypes.save_qc_setting(nurbs_surface, key, option, value)


def run_qc(selection, settings=None):
    """Run the surface checks on the NURBS surfaces in ``selection`` (long
    names; a shape or CV stands for its surface). Returns ``(check,
    problems)`` pairs. Changes nothing. Raises ``ValueError`` if no surfaces
    are selected."""
    if not nurbs_surface.surfaces(selection):
        raise ValueError("No NURBS surfaces selected. Select the NURBS surfaces to check.")
    return datatypes.run_qc(nurbs_surface, selection, settings)


def select_problem(problem):
    """Select what ``problem`` points at that's still in the scene."""
    return checks.select_problem(problem)
