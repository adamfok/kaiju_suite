"""Mesh Tool: QC for meshes, with fixes for some problems. No Qt.

The checks live in :data:`kaiju_suite.datatypes.mesh.CHECKS`, so Scripter's
Publish of a Mesh item runs them too. :func:`run_qc` runs them on the
selected meshes; :func:`fix_and_check` repairs what one check finds, as one
undo step, and runs them again; :func:`select_problem` selects the faces,
edges, vertices or meshes a problem points at.
"""

from kaiju_suite import datatypes
from kaiju_suite.core import checks
from kaiju_suite.core.undo import undoable
from kaiju_suite.datatypes import mesh as mesh_data

# Per-user settings (optionVars) are kept under this name.
SETTINGS_KEY = "mesh_tool"
# The checks the QC tab runs (see run_qc).
QC_CHECKS = mesh_data.CHECKS


def qc_settings():
    """The QC options this user saved (defaults for the rest); Scripter's
    Publish of a Mesh item uses the same ones."""
    return datatypes.qc_settings(mesh_data)


def save_qc_setting(key, option, value):
    """Save one QC option for this user."""
    datatypes.save_qc_setting(mesh_data, key, option, value)


def run_qc(selection, settings=None):
    """Run the mesh checks on the meshes in ``selection`` (long names; a
    shape or component stands for its mesh). Returns ``(check, problems)``
    pairs. Changes nothing. Raises ``ValueError`` if no meshes are selected."""
    if not selection or not datatypes.meshes(selection):
        raise ValueError("No meshes selected. Select the meshes to check.")
    return datatypes.run_qc(mesh_data, selection, settings)


@undoable
def fix(key, selection):
    """Repair what check ``key`` finds on the meshes in ``selection``, as one
    undo step. Raises ``ValueError`` for a check that can't fix."""
    check = checks.get(key, QC_CHECKS)
    if not check.fix:
        raise ValueError(f"{check.label} can't be fixed automatically.")
    check.fix(selection)


def fix_and_check(key, selection):
    """:func:`fix`, then :func:`run_qc` again on ``selection``."""
    fix(key, selection)
    return run_qc(selection)


def select_problem(problem):
    """Select what ``problem`` points at that's still in the scene."""
    return checks.select_problem(problem)
