"""Space switching: what the Space Switch rig module builds on a control, and
switching its space without a pop. Imports only Maya, no Qt.

A space-switching control has a keyable ``space`` enum, one entry per space
(its label), which picks the target of a parent constraint on a group above
the control. :func:`switch` changes the enum and puts the control back where
it was in the world, so the control doesn't jump.

Spaces are written as text, one ``label=node`` per entry, separated by
commas or new lines: ``world=world_space, chest=chest_ctrl``. A bare
``node`` uses the node's name as its label.
"""

import re

from maya import cmds

ATTR = "space"
LABEL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SEPARATOR = re.compile(r"[,\n]")
_TRANSFORM = [f"{channel}{axis}" for channel in ("translate", "rotate", "scale") for axis in "XYZ"]


# -- the spaces text ----------------------------------------------------------


def _entries(text):
    return [entry.strip() for entry in _SEPARATOR.split(text) if entry.strip()]


def parse_spaces(text):
    """``[(label, node), ...]`` from ``text`` (see the module docstring).
    Assumes :func:`spaces_problems` found nothing."""
    pairs = []
    for entry in _entries(text):
        label, _, node = entry.rpartition("=") if "=" in entry else (entry, "", entry)
        pairs.append((label.strip(), node.strip()))
    return pairs


def spaces_problems(text):
    """Problems with ``text`` as a list of spaces, without the scene."""
    entries = _entries(text)
    if not entries:
        return ["Spaces needs at least one space, as label=node (e.g. world=world_space, chest=chest_ctrl)."]
    found = []
    for entry in entries:
        if entry.count("=") > 1:
            found.append(f"Space {entry!r} has more than one =; write each as label=node.")
            continue
        label, node = parse_spaces(entry)[0]
        if not label:
            found.append(f"Space {entry!r} has no label before the =.")
        elif not LABEL.match(label):
            found.append(f"Space label {label!r} can't be used: use letters, digits and _, not starting with a digit.")
        if not node:
            found.append(f"Space {entry!r} has no node after the =.")
    if found:
        return found
    pairs = parse_spaces(text)
    labels = [label for label, _ in pairs]
    found.extend(f"Space {label!r} is listed twice." for label in dict.fromkeys(labels) if labels.count(label) > 1)
    nodes = [node for _, node in pairs]
    found.extend(
        f"{node} is the target of more than one space; each space needs its own node."
        for node in dict.fromkeys(nodes)
        if nodes.count(node) > 1
    )
    return found


# -- a control's spaces ----------------------------------------------------------


def has_spaces(node):
    """Whether ``node`` has a ``space`` enum."""
    return (
        cmds.objExists(node)
        and cmds.attributeQuery(ATTR, node=node, exists=True)
        and cmds.attributeQuery(ATTR, node=node, enum=True)
    )


def spaces(node):
    """The labels of ``node``'s spaces, in enum order; empty if it has none."""
    if not has_spaces(node):
        return []
    names = cmds.attributeQuery(ATTR, node=node, listEnum=True)[0]
    # Entries may carry explicit values ("a=0:b=1"); only the labels matter.
    return [name.split("=")[0] for name in names.split(":")]


def current(node):
    """The label of ``node``'s current space."""
    return spaces(node)[cmds.getAttr(f"{node}.{ATTR}")]


def add_space_attr(control, labels, default=0):
    """Add the keyable ``space`` enum with ``labels`` to ``control``, set to
    ``default`` (an index)."""
    cmds.addAttr(control, longName=ATTR, attributeType="enum", enumName=":".join(labels), defaultValue=default, keyable=True)
    cmds.setAttr(f"{control}.{ATTR}", default)


def drive_weights(control, constraint, prefix):
    """Drive each target weight of ``constraint`` by ``control.space``: 1 when
    the enum is at that target's index, else 0, through condition nodes named
    ``<prefix>_<i>_space_cnd``. Returns the condition nodes."""
    conditions = []
    for index, alias in enumerate(cmds.parentConstraint(constraint, query=True, weightAliasList=True)):
        condition = cmds.createNode("condition", name=f"{prefix}_{index}_space_cnd", skipSelect=True)
        cmds.connectAttr(f"{control}.{ATTR}", f"{condition}.firstTerm")
        cmds.setAttr(f"{condition}.secondTerm", index)
        cmds.setAttr(f"{condition}.operation", 0)  # equal
        cmds.setAttr(f"{condition}.colorIfTrueR", 1)
        cmds.setAttr(f"{condition}.colorIfFalseR", 0)
        cmds.connectAttr(f"{condition}.outColorR", f"{constraint}.{alias}", force=True)
        conditions.append(condition)
    return conditions


# -- switching ------------------------------------------------------------------


def index_of(node, space):
    """The enum index of ``space`` (a label or an index) on ``node``; raises
    ``ValueError`` if ``node`` has no such space."""
    labels = spaces(node)
    if isinstance(space, int) and not isinstance(space, bool):
        if 0 <= space < len(labels):
            return space
    elif space in labels:
        return labels.index(space)
    raise ValueError(f"{node} has no space {space!r} (its spaces: {', '.join(labels) or 'none'}).")


def switch(node, space, key=False):
    """Set ``node``'s space to ``space`` (a label or an index) without moving
    it in the world. With ``key``, key the space and transform channels on
    the frame before the current one (as they were) and on the current one
    (after the switch), the space stepped, so the switch happens on this
    frame with no pop. Not an undo step by itself; wrap callers."""
    index = index_of(node, space)
    channels = [ATTR] + [attr for attr in _TRANSFORM if cmds.getAttr(f"{node}.{attr}", settable=True)]
    if key:
        frame = cmds.currentTime(query=True)
        cmds.setKeyframe(node, attribute=channels, time=(frame - 1,))
    matrix = cmds.xform(node, query=True, worldSpace=True, matrix=True)
    cmds.setAttr(f"{node}.{ATTR}", index)
    cmds.xform(node, worldSpace=True, matrix=matrix)
    if key:
        cmds.setKeyframe(node, attribute=channels, time=(frame,))
        cmds.keyTangent(node, attribute=ATTR, outTangentType="step")
