"""SkinCluster Tool: QC for skinned meshes. The Utilities tab is empty for now. No Qt here.

The QC tab runs the skin checks (:data:`kaiju_suite.datatypes.skin.CHECKS`)
on the selected meshes with :func:`run_qc`, with settings saved per user;
:func:`select_problem` selects what a problem points at.
"""

from kaiju_suite import datatypes
from kaiju_suite.core import checks
from kaiju_suite.datatypes import meshes, skin

# Per-user settings (optionVars) are kept under this name.
SETTINGS_KEY = "skincluster_tool"
# The checks the QC tab runs (see run_qc).
QC_CHECKS = skin.CHECKS


# -- QC ---------------------------------------------------------------------


def qc_settings():
    """The QC settings this user saved (defaults for the rest); Builder's
    Publish of a Skin item uses the same ones."""
    return datatypes.qc_settings(skin)


def save_qc_setting(key, option, value):
    """Save one QC option for this user."""
    datatypes.save_qc_setting(skin, key, option, value)


def run_qc(selection, settings=None):
    """Run the skin checks on the meshes in ``selection`` (long
    names); ``settings`` default to :func:`qc_settings`. Returns ``(check,
    problems)`` pairs. Changes nothing. Raises ``ValueError`` if no meshes
    are selected or the settings are wrong."""
    if not selection or not meshes(selection):
        raise ValueError("No meshes selected. Select the skinned meshes to check.")
    settings = qc_settings() if settings is None else settings
    problems = checks.settings_problems(settings, skin.CHECKS)
    if problems:
        raise ValueError("; ".join(problems))
    return datatypes.run_qc(skin, selection, settings)


def select_problem(problem):
    """Select what ``problem`` points at (vertices, meshes or influences),
    leaving out what's no longer in the scene. Returns what was selected."""
    return checks.select_problem(problem)
