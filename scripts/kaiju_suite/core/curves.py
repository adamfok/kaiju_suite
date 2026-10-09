"""NURBS curve shapes as plain data, and rebuilt from it. No Qt here.

A record holds a curve's degree, form, knots and CVs (in its transform's
object space, relative to a pivot), plus its color overrides and line width
when they were saved. The Assembler's ControlShape items and the
ControlShape Tool's library both store shapes this way. Rational curve
weights aren't saved.
"""

from maya import cmds, mel
from maya.api import OpenMaya as om

from kaiju_suite.core.nodes import unique_name
from kaiju_suite.core.selection import short_name

DISPLAY = ("overrideEnabled", "overrideRGBColors", "overrideColor", "lineWidth")


def shapes(node):
    """The visible NURBS curve shapes under ``node`` (long names)."""
    return cmds.listRelatives(node, shapes=True, noIntermediate=True, fullPath=True, type="nurbsCurve") or []


def record(shape, pivot=(0, 0, 0)):
    """``shape`` as data, its CVs relative to ``pivot`` (object space)."""
    curve = om.MFnNurbsCurve(om.MSelectionList().add(shape).getDagPath(0))
    px, py, pz = pivot
    found = {
        "name": short_name(shape),
        "degree": curve.degree,
        "form": cmds.getAttr(f"{shape}.form"),  # 0 open, 1 closed, 2 periodic
        "knots": list(curve.knots()),
        "cvs": [[p.x - px, p.y - py, p.z - pz] for p in curve.cvPositions(om.MSpace.kObject)],
    }
    for attr in DISPLAY:
        found[attr] = cmds.getAttr(f"{shape}.{attr}")
    found["overrideColorRGB"] = list(cmds.getAttr(f"{shape}.overrideColorRGB")[0])
    return found


def build(parent, record, pivot=(0, 0, 0), name=None):
    """Create the curve of ``record`` under ``parent``, its CVs placed
    relative to ``pivot``; returns the new shape's long name.

    The shape is named ``name`` (default: the record's), or the next free
    name if that's taken. Uses MEL ``setAttr`` on the curve data (the line a
    .ma file holds), which Python's ``setAttr`` can't take, so the shape is
    exact and the change undoable. Display settings missing from the record
    keep Maya's defaults.
    """
    shape = cmds.createNode("nurbsCurve", name=unique_name(name or record["name"]), parent=parent, skipSelect=True)
    shape = cmds.ls(shape, long=True)[0]
    px, py, pz = pivot
    cvs = [repr(float(v)) for x, y, z in record["cvs"] for v in (x + px, y + py, z + pz)]
    knots = [repr(float(k)) for k in record["knots"]]
    spans = len(record["cvs"]) - record["degree"]  # for every form
    values = [record["degree"], spans, record["form"], "no", 3, len(knots), *knots, len(record["cvs"]), *cvs]
    mel.eval(f'setAttr "{shape}.cc" -type "nurbsCurve" {" ".join(map(str, values))};')
    for attr in DISPLAY:
        if attr in record:
            cmds.setAttr(f"{shape}.{attr}", record[attr])
    if "overrideColorRGB" in record:
        cmds.setAttr(f"{shape}.overrideColorRGB", *record["overrideColorRGB"])
    return shape
