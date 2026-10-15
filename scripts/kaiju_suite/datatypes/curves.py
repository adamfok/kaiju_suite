"""Curves (.curve): NURBS curves that aren't controls, saved as data and
rebuilt as new curves (guide curves for Spline IK, wire deformer curves, ...).

:func:`gather` saves each given curve (its transform or one of its curve
shapes): name, parent name, local transform (translate, rotate, scale,
rotate order) and every curve shape under it, as :mod:`kaiju_suite.core.curves`
records (degree, form, knots, object-space CVs, color overrides and line
width). Rational curve weights aren't saved. Only the given curves are
saved, not the curves below them; a curve under another given curve stays
under it.

:func:`apply` always creates new curves and never changes existing ones, as
Joints and Mesh do: a name that's taken gets the next free one
(``spine_crv`` → ``spine_crv1``, shape ``spine_crv1Shape``). A curve whose
parent isn't in the file goes under the scene's node of that name, if there
is one, otherwise under the world. If several nodes have that parent name,
it stops before creating anything.

Scripter's NurbsCurve items use ``.curve``; the Assembler's Curves items
keep ``.crv``. The file contents are the same.

:data:`CHECKS` are QC checks on given curves (duplicate names, rational
curves, construction history, degenerate curves), run by the Curve Tool's
QC tab and before Scripter publishes. Checks change nothing.
"""

from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.core import curves
from kaiju_suite.core.checks import Check, Problem
from kaiju_suite.core.selection import short_name
from kaiju_suite.datatypes import create_node, node_path, outside_parents, parent_of, plural, short

KIND = "curves"
EXTENSION = ".curve"

_VECTORS = ("translate", "rotate", "scale")


def _split_selection(selection):
    """The selected curve transforms (a selected curve shape or component
    counts as its transform), in selection order, and the selected nodes
    that aren't curves."""
    transforms, others = [], []
    for node in cmds.ls(selection, long=True, objectsOnly=True) or []:
        if cmds.objectType(node, isAType="transform") and curves.shapes(node):
            transforms.append(node)
        elif cmds.objectType(node) == "nurbsCurve" and not cmds.getAttr(f"{node}.intermediateObject"):
            transforms.append(parent_of(node))
        else:
            others.append(node)
    return list(dict.fromkeys(transforms)), list(dict.fromkeys(others))


def curve_transforms(selection):
    """The curve transforms in ``selection`` (a shape or component stands
    for its transform), as long names, in order, each once."""
    return _split_selection(selection)[0] if selection else []


def _record(transform, index_of):
    parent = parent_of(transform)
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


def selection_problems(selection):
    if not selection:
        return ["Nothing selected. Select the NURBS curves to publish."]
    transforms, others = _split_selection(selection)
    if others:
        names = ", ".join(short_name(n) for n in others)
        return [f"Not NURBS curves: {names}. Select only curves to publish."]
    if not transforms:
        return ["No NURBS curves selected. Select the curves to publish."]
    return []


def gather(nodes):
    transforms, others = _split_selection(nodes)
    if others:
        raise RuntimeError(f"Not NURBS curves: {', '.join(short_name(n) for n in others)}")
    if not transforms:
        raise RuntimeError("No NURBS curves selected to publish.")
    # Parents before children, so apply can create a curve's parent first.
    transforms.sort(key=lambda path: path.count("|"))
    index_of, records = {}, []
    for transform in transforms:
        records.append(_record(transform, index_of))
        index_of[transform] = len(records) - 1
    return {"curves": records}


def apply(payload, info=None):
    records = payload["curves"]
    outside = outside_parents(records)
    uuids, renamed = [], []
    for record in records:
        index = record["parent_index"]
        parent = node_path(uuids[index]) if index is not None else outside.get(record["parent"])
        uuid = create_node("transform", record["name"], parent)
        transform = node_path(uuid)
        for attr in _VECTORS:
            cmds.setAttr(f"{transform}.{attr}", *record[attr])
        cmds.setAttr(f"{transform}.rotateOrder", record["rotateOrder"])
        leaf = short_name(transform)
        for i, shape in enumerate(record["shapes"]):
            curves.build(transform, shape, name=f"{leaf}Shape" if i == 0 else f"{leaf}Shape{i}")
        uuids.append(uuid)
        if leaf != record["name"]:
            renamed.append(f"{record['name']} → {leaf}")
    message = f"Created {plural(len(records), 'curve')}"
    if renamed:
        message += f" (names taken, renamed: {', '.join(renamed)})"
    return message


def nodes(payload):
    return [r["name"] for r in payload["curves"]]


def describe(payload):
    records = payload["curves"]
    return [plural(len(records), "curve"), ", ".join(r["name"] for r in records)]


def compare_view(payload):
    # parent_index shifts whenever curves are added or removed; the parent's name says enough.
    return {**payload, "curves": [{k: v for k, v in r.items() if k != "parent_index"} for r in payload["curves"]]}


# -- QC checks --------------------------------------------------------------

# How far a CV weight may be from 1 and still count as non-rational.
_WEIGHT_TOLERANCE = 1e-6


def _mfn(shape):
    return om.MFnNurbsCurve(om.MSelectionList().add(shape).getDagPath(0))


def _per_shape(find, text):
    """A check function: ``find(shape, **options)`` on each curve shape of
    the curves among ``nodes``; one :class:`Problem` per curve with shapes
    that have something, ``text(found)`` saying what (``found`` is the first
    such shape's result), selecting the curve. A curve with several shapes
    names the ones that have it."""

    def run(nodes, **options):
        problems = []
        for transform in curve_transforms(nodes):
            shapes = curves.shapes(transform)
            found = [(shape, result) for shape in shapes for result in [find(shape, **options)] if result]
            if not found:
                continue
            message = f"{short(transform)}: {text(found[0][1])}"
            if len(shapes) > 1:
                message += f" ({', '.join(short_name(shape) for shape, _ in found)})"
            problems.append(Problem(message, [short(transform)]))
        return problems

    return run


def _duplicates(path):
    """The nodes called ``path``'s short name, sorted, if there are several."""
    same = sorted(cmds.ls(short_name(path)) or [])
    return same if len(same) > 1 else []


def _check_duplicate_names(nodes):
    problems = []
    for transform in curve_transforms(nodes):
        name = short_name(transform)
        same = _duplicates(transform)
        if same:
            problems.append(Problem(f"{short(transform)}: {len(same)} nodes are called {name}", same))
        parent = parent_of(transform)
        same = _duplicates(parent) if parent else []
        if same:
            problems.append(
                Problem(
                    f"{short(transform)}: parent {short(parent)}: {len(same)} nodes are called {short_name(parent)}",
                    same,
                )
            )
    return problems


def _find_rational(shape):
    return any(abs(p.w - 1) > _WEIGHT_TOLERANCE for p in _mfn(shape).cvPositions(om.MSpace.kObject))


def _find_history(shape):
    return cmds.listConnections(f"{shape}.create", source=True, destination=False) or []


def _find_degenerate(shape, tolerance=0.0001):
    points = _mfn(shape).cvPositions(om.MSpace.kObject)
    first = points[0]
    if all(first.distanceTo(p) <= tolerance for p in points):
        return "all CVs on one spot"
    if _mfn(shape).length() <= tolerance:
        return "zero length"
    return None


CHECKS = (
    Check(
        "duplicate_names",
        "Duplicate names",
        "Curves, or their parents, whose name another node also has: Run puts curves under parents found by name.",
        _check_duplicate_names,
    ),
    Check(
        "rational",
        "Rational curves",
        "Curves with CV weights other than 1: the weights aren't saved.",
        _per_shape(_find_rational, lambda found: "rational (CV weights aren't saved)"),
    ),
    Check(
        "history",
        "Construction history",
        "Curves driven by history (input connections on the shape), which isn't saved: the file holds the "
        "current shape only.",
        _per_shape(_find_history, lambda found: f"driven by {', '.join(found)} (only the current shape is saved)"),
    ),
    Check(
        "degenerate",
        "Degenerate curves",
        "Curves of zero length, or with all their CVs on one spot, give or take the tolerance.",
        _per_shape(_find_degenerate, lambda found: found),
        {"tolerance": 0.0001},
    ),
)
