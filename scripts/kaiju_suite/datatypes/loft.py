"""Loft (.loft): lofted NURBS surfaces saved with their loft settings and
input curves, and rebuilt with live history (ribbons lofted between curves,
...). Builder only; there's no Assembler product.

:func:`gather` saves each given surface (its transform, or its surface shape
or CVs) whose shape is driven by a ``loft`` node: the surface's name, parent
name and local transform, the loft node's name and settings, and its input
curves in order, by their transform's name, with each curve's ``reverse``
flag. Only NURBS curves can be saved as inputs: an isoparm or a
curve-on-surface can't be found by name, so such a loft can't be published.

:func:`apply` finds the input curves by name. A loft with a curve missing
from the scene is skipped with a warning; a curve name that matches several
nodes stops it before anything changes. If a surface of the saved name is
already there, it keeps its node, transform and connections (follicles,
constraints, skin...): its old history is deleted and a new loft from the
saved curves drives its shape. Otherwise a new surface is created under its
saved parent (found by name, otherwise the world) with its saved transform,
and gets ``initialShadingGroup``. The new loft node takes its saved name, or
the next free one.

:data:`CHECKS` are QC checks on given surfaces (not a loft, unsupported
inputs, duplicate names, flipped curves), run by the Loft Tool's QC tab and
before Builder publishes. Checks change nothing.
"""

from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite import datatypes
from kaiju_suite.core.checks import Check, Problem
from kaiju_suite.core.selection import short_name
from kaiju_suite.datatypes import create_node, node_path, outside_parents, parent_of, plural, require_unique, short

KIND = "loft"
EXTENSION = ".loft"

_VECTORS = ("translate", "rotate", "scale")
# The loft node's settings saved with each loft.
SETTINGS = ("uniform", "close", "degree", "sectionSpans", "autoReverse", "reverseSurfaceNormals")
_INTS = ("degree", "sectionSpans")


# -- nodes ------------------------------------------------------------------


def _shapes(transform, node_type):
    return cmds.listRelatives(transform, shapes=True, noIntermediate=True, fullPath=True, type=node_type) or []


def _split_selection(selection):
    """The selected surface transforms (a selected surface shape or CV counts
    as its transform), in selection order, and the selected nodes that
    aren't surfaces."""
    transforms, others = [], []
    for node in cmds.ls(selection, long=True, objectsOnly=True) or []:
        if cmds.objectType(node, isAType="transform") and _shapes(node, "nurbsSurface"):
            transforms.append(node)
        elif cmds.objectType(node) == "nurbsSurface" and not cmds.getAttr(f"{node}.intermediateObject"):
            transforms.append(parent_of(node))
        else:
            others.append(node)
    return list(dict.fromkeys(transforms)), list(dict.fromkeys(others))


def surfaces(selection):
    """The NURBS surface transforms in ``selection`` (a shape or CV stands for
    its transform), as long names, in order, each once."""
    return _split_selection(selection)[0] if selection else []


def _shape(surface):
    return _shapes(surface, "nurbsSurface")[0]


def loft_node(surface):
    """The ``loft`` node driving ``surface``'s shape, or ``None``."""
    found = cmds.listConnections(f"{_shape(surface)}.create", source=True, destination=False) or []
    return found[0] if found and cmds.nodeType(found[0]) == "loft" else None


def _inputs(node):
    """``(index, source shape)`` for each connected input of loft ``node``, in order."""
    out = []
    for index in cmds.getAttr(f"{node}.inputCurve", multiIndices=True) or []:
        found = cmds.listConnections(f"{node}.inputCurve[{index}]", source=True, destination=False, shapes=True)
        if found:
            out.append((index, cmds.ls(found[0], long=True)[0]))
    return out


def _is_curve(shape):
    return cmds.nodeType(shape) == "nurbsCurve" and not cmds.getAttr(f"{shape}.intermediateObject")


def _unsupported(node):
    """The inputs of loft ``node`` that aren't NURBS curves."""
    return [shape for _, shape in _inputs(node) if not _is_curve(shape)]


def _curve_shape(transform):
    found = _shapes(transform, "nurbsCurve")
    return found[0] if found else None


# -- gather -----------------------------------------------------------------


def _record(surface, index_of):
    node = loft_node(surface)
    parent = parent_of(surface)
    record = {
        "name": short_name(surface),
        "parent": short_name(parent) if parent else None,
        "parent_index": index_of.get(parent),
    }
    for attr in _VECTORS:
        record[attr] = list(cmds.getAttr(f"{surface}.{attr}")[0])
    record["rotateOrder"] = int(cmds.getAttr(f"{surface}.rotateOrder"))
    record["shape"] = short_name(_shape(surface))
    record["loft"] = node
    record["settings"] = {
        attr: int(cmds.getAttr(f"{node}.{attr}")) if attr in _INTS else bool(cmds.getAttr(f"{node}.{attr}"))
        for attr in SETTINGS
    }
    record["curves"] = [
        {"name": short_name(parent_of(shape)), "reverse": bool(cmds.getAttr(f"{node}.reverse[{index}]"))}
        for index, shape in _inputs(node)
    ]
    return record


def selection_problems(selection):
    if not selection:
        return ["Nothing selected. Select the lofted NURBS surfaces to publish."]
    transforms, others = _split_selection(selection)
    if others:
        return [f"Not NURBS surfaces: {', '.join(short_name(n) for n in others)}. Select only lofted surfaces."]
    if not transforms:
        return ["No NURBS surfaces selected. Select the lofted NURBS surfaces to publish."]
    unlofted = [short(s) for s in transforms if not loft_node(s)]
    if unlofted:
        return [f"Not lofted: {', '.join(unlofted)}. Select surfaces driven by a loft."]
    unsupported = [short(s) for s in transforms if _unsupported(loft_node(s))]
    if unsupported:
        return [
            f"Loft inputs that aren't curves: {', '.join(unsupported)}. "
            "Only lofts from NURBS curves can be published (an isoparm can't be found by name)."
        ]
    return []


def gather(nodes):
    problems = selection_problems(nodes)
    if problems:
        raise RuntimeError(" ".join(problems))
    transforms = surfaces(nodes)
    # Parents before children, so apply can create a surface's parent first.
    transforms.sort(key=lambda path: path.count("|"))
    index_of, records = {}, []
    for transform in transforms:
        records.append(_record(transform, index_of))
        index_of[transform] = len(records) - 1
    return {"lofts": records}


# -- apply ------------------------------------------------------------------


def _existing(record):
    """The scene's surface of ``record``'s name, or ``None``."""
    found = [n for n in cmds.ls(record["name"], long=True, type="transform") or [] if _shapes(n, "nurbsSurface")]
    return found[0] if found else None


def _new_surface(record, parent):
    uuid = create_node("transform", record["name"], parent)
    transform = node_path(uuid)
    for attr in _VECTORS:
        cmds.setAttr(f"{transform}.{attr}", *record[attr])
    cmds.setAttr(f"{transform}.rotateOrder", record["rotateOrder"])
    leaf = short_name(transform)
    shape = record.get("shape") or f"{leaf}Shape"
    cmds.createNode("nurbsSurface", name=datatypes.unique_name(shape), parent=transform, skipSelect=True)
    cmds.sets(node_path(uuid), edit=True, forceElement="initialShadingGroup")
    return uuid


def _clear_history(surface):
    """Delete the history driving ``surface``'s shape, keeping the surface."""
    shape = _shape(surface)
    found = cmds.listConnections(f"{shape}.create", source=True, destination=False, plugs=True) or []
    if not found:
        return
    driver = found[0].split(".")[0]
    if cmds.nodeType(driver) == "loft":
        cmds.delete(driver)
    else:
        cmds.disconnectAttr(found[0], f"{shape}.create")


def _build_loft(record, surface):
    node = cmds.createNode("loft", name=datatypes.unique_name(record.get("loft") or "loft1"), skipSelect=True)
    for attr, value in record["settings"].items():
        cmds.setAttr(f"{node}.{attr}", value)
    for index, curve in enumerate(record["curves"]):
        cmds.connectAttr(f"{_curve_shape(curve['name'])}.worldSpace[0]", f"{node}.inputCurve[{index}]")
        cmds.setAttr(f"{node}.reverse[{index}]", curve["reverse"])
    cmds.connectAttr(f"{node}.outputSurface", f"{_shape(surface)}.create")
    return node


def apply(payload, info=None):
    records = payload["lofts"]
    missing = {}
    for record in records:
        gone = [c["name"] for c in record["curves"] if not cmds.objExists(c["name"])]
        if gone:
            missing[record["name"]] = gone
    if missing:
        named = "; ".join(f"{name} ({', '.join(curves)})" for name, curves in missing.items())
        datatypes.warning(f"Skipped lofts with missing curves: {named}")
    todo = [r for r in records if r["name"] not in missing]

    # Check everything before changing anything.
    require_unique([c["name"] for r in todo for c in r["curves"]] + [r["name"] for r in todo])
    no_shape = [c["name"] for r in todo for c in r["curves"] if not _curve_shape(c["name"])]
    if no_shape:
        raise RuntimeError(f"Not NURBS curves: {', '.join(dict.fromkeys(no_shape))}")
    outside = outside_parents([r for r in todo if not _existing(r)])

    built, replaced, uuids = 0, 0, {}
    for i, record in enumerate(records):
        if record["name"] in missing:
            continue
        surface = _existing(record)
        if surface:
            _clear_history(surface)
            replaced += 1
        else:
            index = record.get("parent_index")
            parent = node_path(uuids[index]) if index in uuids else outside.get(record["parent"])
            surface = node_path(_new_surface(record, parent))
            built += 1
        uuids[i] = cmds.ls(surface, uuid=True)[0]
        node = _build_loft(record, surface)
        datatypes.report(info, f"{short(surface)}: lofted from {', '.join(c['name'] for c in record['curves'])} ({node})")
    parts = []
    if built:
        parts.append(f"Built {plural(built, 'loft')}")
    if replaced:
        parts.append(f"{'replaced' if parts else 'Replaced'} the history of {plural(replaced, 'loft')}")
    return ", ".join(parts) or "Built no lofts"


def nodes(payload):
    return [r["name"] for r in payload["lofts"]]


def describe(payload):
    records = payload["lofts"]
    return [plural(len(records), "loft")] + [f"{r['name']} ({plural(len(r['curves']), 'curve')})" for r in records]


def compare_view(payload):
    return payload


# -- QC checks --------------------------------------------------------------


def _direction(shape):
    """The world-space direction from ``shape``'s start to its end point."""
    fn = om.MFnNurbsCurve(om.MSelectionList().add(shape).getDagPath(0))
    start, end = fn.knotDomain
    return fn.getPointAtParam(end, om.MSpace.kWorld) - fn.getPointAtParam(start, om.MSpace.kWorld)


def _find_not_loft(surface):
    return [surface] if not loft_node(surface) else []


def _find_unsupported(surface):
    node = loft_node(surface)
    return [node] if node and _unsupported(node) else []


def _find_names(surface):
    found = [surface] if len(cmds.ls(short_name(surface))) > 1 else []
    node = loft_node(surface)
    for _, shape in _inputs(node) if node else []:
        curve = parent_of(shape)
        if _is_curve(shape) and len(cmds.ls(short_name(curve))) > 1:
            found.append(curve)
    return found


def _find_flipped(surface):
    """The curves pointing the opposite way from the curve before them, when
    the loft doesn't reverse them itself (autoReverse off)."""
    node = loft_node(surface)
    if not node or cmds.getAttr(f"{node}.autoReverse"):
        return []
    found, before = [], None
    for index, shape in _inputs(node):
        if not _is_curve(shape):
            continue
        direction = _direction(shape)
        if cmds.getAttr(f"{node}.reverse[{index}]"):
            direction = -direction
        if before is not None and direction.length() > 1e-9 and before.length() > 1e-9 and direction * before < 0:
            found.append(parent_of(shape))
        before = direction
    return found


def _per_surface(find, text):
    """A check function: ``find(surface)`` on each surface among ``nodes``,
    one :class:`Problem` per surface that has something, selecting what it found."""

    def run(nodes):
        problems = []
        for surface in surfaces(nodes):
            items = find(surface)
            if items:
                problems.append(Problem(f"{short(surface)}: {text(surface, items)}", items))
        return problems

    return run


CHECKS = (
    Check("not_loft", "Not a loft", "The surface isn't driven by a loft node, so there's no loft to save.",
          _per_surface(_find_not_loft, lambda surface, items: "not driven by a loft")),
    Check("unsupported", "Unsupported inputs",
          "A loft input isn't a NURBS curve (an isoparm or curve-on-surface), which can't be found by name.",
          _per_surface(_find_unsupported, lambda surface, items: "lofted from something that isn't a curve")),
    Check("names", "Duplicate names",
          "The surface or an input curve has a name another node also has; Builder finds them by name.",
          _per_surface(_find_names,
                       lambda surface, items: f"names also used by other nodes: {', '.join(short_name(i) for i in items)}")),
    Check("flipped", "Flipped curves",
          "With autoReverse off, a curve points the opposite way from the one before it, twisting the surface.",
          _per_surface(_find_flipped,
                       lambda surface, items: f"flipped {plural(len(items), 'curve')}: {', '.join(short_name(i) for i in items)}")),
)  # fmt: skip
