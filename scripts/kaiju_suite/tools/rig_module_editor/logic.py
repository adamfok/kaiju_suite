"""Rig Module Editor: load, save and check a rig module file's parameters. No Qt."""

from maya import cmds

from kaiju_suite.core.colors import color_rgb  # noqa: F401  (re-exported for the editor)
from kaiju_suite.rig import spec
from kaiju_suite.rig.module import COLORS  # noqa: F401  (the editor's color list)


def load(path):
    """``(module, params)`` for the file at ``path``, params completed with
    the module's defaults."""
    return spec.load(path)


def save(path, module, params):
    """Write ``params`` for ``module`` to ``path``."""
    return spec.write(path, module.key, dict(params))


def matches_file(path, module, params):
    """Whether ``path`` holds ``module`` with these ``params``, e.g. to tell
    the editor's own save from a version restored on disk. ``False`` if the
    file can't be read."""
    try:
        saved_module, saved = spec.load(path)
    except (OSError, ValueError, LookupError):
        return False
    return saved_module is module and saved == module.complete(params)


def pick_selection():
    """The first selected node's name, as short as stays unique (``wrist``, or
    ``L_arm|wrist`` if several nodes are named ``wrist``)."""
    selection = cmds.ls(selection=True)
    if not selection:
        raise ValueError("Nothing selected. Select the node to use, then click <<.")
    return selection[0]


def problems(module, params):
    """Why ``params`` can't be built in the current scene, as messages."""
    return module.problems(params)
