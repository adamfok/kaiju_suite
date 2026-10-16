"""NurbsSurface (.surface): NURBS surfaces saved as data and rebuilt as new
surfaces (ribbons, sliding surfaces, follicle surfaces, ...). Builder only;
there's no Assembler product.

:func:`gather` saves each given surface (its transform, or one of its
surface shapes or CVs): name, parent name, local transform (translate,
rotate, scale, rotate order) and every visible NURBS surface shape under it:
degree, form and knots in U and V, object-space CVs and display overrides.
Rational CV weights and trim curves aren't saved (QC warns about both). Only
the given surfaces are saved, not the surfaces below them; a given surface
under another given surface stays under it.

:func:`apply` always creates new surfaces and never changes existing ones,
as Mesh does: a name that's taken gets the next free one (``ribbon`` →
``ribbon1``, shape ``ribbon1Shape``). Each new surface gets
``initialShadingGroup``. A surface whose parent isn't in the file goes under
the scene's node of that name if there is one, otherwise under the world;
if several nodes have that name, nothing is created. Shapes are built with
MEL ``setAttr`` on the surface data (the line a .ma file holds), so they're
exact and the whole apply undoes in one step.

:data:`CHECKS` are QC checks on given surfaces (duplicate names, rational
CVs, trimmed surfaces, construction history), run by the Surface Tool's QC
tab and before Builder publishes. Checks change nothing.
"""

from maya import cmds, mel
from maya.api import OpenMaya as om

from kaiju_suite.core.checks import Check, Problem
from kaiju_suite.core.selection import short_name
from kaiju_suite.datatypes import create_node, node_path, outside_parents, parent_of, plural, short, unique_name

KIND = "nurbs_surface"
EXTENSION = ".surface"

_VECTORS = ("translate", "rotate", "scale")
# Shape display overrides saved with each surface (overrideColorRGB too).
DISPLAY = ("overrideEnabled", "overrideDisplayType", "overrideRGBColors", "overrideColor")


def shapes(transform):
    """The visible NURBS surface shapes under ``transform`` (long names)."""
    return (
        cmds.listRelatives(transform, shapes=True, noIntermediate=True, fullPath=True, type="nurbsSurface") or []
    )


def _split_selection(selection):
    """The selected surface transforms (a selected surface shape or CV counts
    as its transform), in selection order, and the selected nodes that
    aren't surfaces."""
    transforms, others = [], []
    for node in cmds.ls(selection, long=True, objectsOnly=True) or []:
        if cmds.objectType(node, isAType="transform") and shapes(node):
            transforms.append(node)
        elif cmds.objectType(node) == "nurbsSurface" and not cmds.getAttr(f"{node}.intermediateObject"):
            transforms.append(parent_of(node))
        else:
            others.append(node)
    return list(dict.fromkeys(transforms)), list(dict.fromkeys(others))


def surfaces(selection):
    """The surface transforms in ``selection`` (a shape or CV stands for its
    transform), as long names, in order, each once. Other nodes are left out."""
    return _split_selection(selection)[0] if selection else []


def _fn(shape):
    return om.MFnNurbsSurface(om.MSelectionList().add(shape).getDagPath(0))


def _shape_record(shape):
    fn = _fn(shape)
    record = {
        "name": short_name(shape),
        "degree_u": fn.degreeInU,
        "degree_v": fn.degreeInV,
        # 0 open, 1 closed, 2 periodic
        "form_u": cmds.getAttr(f"{shape}.formU"),
        "form_v": cmds.getAttr(f"{shape}.formV"),
        "knots_u": list(fn.knotsInU()),
        "knots_v": list(fn.knotsInV()),
        # U by U, each row along V, as MFnNurbsSurface and the .ma line order them.
        "cvs": [[p.x, p.y, p.z] for p in fn.cvPositions(om.MSpace.kObject)],
    }
    for attr in DISPLAY:
        record[attr] = cmds.getAttr(f"{shape}.{attr}")
    record["overrideColorRGB"] = list(cmds.getAttr(f"{shape}.overrideColorRGB")[0])
    return record


def _build_shape(parent, record, name):
    """Create the surface of ``record`` under ``parent``, named ``name`` or
    the next free name; returns the new shape's long name."""
    shape = cmds.createNode("nurbsSurface", name=unique_name(name), parent=parent, skipSelect=True)
    shape = cmds.ls(shape, long=True)[0]
    knots_u = [repr(float(k)) for k in record["knots_u"]]
    knots_v = [repr(float(k)) for k in record["knots_v"]]
    cvs = [repr(float(v)) for cv in record["cvs"] for v in cv]
    values = [
        record["degree_u"], record["degree_v"], record["form_u"], record["form_v"], "no",
        len(knots_u), *knots_u, len(knots_v), *knots_v, len(record["cvs"]), *cvs,
    ]  # fmt: skip
    mel.eval(f'setAttr "{shape}.cc" -type "nurbsSurface" {" ".join(map(str, values))};')
    for attr in DISPLAY:
        if attr in record:
            cmds.setAttr(f"{shape}.{attr}", record[attr])
    if "overrideColorRGB" in record:
        cmds.setAttr(f"{shape}.overrideColorRGB", *record["overrideColorRGB"])
    return shape


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
    record["shapes"] = [_shape_record(shape) for shape in shapes(transform)]
    return record


def selection_problems(selection):
    if not selection:
        return ["Nothing selected. Select the NURBS surfaces to publish."]
    transforms, others = _split_selection(selection)
    if others:
        names = ", ".join(short_name(n) for n in others)
        return [f"Not NURBS surfaces: {names}. Select only NURBS surfaces to publish."]
    if not transforms:
        return ["No NURBS surfaces selected. Select the NURBS surfaces to publish."]
    return []


def gather(nodes):
    transforms, others = _split_selection(nodes) if nodes else ([], [])
    if others:
        raise RuntimeError(f"Not NURBS surfaces: {', '.join(short_name(n) for n in others)}")
    if not transforms:
        raise RuntimeError("No NURBS surfaces selected to publish.")
    # Parents before children, so apply can create a surface's parent first.
    transforms.sort(key=lambda path: path.count("|"))
    index_of, records = {}, []
    for transform in transforms:
        records.append(_record(transform, index_of))
        index_of[transform] = len(records) - 1
    return {"surfaces": records}


def apply(payload, info=None):
    records = payload["surfaces"]
    outside = outside_parents(records)
    uuids, renamed = [], []
    for record in records:
        index = record.get("parent_index")
        parent = node_path(uuids[index]) if index is not None else outside.get(record["parent"])
        uuid = create_node("transform", record["name"], parent)
        transform = node_path(uuid)
        for attr in _VECTORS:
            cmds.setAttr(f"{transform}.{attr}", *record[attr])
        cmds.setAttr(f"{transform}.rotateOrder", record["rotateOrder"])
        leaf = short_name(transform)
        for i, shape in enumerate(record["shapes"]):
            _build_shape(transform, shape, f"{leaf}Shape" if i == 0 else f"{leaf}Shape{i}")
        if record["shapes"]:
            cmds.sets(node_path(uuid), edit=True, forceElement="initialShadingGroup")
        uuids.append(uuid)
        if leaf != record["name"]:
            renamed.append(f"{record['name']} → {leaf}")
    message = f"Created {plural(len(records), 'NURBS surface')}"
    if renamed:
        message += f" (names taken, renamed: {', '.join(renamed)})"
    return message


def nodes(payload):
    return [r["name"] for r in payload["surfaces"]]


def describe(payload):
    records = payload["surfaces"]
    return [plural(len(records), "NURBS surface"), ", ".join(r["name"] for r in records)]


def compare_view(payload):
    return payload


# -- QC checks --------------------------------------------------------------

# Nodes in a surface's history that aren't construction history.
_NOT_HISTORY = ("geometryFilter", "tweak", "groupParts", "groupId", "shadingEngine", "objectSet", "dagPose")


def _find_names(surface):
    return [surface] if len(cmds.ls(short_name(surface))) > 1 else []


def _find_rational(surface):
    """The CVs whose weight isn't 1, on every visible shape."""
    found = []
    for shape in shapes(surface):
        fn = _fn(shape)
        count_v = fn.numCVsInV
        for i, p in enumerate(fn.cvPositions(om.MSpace.kObject)):
            if abs(p.w - 1.0) > 1e-9:
                found.append(f"{shape}.cv[{i // count_v}][{i % count_v}]")
    return found


def _find_trimmed(surface):
    return [surface] if any(_fn(shape).isTrimmedSurface for shape in shapes(surface)) else []


def _find_history(surface):
    for shape in shapes(surface):
        found = cmds.listHistory(shape, pruneDagObjects=True) or []
        if any(not any(cmds.objectType(node, isAType=kind) for kind in _NOT_HISTORY) for node in found):
            return [surface]
    return []


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
    Check("names", "Duplicate name", "Another node has the same name; Builder finds surfaces by name.",
          _per_surface(_find_names, lambda surface, items: f"another node is called {short_name(surface)}")),
    Check("rational", "Rational CVs",
          "CVs with a weight other than 1. Weights aren't saved: the rebuilt surface has every weight at 1.",
          _per_surface(_find_rational,
                       lambda surface, items: f"{plural(len(items), 'CV')} with weights (weights aren't saved)")),
    Check("trimmed", "Trimmed", "Trimmed surfaces. Trim curves aren't saved: the rebuilt surface is untrimmed.",
          _per_surface(_find_trimmed, lambda surface, items: "trimmed (trim curves aren't saved)")),
    Check("history", "Construction history",
          "The surface is driven by construction history (deformers don't count), which isn't saved.",
          _per_surface(_find_history, lambda surface, items: "construction history (isn't saved)")),
)  # fmt: skip
