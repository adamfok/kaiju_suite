from maya import cmds


def selected(node_type=None, long=True):
    """Return the current selection, optionally filtered by node type."""
    kwargs = {"selection": True, "long": long}
    if node_type:
        kwargs["type"] = node_type
    return cmds.ls(**kwargs) or []


def short_name(node):
    """``|grp|pCube1`` -> ``pCube1``."""
    return node.rsplit("|", 1)[-1]
