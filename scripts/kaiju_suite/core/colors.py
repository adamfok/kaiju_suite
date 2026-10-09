"""Maya's index colors (Drawing Overrides' Color, 0 to 31). No Qt here."""

from maya import cmds

# 0 means "no override": Maya's default color.
COLORS = range(32)

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
