"""Rig controls: what every rig module does to each control it makes, so
pickwalking, selecting every control and resetting them work the same for
all of them. Imports only Maya, no Qt.

:func:`add` makes a node a rig control:

- tags it with a Maya controller node, ``<control>_tag``, whose pickwalk
  parent is the control it's given (Maya's parallel evaluation also treats
  tagged controls better);
- puts it in ``controls_set``, one set for every rig in the scene, and in
  its rig module's set if given (see :func:`module_set_name`), so the controls
  of one arm can be selected together;
- stores its keyable values as built, as JSON in a ``kaijuDefaults`` string
  attribute, so :func:`reset` can put it back.

Call it once the control has every attribute it will get, at the values it
should reset to.
"""

import json

from maya import cmds

from kaiju_suite.core.undo import undoable

SET = "controls_set"
DEFAULTS = "kaijuDefaults"


def add(control, parent=None, rig_module_set=None):
    """Make ``control`` a rig control, its pickwalk parent the control
    ``parent`` if given, also in the set ``module_set`` (made if missing) if
    given. Adding it again keeps the defaults already stored and adds those
    of any new keyable attributes (and keeps its pickwalk parent unless
    given another). Returns ``control``."""
    if tag(control) is None:
        cmds.controller(control)
    if parent:
        cmds.controller(control, parent, parent=True)
    _set(SET, create=True)
    cmds.sets(control, add=SET)
    if rig_module_set:
        cmds.sets(control, add=_set(rig_module_set, create=True))
    _store_defaults(control)
    return control


def rig_module_set_name(group):
    """The name of the set of a rig module's controls, from the rig module's top
    group: ``L_arm_ik_grp`` gives ``L_arm_ik_controls_set``."""
    base = group[: -len("_grp")] if group.endswith("_grp") else group
    return f"{base}_controls_set"


def rig_module_sets(control):
    """The rig module sets ``control`` is in (every controls set but the rig-wide one)."""
    found = cmds.listSets(object=control) or []
    return sorted(s for s in found if s != SET and s.endswith("_controls_set"))


def tag(node):
    """``node``'s controller node, or ``None`` if it isn't tagged."""
    tags = cmds.listConnections(f"{node}.message", type="controller", source=False, destination=True) or []
    return tags[0] if tags else None


def is_control(node):
    """Whether ``node`` is a rig control: tagged, with stored defaults."""
    return tag(node) is not None and cmds.attributeQuery(DEFAULTS, node=node, exists=True)


def pickwalk_parent(control):
    """The control ``control`` pickwalks up to, or ``None``."""
    if tag(control) is None:
        return None
    parent_tag = cmds.controller(control, query=True, parent=True)
    nodes = cmds.listConnections(f"{parent_tag}.controllerObject") if parent_tag else None
    return nodes[0] if nodes else None


def defaults(node):
    """``{attribute: value}`` stored on ``node``; empty if it isn't a control."""
    if not cmds.attributeQuery(DEFAULTS, node=node, exists=True):
        return {}
    return json.loads(cmds.getAttr(f"{node}.{DEFAULTS}") or "{}")


def all_controls():
    """Every rig control in the scene, as long paths."""
    if _set(SET) is None:
        return []
    return cmds.ls(cmds.sets(SET, query=True) or [], long=True)


@undoable
def reset(nodes=None):
    """Put the controls among ``nodes`` (every control if ``None``) back to
    their stored defaults, as one undo step. Nodes that aren't controls are
    skipped, and so are attributes locked or driven since. Returns the
    controls reset, as long paths."""
    nodes = all_controls() if nodes is None else cmds.ls(nodes, long=True)
    done = []
    for node in nodes:
        if not is_control(node):
            continue
        for attr, value in defaults(node).items():
            plug = f"{node}.{attr}"
            if cmds.attributeQuery(attr, node=node, exists=True) and cmds.getAttr(plug, settable=True):
                cmds.setAttr(plug, value)
        done.append(node)
    return done


def _keyable_values(control):
    found = {}
    for attr in cmds.listAttr(control, keyable=True, unlocked=True, scalar=True) or []:
        plug = f"{control}.{attr}"
        if cmds.getAttr(plug, settable=True):
            found[attr] = cmds.getAttr(plug)
    return found


def _store_defaults(control):
    stored = dict(_keyable_values(control), **defaults(control))
    if not cmds.attributeQuery(DEFAULTS, node=control, exists=True):
        cmds.addAttr(control, longName=DEFAULTS, dataType="string")
    cmds.setAttr(f"{control}.{DEFAULTS}", json.dumps(stored), type="string")


def _set(name, create=False):
    if cmds.objExists(name) and cmds.nodeType(name) == "objectSet":
        return name
    if not create:
        return None
    return cmds.sets(name=name, empty=True)
