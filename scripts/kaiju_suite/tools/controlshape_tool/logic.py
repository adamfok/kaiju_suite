"""ControlShape Tool: a library of control shapes, and editing the curve
shapes of controls without moving the controls. No Qt here.

A control is a transform with NURBS curve shapes; other shapes under it
(locators, ...) are left alone. Shapes are placed and edited around the
control's rotate pivot, in its own space. Presets are the built-in ones
(:mod:`presets`) plus the user's, saved as Kaiju data files in a library
folder (by default in Maya's user folder). Every scene edit is one undo step.
"""

import copy
import os
import re
from collections import namedtuple

from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.core import curves, datafile
from kaiju_suite.core.naming import opposite_name
from kaiju_suite.core.nodes import unique_name
from kaiju_suite.core.selection import short_name
from kaiju_suite.core.undo import undoable
from kaiju_suite.tools.controlshape_tool.presets import BUILT_IN

KIND = "controlShapePreset"
Result = namedtuple("Result", "changed skipped")

_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_ -]*$")
# Curve data only: what a preset keeps of a shape record.
_GEOMETRY = ("degree", "form", "knots", "cvs")
_MIRROR = om.MMatrix([[-1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])


def transforms(selection):
    """The transforms in ``selection`` (a selected curve shape stands for
    its transform), in order, each once."""
    found = []
    for node in cmds.ls(selection, long=True, objectsOnly=True) or []:
        if cmds.nodeType(node) == "nurbsCurve":
            node = cmds.listRelatives(node, parent=True, fullPath=True)[0]
        if cmds.objectType(node, isAType="transform"):
            found.append(node)
    return list(dict.fromkeys(found))


def controls(selection):
    """Like :func:`transforms`, leaving out those without curve shapes."""
    return [node for node in transforms(selection) if curves.shapes(node)]


# -- library ----------------------------------------------------------------


def default_library():
    """The folder user presets are saved in."""
    return os.path.join(cmds.internalVar(userAppDir=True), "kaiju_suite", "control_shapes")


def _path(name, library):
    return os.path.join(library or default_library(), f"{name}.json")


def _saved(library):
    folder = library or default_library()
    if not os.path.isdir(folder):
        return []
    return sorted(os.path.splitext(f)[0] for f in os.listdir(folder) if f.lower().endswith(".json"))


def preset_names(library=None):
    """The built-in presets, then the saved ones (alphabetical)."""
    return list(BUILT_IN) + [name for name in _saved(library) if name not in BUILT_IN]


def is_built_in(name):
    return name in BUILT_IN


def load_preset(name, library=None):
    """The curve records of preset ``name``; raises ``LookupError`` if there's none."""
    if name in BUILT_IN:
        return copy.deepcopy(BUILT_IN[name])
    path = _path(name, library)
    if not os.path.isfile(path):
        raise LookupError(f"There's no control shape preset called {name!r}.")
    return datafile.read(path, KIND)["shapes"]


def save_preset(control, name, library=None, overwrite=False):
    """Save ``control``'s curve shapes (relative to its pivot, without their
    colors) as preset ``name``; returns the file's path."""
    if not _NAME.match(name or ""):
        raise ValueError(f"Preset name {name!r} can't be used: use letters, digits, spaces, _ and -.")
    if name in BUILT_IN:
        raise ValueError(f"{name} is a built-in preset. Pick another name.")
    path = _path(name, library)
    if os.path.exists(path) and not overwrite:
        raise ValueError(f"There's already a preset called {name}.")
    shapes = curves.shapes(control)
    if not shapes:
        raise ValueError(f"{short_name(control)} has no NURBS curve shapes to save.")
    pivot = _pivot(control)
    records = [{key: curves.record(shape, pivot)[key] for key in _GEOMETRY} for shape in shapes]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return datafile.write(path, KIND, {"shapes": records})


def delete_preset(name, library=None):
    if name in BUILT_IN:
        raise ValueError(f"{name} is a built-in preset; it can't be deleted.")
    path = _path(name, library)
    if not os.path.isfile(path):
        raise LookupError(f"There's no control shape preset called {name!r}.")
    os.remove(path)


# -- building shapes --------------------------------------------------------


def _pivot(control):
    return cmds.xform(control, query=True, objectSpace=True, rotatePivot=True)


def _display(shape):
    """The color and line width settings of ``shape``, to give to new shapes."""
    found = {attr: cmds.getAttr(f"{shape}.{attr}") for attr in curves.DISPLAY}
    found["overrideColorRGB"] = list(cmds.getAttr(f"{shape}.overrideColorRGB")[0])
    return found


def _size(points):
    return max((om.MVector(p).length() for p in points), default=0.0)


def _build_shapes(control, records, pivot, scale=1.0, display=None):
    """Create ``records`` under ``control`` around ``pivot``, scaled by
    ``scale``, named ``<control>Shape``, ``<control>Shape1``, ..."""
    leaf = short_name(control)
    for record in records:
        record = {key: record[key] for key in _GEOMETRY}
        record["cvs"] = [[v * scale for v in p] for p in record["cvs"]]
        record.update(display or {})
        curves.build(control, record, pivot, name=f"{leaf}Shape")


@undoable
def create_control(name, records, size=1.0, at=None, color=0):
    """A new control called ``name`` (or the next free name) with the shapes
    of ``records`` scaled by ``size``, at ``at``'s position and orientation
    if given, else at the origin; returns its long name."""
    control = cmds.createNode("transform", name=unique_name(name), skipSelect=True)
    control = cmds.ls(control, long=True)[0]
    if at:
        cmds.matchTransform(control, at, position=True, rotation=True)
    _build_shapes(control, records, (0, 0, 0), size)
    if color:
        set_color([control], color)
    return cmds.ls(control, long=True)[0]


@undoable
def replace_shapes(nodes, records, keep_size=True, keep_color=True):
    """Swap the curve shapes of each transform for ``records``, scaled to
    the old shapes' size if ``keep_size``, with the old color and line width
    if ``keep_color``. A transform with no curve shapes (a joint, ...) gets
    the preset as it is."""
    preset_size = _size(p for record in records for p in record["cvs"])
    for control in transforms(nodes):
        old = curves.shapes(control)
        pivot = _pivot(control)
        display = _display(old[0]) if keep_color and old else None
        scale = 1.0
        if keep_size and old and preset_size:
            points = [[v - c for v, c in zip(p, pivot)] for shape in old for p in curves.record(shape)["cvs"]]
            scale = _size(points) / preset_size or 1.0
        if old:
            cmds.delete(old)
        _build_shapes(control, records, pivot, scale, display)


# -- moving CVs -------------------------------------------------------------


def _edit_cvs(nodes, move):
    """Move every CV of each control's curve shapes: ``move`` takes and
    returns an ``MVector`` from the control's pivot, in its own space."""
    for control in controls(nodes):
        pivot = om.MVector(_pivot(control))
        for shape in curves.shapes(control):
            # cv[*] lists each CV once, so a periodic curve's repeats follow.
            for cv in cmds.ls(f"{shape}.cv[*]", flatten=True):
                point = om.MVector(cmds.xform(cv, query=True, objectSpace=True, translation=True))
                moved = move(point - pivot) + pivot
                cmds.xform(cv, objectSpace=True, translation=(moved.x, moved.y, moved.z))


@undoable
def rotate_shapes(nodes, degrees):
    """Turn the controls' shapes by ``(x, y, z)`` degrees around their pivots."""
    matrix = om.MEulerRotation([om.MAngle(d, om.MAngle.kDegrees).asRadians() for d in degrees]).asMatrix()
    _edit_cvs(nodes, lambda v: v * matrix)


@undoable
def scale_shapes(nodes, factor):
    """Scale the controls' shapes about their pivots by ``factor``, one
    number or ``(x, y, z)``."""
    sx, sy, sz = (factor,) * 3 if isinstance(factor, (int, float)) else factor
    _edit_cvs(nodes, lambda v: om.MVector(v.x * sx, v.y * sy, v.z * sz))


@undoable
def translate_shapes(nodes, offset):
    """Move the controls' shapes by ``offset`` in their own space."""
    offset = om.MVector(offset)
    _edit_cvs(nodes, lambda v: v + offset)


# -- mirroring and copying --------------------------------------------------


def _matrix(node, attr):
    return om.MMatrix(cmds.getAttr(f"{node}.{attr}[0]"))


@undoable
def mirror_shapes(nodes):
    """Give each control's opposite (by name, ``L_`` / ``R_``, ...) the
    control's shapes mirrored across world X, keeping the opposite's color
    and line width; returns a :data:`Result`."""
    changed, skipped = [], []
    for control in controls(nodes):
        name = opposite_name(short_name(control))
        found = cmds.ls(name, long=True) if name else []
        if name is None:
            skipped.append(f"{short_name(control)}: no side in its name")
            continue
        if len(found) != 1:
            reason = f"several nodes are named {name}" if found else f"no {name} in the scene"
            skipped.append(f"{short_name(control)}: {reason}")
            continue
        target = found[0]
        to_target = _matrix(control, "worldMatrix") * _MIRROR * _matrix(target, "worldInverseMatrix")
        records = []
        for shape in curves.shapes(control):
            record = curves.record(shape)
            record["cvs"] = [list(om.MPoint(p) * to_target)[:3] for p in record["cvs"]]
            records.append(record)
        old = curves.shapes(target)
        display = _display(old[0]) if old else None
        if old:
            cmds.delete(old)
        _build_shapes(target, records, (0, 0, 0), display=display)
        changed.append(target)
    return Result(changed, skipped)


@undoable
def copy_shapes(source, nodes):
    """Give each transform in ``nodes`` ``source``'s shapes, placed the same
    way around its own pivot, keeping its color and line width if it had
    curve shapes."""
    pivot = _pivot(source)
    records = [curves.record(shape, pivot) for shape in curves.shapes(source)]
    source = cmds.ls(source, long=True)[0]
    for control in transforms(nodes):
        if control == source:
            continue
        old = curves.shapes(control)
        display = _display(old[0]) if old else None
        target_pivot = _pivot(control)
        if old:
            cmds.delete(old)
        _build_shapes(control, records, target_pivot, display=display)


# -- display ----------------------------------------------------------------


@undoable
def set_color(nodes, index):
    """Give the controls' shapes Maya index color ``index`` (0 to 31); 0
    turns the color override off."""
    for control in controls(nodes):
        for shape in curves.shapes(control):
            cmds.setAttr(f"{shape}.overrideEnabled", bool(index))
            cmds.setAttr(f"{shape}.overrideRGBColors", False)
            cmds.setAttr(f"{shape}.overrideColor", index)


@undoable
def set_line_width(nodes, width):
    """Set the controls' shapes' line width (-1 uses Maya's default)."""
    for control in controls(nodes):
        for shape in curves.shapes(control):
            cmds.setAttr(f"{shape}.lineWidth", width)
