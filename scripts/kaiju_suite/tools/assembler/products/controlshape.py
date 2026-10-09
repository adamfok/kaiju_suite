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
...) are left alone. Controls missing from the scene are skipped with a
warning. Rational curve weights aren't saved.
"""

from maya import cmds

from kaiju_suite.core import curves
from kaiju_suite.tools.assembler import data, runlog

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


class ControlShapeProduct(data.DataProduct):
    name = "ControlShape"
    utility = "ControlShape Tool"
    kind = "controlShape"
    extension = ".ctrl"
    order = 120
    menu_slot = (2, 2)

    def selection_problems(self):
        selection = cmds.ls(selection=True, long=True)
        if not selection:
            return ["Nothing selected. Select the controls whose shapes to publish."]
        without = [cmds.ls(c)[0] for c in _controls(selection) if not curves.shapes(c)]
        if without:
            return [f"These have no NURBS curve shapes: {', '.join(without)}. Select controls with curve shapes."]
        return []

    def gather(self, selection):
        records = []
        for control in _controls(selection):
            shapes = curves.shapes(control)
            if not shapes:
                raise RuntimeError(f"{cmds.ls(control)[0]} has no NURBS curve shapes.")
            pivot = _pivot(control)
            records.append({"name": cmds.ls(control)[0], "shapes": [curves.record(s, pivot) for s in shapes]})
        if not records:
            raise RuntimeError("No controls selected to publish.")
        return {"controls": records}

    def apply(self, payload):
        records = payload["controls"]
        missing = data.skip_missing([record["name"] for record in records], "controls")
        records = [record for record in records if record["name"] not in missing]
        data.require_unique([record["name"] for record in records])

        for record in records:
            control = cmds.ls(record["name"], long=True)[0]
            old = curves.shapes(control)
            if old:
                cmds.delete(old)
            pivot = _pivot(control)
            for shape in record["shapes"]:
                curves.build(control, shape, pivot)
            runlog.info(f"{record['name']}: replaced with {data.plural(len(record['shapes']), 'curve shape')}")
        return f"Replaced the shapes of {data.plural(len(records), 'control')}"

    def describe(self, payload):
        records = payload["controls"]
        count = sum(len(record["shapes"]) for record in records)
        return [
            data.plural(len(records), "control"),
            data.plural(count, "curve shape"),
            f"Controls: {', '.join(record['name'] for record in records)}",
        ]


PRODUCT = ControlShapeProduct()
