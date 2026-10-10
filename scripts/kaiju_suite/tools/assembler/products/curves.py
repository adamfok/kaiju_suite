"""Curves (.crv): NURBS curves that aren't controls, saved as data and rebuilt
as new curves (guide curves for Spline IK, wire deformer curves, ...).

Publish saves each selected curve (select its transform or one of its curve
shapes): name, parent name, local transform (translate, rotate, scale,
rotate order) and every curve shape under it, as :mod:`kaiju_suite.core.curves`
records (degree, form, knots, object-space CVs, color overrides and line
width). Rational curve weights aren't saved. Only selected curves are saved,
not the curves below them; a selected curve under another selected curve
stays under it.

Run always creates new curves and never changes existing ones, as Joints and
Mesh do: a name that's taken gets the next free one (``spine_crv`` →
``spine_crv1``, shape ``spine_crv1Shape``). A curve whose parent isn't in
the file goes under the scene's node of that name, if there is one,
otherwise under the world. If several nodes have that parent name, Run
stops before creating anything.
"""

from maya import cmds

from kaiju_suite.core import curves
from kaiju_suite.core.selection import short_name
from kaiju_suite.tools.assembler import data

_VECTORS = ("translate", "rotate", "scale")


def _split_selection(selection):
    """The selected curve transforms (a selected curve shape counts as its
    transform), in selection order, and the selected nodes that aren't curves."""
    transforms, others = [], []
    for node in cmds.ls(selection, long=True, objectsOnly=True) or []:
        if cmds.objectType(node, isAType="transform") and curves.shapes(node):
            transforms.append(node)
        elif cmds.objectType(node) == "nurbsCurve" and not cmds.getAttr(f"{node}.intermediateObject"):
            transforms.append(data.parent_of(node))
        else:
            others.append(node)
    return list(dict.fromkeys(transforms)), list(dict.fromkeys(others))


def _record(transform, index_of):
    parent = data.parent_of(transform)
    record = {
        "name": short_name(transform),
        "parent": short_name(parent) if parent else None,
        "parent_index": index_of.get(parent),
    }
    for attr in _VECTORS:
        record[attr] = list(cmds.getAttr(f"{transform}.{attr}")[0])
    record["rotateOrder"] = int(cmds.getAttr(f"{transform}.rotateOrder"))
    record["shapes"] = [curves.record(shape) for shape in curves.shapes(transform)]
    return record


class CurvesProduct(data.DataProduct):
    name = "Curves"
    kind = "curves"
    extension = ".crv"
    order = 55
    menu_slot = (2, 3)

    def selection_problems(self):
        selection = cmds.ls(selection=True)
        if not selection:
            return ["Nothing selected. Select the NURBS curves to publish."]
        transforms, others = _split_selection(selection)
        if others:
            names = ", ".join(short_name(n) for n in others)
            return [f"Not NURBS curves: {names}. Select only curves to publish."]
        if not transforms:
            return ["No NURBS curves selected. Select the curves to publish."]
        return []

    def gather(self, selection):
        transforms, others = _split_selection(selection)
        if others:
            raise RuntimeError(f"Not NURBS curves: {', '.join(short_name(n) for n in others)}")
        if not transforms:
            raise RuntimeError("No NURBS curves selected to publish.")
        # Parents before children, so Run can create a curve's parent first.
        transforms.sort(key=lambda path: path.count("|"))
        index_of, records = {}, []
        for transform in transforms:
            records.append(_record(transform, index_of))
            index_of[transform] = len(records) - 1
        return {"curves": records}

    def apply(self, payload):
        records = payload["curves"]
        outside = data.outside_parents(records)
        uuids, renamed = [], []
        for record in records:
            index = record["parent_index"]
            parent = data.node_path(uuids[index]) if index is not None else outside.get(record["parent"])
            uuid = data.create_node("transform", record["name"], parent)
            transform = data.node_path(uuid)
            for attr in _VECTORS:
                cmds.setAttr(f"{transform}.{attr}", *record[attr])
            cmds.setAttr(f"{transform}.rotateOrder", record["rotateOrder"])
            leaf = short_name(transform)
            for i, shape in enumerate(record["shapes"]):
                curves.build(transform, shape, name=f"{leaf}Shape" if i == 0 else f"{leaf}Shape{i}")
            uuids.append(uuid)
            if leaf != record["name"]:
                renamed.append(f"{record['name']} → {leaf}")
        message = f"Created {data.plural(len(records), 'curve')}"
        if renamed:
            message += f" (names taken, renamed: {', '.join(renamed)})"
        return message

    def describe(self, payload):
        records = payload["curves"]
        return [data.plural(len(records), "curve"), ", ".join(r["name"] for r in records)]


PRODUCT = CurvesProduct()
