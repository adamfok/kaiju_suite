"""ControlShape (.ctrl): the NURBS curve shapes of controls, saved and swapped back in.

:func:`gather` saves, for each given control (a curve shape stands for its
control), every curve shape under it: degree, form, knots, and its CVs
relative to the control's rotate pivot, in the control's own space, plus the
shape's color overrides and line width. Controls are saved by their shortest
unique name.

:func:`apply` finds each control by name, deletes its curve shapes (CV
counts may differ, so they're replaced rather than edited) and creates the
saved ones, placed relative to the control's current pivot: a control that
has moved, or whose pivot has, gets the shape where it now is. Other shapes
(locators, ...) are left alone. Controls missing from the scene are skipped
with a warning. Rational curve weights aren't saved.

:data:`CHECKS` are QC checks on given controls (no curve shapes, shape name
mismatch, no color, duplicate names, rational curves), run by the
ControlShape Tool's QC tab and before Builder publishes. They change
nothing.
"""

import re

from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.core import curves
from kaiju_suite.core.checks import Check, Problem
from kaiju_suite.core.selection import short_name
from kaiju_suite.datatypes import plural, report, require_unique, short, skip_missing

KIND = "controlShape"
EXTENSION = ".ctrl"


def _controls(selection):
    """The given controls, a curve shape standing for its parent, in order
    without repeats."""
    controls = []
    for path in cmds.ls(selection, long=True) or []:
        if cmds.nodeType(path) == "nurbsCurve":
            path = cmds.listRelatives(path, parent=True, fullPath=True)[0]
        controls.append(path)
    return list(dict.fromkeys(controls))


def _pivot(control):
    return cmds.xform(control, query=True, objectSpace=True, rotatePivot=True)


def selection_problems(selection):
    if not selection:
        return ["Nothing selected. Select the controls whose shapes to publish."]
    without = [short(c) for c in _controls(selection) if not curves.shapes(c)]
    if without:
        return [f"These have no NURBS curve shapes: {', '.join(without)}. Select controls with curve shapes."]
    return []


def gather(nodes):
    records = []
    for control in _controls(nodes):
        shapes = curves.shapes(control)
        if not shapes:
            raise RuntimeError(f"{short(control)} has no NURBS curve shapes.")
        pivot = _pivot(control)
        records.append({"name": short(control), "shapes": [curves.record(s, pivot) for s in shapes]})
    if not records:
        raise RuntimeError("No controls selected to publish.")
    return {"controls": records}


def apply(payload, info=None):
    records = payload["controls"]
    missing = skip_missing([record["name"] for record in records], "controls")
    records = [record for record in records if record["name"] not in missing]
    require_unique([record["name"] for record in records])

    for record in records:
        control = cmds.ls(record["name"], long=True)[0]
        old = curves.shapes(control)
        if old:
            cmds.delete(old)
        pivot = _pivot(control)
        for shape in record["shapes"]:
            curves.build(control, shape, pivot)
        report(info, f"{record['name']}: replaced with {plural(len(record['shapes']), 'curve shape')}")
    return f"Replaced the shapes of {plural(len(records), 'control')}"


def nodes(payload):
    return [record["name"] for record in payload["controls"]]


def describe(payload):
    records = payload["controls"]
    count = sum(len(record["shapes"]) for record in records)
    return [
        plural(len(records), "control"),
        plural(count, "curve shape"),
        f"Controls: {', '.join(record['name'] for record in records)}",
    ]


def compare_view(payload):
    return payload


# -- QC checks --------------------------------------------------------------


def _checked(nodes):
    """The controls among ``nodes`` (long names), a curve shape standing for
    its control."""
    return _controls(nodes) if nodes else []


def _check_no_shapes(nodes):
    return [
        Problem(f"{short(control)}: no NURBS curve shape", [short(control)])
        for control in _checked(nodes)
        if not curves.shapes(control)
    ]


def _check_shape_names(nodes):
    problems = []
    for control in _checked(nodes):
        leaf = short_name(control)
        wanted = re.compile(rf"^{re.escape(leaf)}Shape\d*$")
        for shape in curves.shapes(control):
            if not wanted.match(short_name(shape)):
                problems.append(
                    Problem(
                        f"{short(control)}: curve shape {short_name(shape)} isn't named {leaf}Shape", [short(shape)]
                    )
                )
    return problems


def _colored(node):
    """Whether ``node`` draws with an override color (index 0 is no color)."""
    if not cmds.getAttr(f"{node}.overrideEnabled"):
        return False
    return bool(cmds.getAttr(f"{node}.overrideRGBColors") or cmds.getAttr(f"{node}.overrideColor"))


def _check_color(nodes):
    problems = []
    for control in _checked(nodes):
        shapes = curves.shapes(control)
        if shapes and not any(_colored(node) for node in [control, *shapes]):
            problems.append(Problem(f"{short(control)}: no color", [short(control)]))
    return problems


def _check_duplicate_names(nodes):
    problems = []
    for control in _checked(nodes):
        name = short_name(control)
        same = sorted(cmds.ls(name) or [])
        if len(same) > 1:
            problems.append(Problem(f"{short(control)}: {len(same)} nodes are called {name}", same))
    return problems


def _rational(shape):
    curve = om.MFnNurbsCurve(om.MSelectionList().add(shape).getDagPath(0))
    return any(abs(p.w - 1) > 1e-9 for p in curve.cvPositions(om.MSpace.kObject))


def _check_rational(nodes):
    problems = []
    for control in _checked(nodes):
        for shape in curves.shapes(control):
            if _rational(shape):
                problems.append(
                    Problem(f"{short(control)}: {short_name(shape)} has CV weights, which aren't saved", [short(shape)])
                )
    return problems


CHECKS = (
    Check(
        "no_shapes",
        "No curve shapes",
        "Selected nodes with no NURBS curve shape: there's nothing to save.",
        _check_no_shapes,
    ),
    Check(
        "shape_names",
        "Shape name mismatch",
        "Curve shapes not named after their control (<control>Shape, <control>Shape1, ...).",
        _check_shape_names,
    ),
    Check(
        "color",
        "No color",
        "Controls with no drawing override color on the control or its curve shapes.",
        _check_color,
    ),
    Check(
        "duplicate_names",
        "Duplicate names",
        "Controls whose name another node also has; ControlShape items find controls by name.",
        _check_duplicate_names,
    ),
    Check(
        "rational",
        "Rational curves",
        "Curve shapes with CV weights, which ControlShape items don't save.",
        _check_rational,
    ),
)
