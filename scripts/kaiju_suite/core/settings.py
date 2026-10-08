"""Per-user settings persisted in Maya optionVars."""

from maya import cmds

PREFIX = "kaiju_suite"


def _key(tool, name):
    return f"{PREFIX}_{tool}_{name}"


def get(tool, name, default=None):
    key = _key(tool, name)
    if not cmds.optionVar(exists=key):
        return default
    return cmds.optionVar(query=key)


def set(tool, name, value):
    key = _key(tool, name)
    if isinstance(value, bool):
        cmds.optionVar(intValue=(key, int(value)))
    elif isinstance(value, int):
        cmds.optionVar(intValue=(key, value))
    elif isinstance(value, float):
        cmds.optionVar(floatValue=(key, value))
    else:
        cmds.optionVar(stringValue=(key, str(value)))


def remove(tool, name):
    cmds.optionVar(remove=_key(tool, name))
