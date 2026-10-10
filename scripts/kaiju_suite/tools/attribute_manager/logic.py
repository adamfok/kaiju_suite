"""Attribute Manager: add, rename, reorder, lock/hide and delete custom
attributes on many nodes at once, add separator attributes, and apply
lock-and-hide presets. No Qt here.

Every function takes a list of nodes, works on each one that has what it
needs, and returns a :data:`Result` naming the nodes it changed and a
message for each one it skipped. Every scene edit is one undo step.

Maya has no command to reorder attributes: the channel box lists custom
attributes in the order they were added. :func:`reorder` recreates each
attribute that has to move, in the new order, copying its settings, value,
lock state and connections (animation curves included) onto the new one.
"""

import re
from collections import namedtuple

from maya import cmds

from kaiju_suite.core.selection import short_name
from kaiju_suite.core.undo import undoable

Result = namedtuple("Result", "changed skipped")
Preset = namedtuple("Preset", "attrs lock hide")

KINDS = ("float", "int", "bool", "enum", "string")
_ATTRIBUTE_TYPES = {"float": "double", "int": "long", "bool": "bool", "enum": "enum"}

SEPARATOR_PREFIX = "sep_"
SEPARATOR_VALUE = "__________"

_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_T = ("translateX", "translateY", "translateZ")
_R = ("rotateX", "rotateY", "rotateZ")
_S = ("scaleX", "scaleY", "scaleZ")
_V = ("visibility",)

# One-click presets, in the order the window shows them.
PRESETS = {
    "Lock and Hide Scale + Visibility": Preset(_S + _V, True, True),
    "Lock and Hide Translate": Preset(_T, True, True),
    "Lock and Hide Rotate": Preset(_R, True, True),
    "Lock and Hide Scale": Preset(_S, True, True),
    "Lock and Hide Visibility": Preset(_V, True, True),
    "Unlock and Show Transforms": Preset(_T + _R + _S + _V, False, False),
}

# Types reorder knows how to recreate: attributeType ones, then dataType ones.
_NUMERIC = {"bool", "long", "short", "byte", "char", "enum", "float", "double", "doubleLinear", "doubleAngle", "time"}
_DATA = {"string", "matrix"}


def _check_name(name):
    if not isinstance(name, str) or not _NAME.match(name):
        raise ValueError(
            f"{name!r} isn't a valid attribute name: use letters, digits and underscores, not starting with a digit."
        )


def _has(node, attr):
    return cmds.attributeQuery(attr, node=node, exists=True)


# -- listing -------------------------------------------------------------------


def custom_attributes(node):
    """``node``'s custom attributes in channel box order (a compound's
    children are left out; the compound stands for them)."""
    found = []
    for attr in cmds.listAttr(node, userDefined=True) or []:
        if "." in attr or cmds.attributeQuery(attr, node=node, listParent=True):
            continue
        found.append(attr)
    return found


def is_separator(node, attr):
    """Whether ``node.attr`` is a separator made by :func:`add_separator`."""
    if not attr.startswith(SEPARATOR_PREFIX.rstrip("_")) or not _has(node, attr):
        return False
    plug = f"{node}.{attr}"
    return cmds.getAttr(plug, type=True) == "enum" and cmds.getAttr(plug, lock=True)


def describe(node, attr):
    """A short summary of ``node.attr`` for the window: type and flags."""
    plug = f"{node}.{attr}"
    if is_separator(node, attr):
        return "separator"
    kind = cmds.getAttr(plug, type=True)
    flags = []
    if cmds.getAttr(plug, lock=True):
        flags.append("locked")
    if not cmds.getAttr(plug, keyable=True):
        flags.append("shown" if cmds.getAttr(plug, channelBox=True) else "hidden")
    return ", ".join([kind] + flags)


# -- adding --------------------------------------------------------------------


@undoable
def add_attribute(nodes, name, kind, minimum=None, maximum=None, default=None, keyable=True, enum_names=None):
    """Add a ``kind`` attribute (one of :data:`KINDS`) called ``name`` to
    each node that doesn't have one already. ``minimum``/``maximum`` apply
    to float and int, ``enum_names`` to enum (``default`` is then an index).
    A non-keyable attribute still shows in the channel box."""
    _check_name(name)
    if kind not in KINDS:
        raise ValueError(f"Unknown attribute type {kind!r}: use one of {', '.join(KINDS)}.")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError(f"The minimum ({minimum}) is above the maximum ({maximum}).")
    if kind == "enum" and not [n for n in enum_names or [] if n.strip()]:
        raise ValueError("An enum attribute needs at least one name.")

    changed, skipped = [], []
    for node in nodes:
        if _has(node, name):
            skipped.append(f"{short_name(node)} already has {name}")
            continue
        if kind == "string":
            cmds.addAttr(node, longName=name, dataType="string")
            if default is not None:
                cmds.setAttr(f"{node}.{name}", str(default), type="string")
        else:
            kwargs = {"longName": name, "attributeType": _ATTRIBUTE_TYPES[kind], "keyable": keyable}
            if kind == "enum":
                kwargs["enumName"] = ":".join(n.strip() for n in enum_names if n.strip())
            if kind in ("float", "int"):
                if minimum is not None:
                    kwargs["minValue"] = minimum
                if maximum is not None:
                    kwargs["maxValue"] = maximum
            if default is not None:
                kwargs["defaultValue"] = default
            cmds.addAttr(node, **kwargs)
            if not keyable:
                cmds.setAttr(f"{node}.{name}", channelBox=True)
        changed.append(node)
    return Result(changed, skipped)


def _separator_name(node, label):
    base = SEPARATOR_PREFIX + re.sub(r"\W", "_", label.strip()) if label.strip() else SEPARATOR_PREFIX.rstrip("_")
    name, i = base, 1
    while _has(node, name):
        name, i = f"{base}{i}", i + 1
    return name


@undoable
def add_separator(nodes, label=""):
    """Add a divider to each node's channel box: a locked, non-keyable enum
    whose nice name is ``label`` and whose value is a row of underscores."""
    changed = []
    for node in nodes:
        name = _separator_name(node, label)
        cmds.addAttr(
            node,
            longName=name,
            niceName=label.strip() or SEPARATOR_VALUE,
            attributeType="enum",
            enumName=SEPARATOR_VALUE,
        )
        plug = f"{node}.{name}"
        cmds.setAttr(plug, keyable=False, channelBox=True)
        cmds.setAttr(plug, lock=True)
        changed.append(node)
    return Result(changed, [])


# -- renaming ------------------------------------------------------------------


@undoable
def rename_attribute(nodes, old, new):
    """Rename ``old`` to ``new`` on each node that has ``old`` and not ``new``.
    Values and connections are kept."""
    _check_name(new)
    changed, skipped = [], []
    for node in nodes:
        if not _has(node, old):
            skipped.append(f"{short_name(node)} has no {old}")
        elif _has(node, new):
            skipped.append(f"{short_name(node)} already has {new}")
        else:
            cmds.renameAttr(f"{node}.{old}", new)
            changed.append(node)
    return Result(changed, skipped)


# -- reordering ----------------------------------------------------------------


def _unsupported(node, attr):
    """Why ``node.attr`` can't be recreated, or None."""
    if cmds.attributeQuery(attr, node=node, multi=True):
        return f"{short_name(node)}.{attr} is a multi attribute"
    if cmds.attributeQuery(attr, node=node, listChildren=True):
        return f"{short_name(node)}.{attr} is a compound attribute"
    kind = cmds.getAttr(f"{node}.{attr}", type=True)
    if kind not in _NUMERIC | _DATA | {"message"}:
        return f"{short_name(node)}.{attr} is a {kind} attribute"
    return None


def _query(node, attr, **flag):
    return cmds.attributeQuery(attr, node=node, **flag)


def _capture(node, attr):
    """Everything needed to recreate ``node.attr``."""
    plug = f"{node}.{attr}"
    kind = cmds.getAttr(plug, type=True)
    record = {
        "kind": kind,
        "long": attr,
        "short": _query(node, attr, shortName=True),
        "nice": _query(node, attr, niceName=True),
        "hidden": _query(node, attr, hidden=True),
        "keyable": cmds.getAttr(plug, keyable=True),
        "channelBox": cmds.getAttr(plug, channelBox=True),
        "lock": cmds.getAttr(plug, lock=True),
        "incoming": cmds.listConnections(plug, source=True, destination=False, plugs=True) or [],
        "outgoing": cmds.listConnections(plug, source=False, destination=True, plugs=True) or [],
        "value": None,
        "range": {},
    }
    if kind in _NUMERIC:
        for exists, flag, key in (
            ("minExists", "minimum", "minValue"),
            ("maxExists", "maximum", "maxValue"),
            ("softMinExists", "softMin", "softMinValue"),
            ("softMaxExists", "softMax", "softMaxValue"),
        ):
            if _query(node, attr, **{exists: True}):
                record["range"][key] = _query(node, attr, **{flag: True})[0]
        record["default"] = _query(node, attr, listDefault=True)[0]
        if kind == "enum":
            record["enum"] = _query(node, attr, listEnum=True)[0]
        record["value"] = cmds.getAttr(plug)
    elif kind in _DATA:
        record["value"] = cmds.getAttr(plug)
    return record


def _recreate(node, record):
    attr, kind = record["long"], record["kind"]
    plug = f"{node}.{attr}"
    kwargs = {"longName": attr, "shortName": record["short"], "hidden": record["hidden"]}
    if kind in _DATA:
        kwargs["dataType"] = kind
    else:
        kwargs["attributeType"] = kind
    if kind in _NUMERIC:
        kwargs["keyable"] = record["keyable"]
        kwargs["defaultValue"] = record["default"]
        kwargs.update(record["range"])
        if kind == "enum":
            kwargs["enumName"] = record["enum"]
    cmds.addAttr(node, **kwargs)
    # Set the nice name only if it was customised, so an automatic one
    # keeps following renames.
    if _query(node, attr, niceName=True) != record["nice"]:
        cmds.addAttr(plug, edit=True, niceName=record["nice"])
    if kind in _NUMERIC:
        cmds.setAttr(plug, keyable=record["keyable"])
        if not record["keyable"]:
            cmds.setAttr(plug, channelBox=record["channelBox"])
    if record["value"] is not None and not record["incoming"]:
        if kind == "string":
            cmds.setAttr(plug, record["value"], type="string")
        elif kind == "matrix":
            cmds.setAttr(plug, record["value"], type="matrix")
        else:
            cmds.setAttr(plug, record["value"])
    # A connection to another attribute being recreated is made by whichever
    # of the two comes back last.
    for source in record["incoming"]:
        if cmds.objExists(source) and not cmds.isConnected(source, plug):
            cmds.connectAttr(source, plug, force=True)
    for destination in record["outgoing"]:
        if cmds.objExists(destination) and not cmds.isConnected(plug, destination):
            cmds.connectAttr(plug, destination, force=True)
    if record["lock"]:
        cmds.setAttr(plug, lock=True)


def _reorder(node, order):
    current = custom_attributes(node)
    if sorted(order) != sorted(current):
        raise ValueError(f"The new order for {short_name(node)} must list each of its custom attributes once.")
    start = next((i for i, (a, b) in enumerate(zip(current, order)) if a != b), len(order))
    moving = order[start:]
    problems = [p for p in (_unsupported(node, attr) for attr in moving) if p]
    if problems:
        raise ValueError("Can't reorder: " + "; ".join(problems) + ".")
    records = [_capture(node, attr) for attr in moving]
    # Delete them all, last first, then add them back in the new order. Undo
    # brings a deleted attribute back at the end of the list, so deleting in
    # reverse makes one undo restore the old order too.
    for attr in reversed(current[start:]):
        plug = f"{node}.{attr}"
        cmds.setAttr(plug, lock=False)
        cmds.deleteAttr(plug)
    for record in records:
        _recreate(node, record)


@undoable
def reorder(node, order):
    """Put ``node``'s custom attributes in ``order``, which lists each once.
    Only attributes from the first one out of place onwards are recreated."""
    _reorder(node, list(order))


def _moved(order, attrs, direction):
    """``order`` with each of ``attrs`` moved one place (``direction`` -1 is
    up, 1 is down), stopping at the ends; a block of them moves together."""
    order = list(order)
    indices = range(len(order)) if direction < 0 else range(len(order) - 1, -1, -1)
    for i in indices:
        j = i + direction
        if order[i] in attrs and 0 <= j < len(order) and order[j] not in attrs:
            order[i], order[j] = order[j], order[i]
    return order


@undoable
def move_attributes(nodes, attrs, direction):
    """Move ``attrs`` one place up (``direction`` -1) or down (1) in each
    node's channel box. Every node is checked before any changes."""
    changed, skipped, plans = [], [], []
    for node in nodes:
        current = custom_attributes(node)
        present = [a for a in attrs if a in current]
        if not present:
            skipped.append(f"{short_name(node)} has none of {', '.join(attrs)}")
            continue
        order = _moved(current, set(present), direction)
        if order == current:
            continue
        start = next(i for i, (a, b) in enumerate(zip(current, order)) if a != b)
        problems = [p for p in (_unsupported(node, attr) for attr in order[start:]) if p]
        if problems:
            raise ValueError("Can't reorder: " + "; ".join(problems) + ".")
        plans.append((node, order))
    for node, order in plans:
        _reorder(node, order)
        changed.append(node)
    return Result(changed, skipped)


# -- lock / hide ---------------------------------------------------------------


def _each_plug(nodes, attrs, change):
    changed, skipped = [], []
    for node in nodes:
        done = False
        for attr in attrs:
            if _has(node, attr):
                change(node, attr)
                done = True
            else:
                skipped.append(f"{short_name(node)} has no {attr}")
        if done:
            changed.append(node)
    return Result(changed, skipped)


@undoable
def set_locked(nodes, attrs, locked):
    """Lock (or unlock) ``attrs`` on each node that has them."""
    return _each_plug(nodes, attrs, lambda node, attr: cmds.setAttr(f"{node}.{attr}", lock=locked))


def _set_hidden(node, attr, hidden):
    plug = f"{node}.{attr}"
    if hidden:
        cmds.setAttr(plug, keyable=False, channelBox=False)
    elif is_separator(node, attr):
        cmds.setAttr(plug, channelBox=True)
    else:
        cmds.setAttr(plug, keyable=True)


@undoable
def set_hidden(nodes, attrs, hidden):
    """Hide ``attrs`` from the channel box (not keyable, not shown), or show
    them again as keyable; a separator comes back shown but not keyable."""
    return _each_plug(nodes, attrs, lambda node, attr: _set_hidden(node, attr, hidden))


@undoable
def apply_preset(nodes, name):
    """Apply the preset called ``name`` (see :data:`PRESETS`) to each node."""
    preset = PRESETS[name]

    def change(node, attr):
        cmds.setAttr(f"{node}.{attr}", lock=preset.lock)
        _set_hidden(node, attr, preset.hide)

    return _each_plug(nodes, preset.attrs, change)


# -- deleting ------------------------------------------------------------------


@undoable
def delete_attributes(nodes, attrs):
    """Delete the custom ``attrs`` from each node, locked or connected ones
    too. Built-in attributes are skipped."""
    changed, skipped = [], []
    for node in nodes:
        custom = set(custom_attributes(node))
        done = False
        for attr in attrs:
            if attr in custom:
                plug = f"{node}.{attr}"
                cmds.setAttr(plug, lock=False)
                cmds.deleteAttr(plug)
                done = True
            elif _has(node, attr):
                skipped.append(f"{short_name(node)}.{attr} isn't a custom attribute")
            else:
                skipped.append(f"{short_name(node)} has no {attr}")
        if done:
            changed.append(node)
    return Result(changed, skipped)
