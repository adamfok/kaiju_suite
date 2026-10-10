"""Custom attributes and channel lock/hide state, read as data and applied back.

Shared by the Assembler's Attributes product and any tool that manages
attributes. A custom attribute is a dict::

    {"name": "ikFk", "type": "double", "min": 0.0, "max": 1.0, "default": 1.0,
     "keyable": True, "channel_box": False, "locked": False}

``min``/``max`` are ``None`` when not set; enums add ``enum`` (``"a:b"`` or
``"a=0:b=5"``); strings have no ``default``. Angle and distance limits and defaults are in
Maya's internal units (radians, centimeters), as ``addAttr`` takes them. A standard channel's state is
``{"locked", "keyable", "channel_box"}``. Values aren't read or written:
applying a record never changes what an attribute is set to. No Qt here.
"""

from maya import cmds

STANDARD_CHANNELS = tuple(f"{a}{x}" for a in ("translate", "rotate", "scale") for x in "XYZ") + ("visibility",)

# Scalar attribute types that can be read and applied.
NUMERIC_TYPES = ("double", "float", "doubleLinear", "doubleAngle", "long", "short", "byte")
SUPPORTED_TYPES = NUMERIC_TYPES + ("bool", "enum", "string")
_INT_TYPES = ("long", "short", "byte", "enum")
_DIGITS = 6


def _plug(node, attr):
    return f"{node}.{attr}"


def _exists(node, attr):
    return cmds.attributeQuery(attr, node=node, exists=True)


def _type(node, attr):
    return cmds.getAttr(_plug(node, attr), type=True)


def _number(value, kind):
    if kind == "bool":
        return bool(value)
    if kind in _INT_TYPES:
        return int(round(value))
    return round(float(value), _DIGITS)


def custom_attributes(node):
    """``node``'s user-defined attributes of a supported type, in the order
    they were added. Compound attributes and their children are left out."""
    names = cmds.listAttr(node, userDefined=True) or []
    found = []
    for name in names:
        if "." in name or not _exists(node, name):
            continue
        if cmds.attributeQuery(name, node=node, listParent=True):
            continue
        if _type(node, name) in SUPPORTED_TYPES:
            found.append(name)
    return found


def _state(node, attr):
    plug = _plug(node, attr)
    return {
        "keyable": bool(cmds.getAttr(plug, keyable=True)),
        "channel_box": bool(cmds.getAttr(plug, channelBox=True)),
        "locked": bool(cmds.getAttr(plug, lock=True)),
    }


def _limits(node, attr, kind):
    """``{"min": ..., "max": ...}``, ``None`` where not set. Read with
    ``addAttr`` (not ``attributeQuery``) so angles come back in the units
    ``addAttr`` takes them in."""
    plug = _plug(node, attr)
    limits = {}
    for key, has, value in (("min", "hasMinValue", "minValue"), ("max", "hasMaxValue", "maxValue")):
        set_ = cmds.addAttr(plug, query=True, **{has: True})
        limits[key] = _number(cmds.addAttr(plug, query=True, **{value: True}), kind) if set_ else None
    return limits


def read_attribute(node, attr):
    """The record of custom attribute ``attr`` on ``node``, or ``None`` if its
    type isn't supported."""
    kind = _type(node, attr)
    if kind not in SUPPORTED_TYPES:
        return None
    record = {"name": attr, "type": kind}
    if kind != "string":
        if kind in NUMERIC_TYPES:
            record.update(_limits(node, attr, kind))
        if kind == "enum":
            record["enum"] = cmds.attributeQuery(attr, node=node, listEnum=True)[0]
        record["default"] = _number(cmds.addAttr(_plug(node, attr), query=True, defaultValue=True), kind)
    record.update(_state(node, attr))
    return record


def read_channels(node):
    """The lock/keyable/channel box state of ``node``'s standard channels
    (translate, rotate, scale, visibility) that it has."""
    channels = {}
    for attr in STANDARD_CHANNELS:
        if _exists(node, attr):
            state = _state(node, attr)
            channels[attr] = {k: state[k] for k in ("locked", "keyable", "channel_box")}
    return channels


def read_node(node):
    """``{"attributes": [...], "channels": {...}}`` for ``node``."""
    records = [read_attribute(node, attr) for attr in custom_attributes(node)]
    return {"attributes": [r for r in records if r], "channels": read_channels(node)}


def attribute_problems(node, record):
    """Why ``record`` can't be applied to ``node``, as messages (empty if it can)."""
    name, kind = record["name"], record.get("type")
    plug = _plug(node, name)
    if kind not in SUPPORTED_TYPES:
        return [f"{plug}: unsupported attribute type {kind!r}"]
    if not _exists(node, name):
        return []
    if name not in (cmds.listAttr(node, userDefined=True) or []):
        return [f"{plug} is a built-in attribute, not a custom one"]
    current = _type(node, name)
    if current != kind:
        return [f"{plug} is a {current} attribute, the file has {kind}"]
    return []


def _set_state(node, attr, state):
    plug = _plug(node, attr)
    if "keyable" in state:
        cmds.setAttr(plug, keyable=state["keyable"])
    if "channel_box" in state and not state.get("keyable"):
        cmds.setAttr(plug, channelBox=state["channel_box"])
    if "locked" in state:
        cmds.setAttr(plug, lock=state["locked"])


def apply_attribute(node, record):
    """Add custom attribute ``record`` to ``node``, or update the one it has,
    then set its keyable, channel box and lock state. Returns ``"added"`` or
    ``"updated"``. Check :func:`attribute_problems` first."""
    name, kind = record["name"], record["type"]
    plug = _plug(node, name)
    if _exists(node, name):
        result = "updated"
        cmds.setAttr(plug, lock=False)
        current = read_attribute(node, name)
        edit = {}
        if kind in NUMERIC_TYPES:
            for key, has, value in (("min", "hasMinValue", "minValue"), ("max", "hasMaxValue", "maxValue")):
                if record.get(key) == current[key]:
                    continue
                # Setting a limit turns it on. Pass hasMinValue only to turn
                # one off: with it, Maya's undo doesn't restore the old limit.
                if record.get(key) is None:
                    edit[has] = False
                else:
                    edit[value] = record[key]
        if kind == "enum" and record["enum"] != current["enum"]:
            edit["enumName"] = record["enum"]
        if kind != "string" and record["default"] != current["default"]:
            edit["defaultValue"] = record["default"]
        if edit:
            cmds.addAttr(plug, edit=True, **edit)
    else:
        result = "added"
        if kind == "string":
            cmds.addAttr(node, longName=name, dataType="string")
        else:
            kwargs = {"longName": name, "attributeType": kind, "defaultValue": record["default"]}
            if kind == "enum":
                kwargs["enumName"] = record["enum"]
            if record.get("min") is not None:
                kwargs["minValue"] = record["min"]
            if record.get("max") is not None:
                kwargs["maxValue"] = record["max"]
            cmds.addAttr(node, **kwargs)
    _set_state(node, name, record)
    return result


def apply_channels(node, channels):
    """Set the lock/keyable/channel box state of standard channels from
    ``channels`` (as :func:`read_channels` returns). Channels ``node``
    doesn't have are skipped; ones not in ``channels`` are left alone."""
    for attr, state in channels.items():
        if _exists(node, attr):
            _set_state(node, attr, state)
