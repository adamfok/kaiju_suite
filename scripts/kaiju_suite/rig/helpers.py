"""Shared pieces for rig modules: checking names, nodes and joint chains, and
building groups and colored control curves. Imports only Maya, no Qt."""

import re
from contextlib import contextmanager

from maya import cmds
from maya.api import OpenMaya as om

NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# -- checks -----------------------------------------------------------------


def name_problems(name, group, module_name):
    """Problems with ``name`` as the prefix of a module's nodes, whose top
    group would be ``group``; ``module_name`` says which kind of module."""
    if not NAME.match(name):
        return [f"Name {name!r} can't be used in node names: use letters, digits and _, not starting with a digit."]
    if cmds.objExists(group):
        return [f"{group} already exists: another {module_name} is named {name}. Pick another name."]
    return []


def node_problems(label, name, joint=False):
    """Problems finding one node named ``name``: a joint if ``joint``, else a
    transform. ``label`` names the parameter in the messages."""
    matches = cmds.ls(name, long=True) or []
    if not matches:
        return [f"{label} {name!r} isn't in the scene."]
    if len(matches) > 1:
        return [f"Several nodes are named {name!r} ({', '.join(matches)}); the {label.lower()} needs a unique name."]
    if joint and cmds.nodeType(matches[0]) != "joint":
        return [f"{label} {name!r} is not a joint."]
    if not joint and not cmds.objectType(matches[0], isAType="transform"):
        return [f"{label} {name!r} is not a transform."]
    return []


def parent_problems(parent):
    """Problems with an optional ``parent`` parameter; blank is fine."""
    parent = parent.strip()
    return node_problems("Parent", parent) if parent else []


def chain(start, end):
    """Long paths from ``start`` down to ``end``, both included, or ``None``
    if ``end`` isn't ``start`` or below it."""
    start_path, end_path = cmds.ls(start, long=True)[0], cmds.ls(end, long=True)[0]
    if end_path != start_path and not end_path.startswith(start_path + "|"):
        return None
    nodes = [end_path]
    while nodes[-1] != start_path:
        nodes.append(cmds.listRelatives(nodes[-1], parent=True, fullPath=True)[0])
    return nodes[::-1]


def chain_problems(start, end, minimum):
    """Problems with a joint chain from ``start`` down to ``end`` holding at
    least ``minimum`` joints, all of them joints."""
    found = node_problems("Start joint", start, joint=True) + node_problems("End joint", end, joint=True)
    if found:
        return found
    nodes = chain(start, end)
    if nodes is None or (len(nodes) == 1 and minimum > 1):
        return [f"End joint {end!r} is not below start joint {start!r}."]
    others = [short(node) for node in nodes if cmds.nodeType(node) != "joint"]
    if others:
        return [f"Everything from start joint to end joint must be a joint; these aren't: {', '.join(others)}."]
    if len(nodes) < minimum:
        return [f"The chain needs at least {minimum} joints from start joint to end joint."]
    return []


# -- building ---------------------------------------------------------------


def world(node):
    """``node``'s world-space position, as an ``MVector``."""
    return om.MVector(cmds.xform(node, query=True, worldSpace=True, translation=True))


def pole_position(chain, distance):
    """Where a pole vector goes for ``chain`` (start to end): ``distance`` out
    from the middle joint, away from the start-end line, on the chain's
    plane. ``None`` if the chain is straight."""
    start, mid, end = (world(chain[i]) for i in (0, len(chain) // 2, -1))
    line = end - start
    out = (mid - start) - line * (((mid - start) * line) / (line * line))
    if out.length() < 1e-4 * line.length():
        return None
    return mid + out.normal() * distance


def short(node):
    """The shortest unique name of ``node``."""
    return cmds.ls(node)[0]


def group(name, parent=None):
    """An empty transform named ``name``, under ``parent`` or the world."""
    node = cmds.createNode("transform", name=name, parent=parent or None, skipSelect=True)
    return short(node)


def _curve(name, parent, points, degree=1):
    curve = cmds.curve(name=name, degree=degree, point=points)
    return cmds.parent(curve, parent, relative=True)[0]


def circle(name, size, parent, normal=(1, 0, 0)):
    """A circle control of radius ``size`` facing ``normal``, under ``parent``."""
    curve = cmds.circle(name=name, normal=normal, radius=size, constructionHistory=False)[0]
    return cmds.parent(curve, parent, relative=True)[0]


def diamond(name, size, parent):
    """A diamond control ``size`` across, under ``parent``; e.g. a pole vector."""
    s = size * 0.5
    points = [(0, s, 0), (s, 0, 0), (0, -s, 0), (-s, 0, 0), (0, s, 0), (0, 0, s), (0, -s, 0), (0, 0, -s), (0, s, 0)]
    return _curve(name, parent, points)


def box(name, size, parent):
    """A cube control ``size`` across, under ``parent``."""
    s = size * 0.5
    points = [
        (-s, s, s), (s, s, s), (s, s, -s), (-s, s, -s), (-s, s, s),
        (-s, -s, s), (s, -s, s), (s, s, s), (s, -s, s), (s, -s, -s),
        (s, s, -s), (s, -s, -s), (-s, -s, -s), (-s, s, -s), (-s, -s, -s), (-s, -s, s),
    ]  # fmt: skip
    return _curve(name, parent, points)


def set_color(control, color):
    """Give every curve shape under ``control`` Maya index color ``color``
    (a "color" parameter); 0 leaves Maya's default color."""
    if not color:
        return
    for shape in cmds.listRelatives(control, shapes=True, fullPath=True, type="nurbsCurve") or []:
        cmds.setAttr(f"{shape}.overrideEnabled", True)
        cmds.setAttr(f"{shape}.overrideColor", color)


@contextmanager
def kept_selection():
    """Put the selection back as it was when the block ends."""
    selection = cmds.ls(selection=True, long=True)
    try:
        yield
    finally:
        existing = [node for node in selection if cmds.objExists(node)]
        cmds.select(existing, replace=True) if existing else cmds.select(clear=True)
