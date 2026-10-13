"""Rig Module Editor: load, save and check a rig module file's parameters. No Qt."""

from maya import cmds

from kaiju_suite.core.colors import color_rgb  # noqa: F401  (re-exported for the editor)
from kaiju_suite.rigging import spec
from kaiju_suite.rigging.rig_module import COLORS  # noqa: F401  (the editor's color list)


def load(path):
    """``(rig_module, params)`` for the file at ``path``, params completed with
    the rig module's defaults."""
    return spec.load(path)


def save(path, rig_module, params):
    """Write ``params`` for ``rig_module`` to ``path``."""
    return spec.write(path, rig_module.key, dict(params))


def matches_file(path, rig_module, params):
    """Whether ``path`` holds ``rig_module`` with these ``params``, e.g. to tell
    the editor's own save from a version restored on disk. ``False`` if the
    file can't be read."""
    try:
        saved_rig_module, saved = spec.load(path)
    except (OSError, ValueError, LookupError):
        return False
    return saved_rig_module is rig_module and saved == rig_module.complete(params)


def pick_selection():
    """The first selected node's name, as short as stays unique (``wrist``, or
    ``L_arm|wrist`` if several nodes are named ``wrist``)."""
    selection = cmds.ls(selection=True)
    if not selection:
        raise ValueError("Nothing selected. Select the node to use, then click <<.")
    return selection[0]


def problems(rig_module, params):
    """Why ``params`` can't be built in the current scene, as messages."""
    return rig_module.problems(params)
