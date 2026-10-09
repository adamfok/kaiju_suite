"""Rig Module Editor: load, save and check a rig module file's parameters. No Qt."""

from maya import cmds

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


# Maya's default index palette, for when the live one can't be queried
# (``colorIndex`` returns nothing without a UI, e.g. in mayapy).
_DEFAULT_PALETTE = (
    (0.471, 0.471, 0.471), (0.0, 0.0, 0.0), (0.251, 0.251, 0.251), (0.6, 0.6, 0.6),
    (0.608, 0.0, 0.157), (0.0, 0.016, 0.376), (0.0, 0.0, 1.0), (0.0, 0.275, 0.098),
    (0.149, 0.0, 0.263), (0.784, 0.0, 0.784), (0.541, 0.282, 0.2), (0.247, 0.137, 0.122),
    (0.6, 0.149, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.255, 0.6),
    (1.0, 1.0, 1.0), (1.0, 1.0, 0.0), (0.392, 0.863, 1.0), (0.263, 1.0, 0.639),
    (1.0, 0.69, 0.69), (0.894, 0.675, 0.475), (1.0, 1.0, 0.388), (0.0, 0.6, 0.329),
    (0.631, 0.416, 0.188), (0.62, 0.631, 0.188), (0.408, 0.631, 0.188), (0.188, 0.631, 0.365),
    (0.188, 0.631, 0.631), (0.188, 0.404, 0.631), (0.435, 0.188, 0.631), (0.631, 0.188, 0.416),
)  # fmt: skip


def color_rgb(index):
    """Maya index color ``index`` as ``(r, g, b)``, each 0 to 1, from the
    user's palette when Maya can say, else Maya's default one."""
    if index > 0:
        rgb = cmds.colorIndex(index, query=True)
        if rgb:
            return tuple(rgb)
    return _DEFAULT_PALETTE[index]


def problems(module, params):
    """Why ``params`` can't be built in the current scene, as messages."""
    return module.problems(params)
