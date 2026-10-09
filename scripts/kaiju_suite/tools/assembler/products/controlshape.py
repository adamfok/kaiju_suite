"""ControlShape (.ctrl): the NURBS curve shapes of controls, saved and swapped back in.

Publish saves, for each selected control (select it or one of its curve
shapes), every curve shape under it: degree, form, knots, and its CVs
relative to the control's rotate pivot, in the control's own space, plus the
shape's color overrides and line width. Controls are saved by their shortest
unique name.

Run finds each control by name, deletes its curve shapes (CV counts may
differ, so they're replaced rather than edited) and creates the saved ones,
placed relative to the control's current pivot: a control that has moved,
or whose pivot has, gets the shape where it now is. Other shapes (locators,
...) are left alone. Rational curve weights aren't saved.
"""

from maya import cmds, mel
from maya.api import OpenMaya as om

from kaiju_suite.tools.assembler import data

_DISPLAY = ("overrideEnabled", "overrideRGBColors", "overrideColor", "lineWidth")


def _plural(count, word):
    return f"{count} {word}{'s' if count != 1 else ''}"


def _leaf(path):
    return path.rsplit("|", 1)[-1]


def _curve_shapes(node):
    shapes = cmds.listRelatives(node, shapes=True, noIntermediate=True, fullPath=True, type="nurbsCurve")
    return shapes or []


def _controls(selection):
    """The selected controls, a selected curve shape standing for its parent,
    in selection order without repeats."""
    controls = []
    for path in cmds.ls(selection, long=True) or []:
        if cmds.nodeType(path) == "nurbsCurve":
            path = cmds.listRelatives(path, parent=True, fullPath=True)[0]
        controls.append(path)
    return list(dict.fromkeys(controls))


def _pivot(control):
    return cmds.xform(control, query=True, objectSpace=True, rotatePivot=True)


def _record(shape, pivot):
    curve = om.MFnNurbsCurve(om.MSelectionList().add(shape).getDagPath(0))
    px, py, pz = pivot
    record = {
        "name": _leaf(shape),
        "degree": curve.degree,
        "form": cmds.getAttr(f"{shape}.form"),  # 0 open, 1 closed, 2 periodic
        "knots": list(curve.knots()),
        "cvs": [[p.x - px, p.y - py, p.z - pz] for p in curve.cvPositions(om.MSpace.kObject)],
    }
    for attr in _DISPLAY:
        record[attr] = cmds.getAttr(f"{shape}.{attr}")
    record["overrideColorRGB"] = list(cmds.getAttr(f"{shape}.overrideColorRGB")[0])
    return record


def _build(control, record, pivot):
    """Create the shape of ``record`` under ``control``. Uses MEL ``setAttr``
    on the curve data (the line a .ma file holds), which Python's ``setAttr``
    can't take, so the shape is exact and the change undoable."""
    shape = data.node_path(data.create_node("nurbsCurve", record["name"], control))
    px, py, pz = pivot
    cvs = [repr(v) for x, y, z in record["cvs"] for v in (x + px, y + py, z + pz)]
    knots = [repr(float(k)) for k in record["knots"]]
    spans = len(record["cvs"]) - record["degree"]  # for every form
    values = [record["degree"], spans, record["form"], "no", 3, len(knots), *knots, len(record["cvs"]), *cvs]
    mel.eval(f'setAttr "{shape}.cc" -type "nurbsCurve" {" ".join(map(str, values))};')
    for attr in _DISPLAY:
        cmds.setAttr(f"{shape}.{attr}", record[attr])
    cmds.setAttr(f"{shape}.overrideColorRGB", *record["overrideColorRGB"])
    return shape


def _require_unique(names):
    ambiguous = [f"{name} ({', '.join(cmds.ls(name, long=True))})" for name in names if len(cmds.ls(name)) > 1]
    if ambiguous:
        raise RuntimeError(f"Several nodes have the same name, can't tell which to use: {'; '.join(ambiguous)}")


class ControlShapeProduct(data.DataProduct):
    name = "ControlShape"
    kind = "controlShape"
    extension = ".ctrl"
    order = 120

    def selection_problems(self):
        selection = cmds.ls(selection=True, long=True)
        if not selection:
            return ["Nothing selected. Select the controls whose shapes to publish."]
        without = [cmds.ls(c)[0] for c in _controls(selection) if not _curve_shapes(c)]
        if without:
            return [f"These have no NURBS curve shapes: {', '.join(without)}. Select controls with curve shapes."]
        return []

    def gather(self, selection):
        records = []
        for control in _controls(selection):
            shapes = _curve_shapes(control)
            if not shapes:
                raise RuntimeError(f"{cmds.ls(control)[0]} has no NURBS curve shapes.")
            pivot = _pivot(control)
            records.append({"name": cmds.ls(control)[0], "shapes": [_record(s, pivot) for s in shapes]})
        if not records:
            raise RuntimeError("No controls selected to publish.")
        return {"controls": records}

    def apply(self, payload):
        records = payload["controls"]
        names = [record["name"] for record in records]
        data.require_nodes(names, "controls")
        _require_unique(names)

        for record in records:
            control = cmds.ls(record["name"], long=True)[0]
            old = _curve_shapes(control)
            if old:
                cmds.delete(old)
            pivot = _pivot(control)
            for shape in record["shapes"]:
                _build(control, shape, pivot)
        return f"Replaced the shapes of {_plural(len(records), 'control')}"

    def describe(self, payload):
        records = payload["controls"]
        count = sum(len(record["shapes"]) for record in records)
        return [
            _plural(len(records), "control"),
            _plural(count, "curve shape"),
            f"Controls: {', '.join(record['name'] for record in records)}",
        ]


PRODUCT = ControlShapeProduct()
