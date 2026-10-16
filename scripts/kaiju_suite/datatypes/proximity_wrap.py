"""ProximityWrap (.pwrap): proximityWrap deformers saved as data and rebound by name.

:func:`gather` saves every proximityWrap on the given meshes (classic
``wrap`` deformers are left out): which meshes it deforms, its driver
meshes, its settings and per-driver settings, and its painted weights,
sparse. :func:`apply` finds the meshes and drivers by name, replaces a
proximityWrap of the same name and binds a new one after the mesh's
existing deformers, so it sits on top of skin. A proximityWrap binds to its
drivers' undeformed shape.

Missing meshes are skipped with a warning; a proximityWrap whose driver is
missing is skipped with a warning. Ambiguous names, a changed vertex count
on a mesh with painted weights, or a name taken by another node stop the
apply before anything changes.

:data:`CHECKS` are QC checks on the proximityWraps of given meshes (no
proximityWrap, missing driver, below skin, disabled, duplicate names), run
by the ProximityWrap Tool's QC tab and before Builder publishes. They
change nothing.
"""

from maya import cmds

from kaiju_suite import datatypes
from kaiju_suite.core import deformers
from kaiju_suite.core.checks import Check, Problem
from kaiju_suite.core.selection import short_name
from kaiju_suite.datatypes import mesh_shape, plural, short

KIND = "proximity_wrap"
EXTENSION = ".pwrap"

PROXIMITY = "proximityWrap"

# Deformer settings saved.
SETTINGS = (
    "envelope",
    "wrapMode",
    "maxDrivers",
    "falloffScale",
    "dropoffRateScale",
    "scaleCompensation",
    "coordinateFrames",
    "smoothNormals",
    "spanSamples",
    "smoothInfluences",
    "softNormalization",
)
# Per-driver settings, in each ``drivers[i]`` compound.
DRIVER_SETTINGS = (
    "driverStrength",
    "driverFalloffStart",
    "driverFalloffEnd",
    "driverDropoffRate",
    "driverUseTransformAsDeformation",
    "driverScaleCompensation",
    "driverWrapMode",
    "driverOverrideSmoothNormals",
    "driverSmoothNormals",
    "driverOverrideSpanSamples",
    "driverSpanSamples",
    "driverOverrideSmoothInfluences",
    "driverSmoothInfluences",
)
_DIGITS = 6
# What nodeState's values mean (0 is Normal).
_NODE_STATES = ("Normal", "HasNoEffect", "Blocking", "Waiting-Normal", "Waiting-HasNoEffect", "Waiting-Blocking")


def value(plug):
    """``plug``'s value, floats rounded so the same setting saves the same."""
    found = cmds.getAttr(plug)
    return round(found, _DIGITS) if isinstance(found, float) else found


def proximity_wraps(shape):
    """The proximityWraps deforming ``shape``, first evaluated first. A
    driver's own deformers are in its history too; only nodes with ``shape``
    as an output count."""
    return deformers.deformers_on(shape, [PROXIMITY])


def _driver_sources(node):
    """``[(index, source or None)]`` for each of ``node``'s driver slots, in
    index order: the long name of the shape feeding its driver geometry."""
    found = []
    for index in cmds.getAttr(f"{node}.drivers", multiIndices=True) or []:
        source = cmds.listConnections(
            f"{node}.drivers[{index}].driverGeometry", source=True, destination=False, shapes=True
        )
        found.append((index, cmds.ls(source[0], long=True)[0] if source else None))
    return found


def drivers(node):
    """``[(index, shape)]`` of ``node``'s connected drivers, in index order."""
    return [(index, shape) for index, shape in _driver_sources(node) if shape]


def record(node):
    """proximityWrap ``node`` as data: its meshes (with painted weights),
    drivers (with their settings) and settings. Raises if a driver isn't a
    mesh or it has no drivers."""
    meshes = []
    for shape in cmds.ls(cmds.deformer(node, query=True, geometry=True) or [], long=True):
        transform = cmds.listRelatives(shape, parent=True, fullPath=True)[0]
        vertex_count = cmds.polyEvaluate(shape, vertex=True)
        weights = deformers.read_weights(node, deformers.geometry_index(node, shape), vertex_count)
        meshes.append({"mesh": short_name(transform), "vertex_count": vertex_count, "weights": weights})

    found = []
    for index, shape in drivers(node):
        if cmds.nodeType(shape) != "mesh":
            raise RuntimeError(f"{node}: driver {short_name(shape)} isn't a mesh; only mesh drivers can be published.")
        transform = cmds.listRelatives(shape, parent=True, fullPath=True)[0]
        driver = {"mesh": short_name(transform)}
        for attr in DRIVER_SETTINGS:
            driver[attr] = value(f"{node}.drivers[{index}].{attr}")
        found.append(driver)
    if not found:
        raise RuntimeError(f"{node} has no driver meshes to publish.")

    settings = {attr: value(f"{node}.{attr}") for attr in SETTINGS}
    return {"name": node, "type": PROXIMITY, "meshes": meshes, "drivers": found, "settings": settings}


# -- apply ------------------------------------------------------------------


def present(records):
    """The records whose meshes and drivers are in the scene, with the
    missing meshes left out; the rest are skipped with a warning each."""
    missing = datatypes.skip_missing([m["mesh"] for r in records for m in r["meshes"]], "meshes")
    records = [dict(r, meshes=[m for m in r["meshes"] if m["mesh"] not in missing]) for r in records]
    records = [r for r in records if r["meshes"]]
    missing = datatypes.skip_missing([d["mesh"] for r in records for d in r["drivers"]], "drivers")
    return [r for r in records if not any(d["mesh"] in missing for d in r["drivers"])]


def check(records, label="ProximityWrap"):
    """Map each mesh and driver name in ``records`` to its transform,
    raising before anything changes if a name is ambiguous, a painted mesh's
    vertex count differs, or a deformer's name is taken by another node.

    Works on any record with this module's layout and a ``type``; ``label`` names what's applied in the error.
    """
    names = [m["mesh"] for r in records for m in r["meshes"]] + [d["mesh"] for r in records for d in r["drivers"]]
    transforms, problems = {}, []
    for name in dict.fromkeys(names):
        matches = [m for m in cmds.ls(name, long=True) if cmds.objectType(m, isAType="transform") and mesh_shape(m)]
        if len(matches) != 1:
            found = ", ".join(matches) if matches else "no mesh"
            problems.append(f"{name} doesn't name exactly one mesh ({found})")
        else:
            transforms[name] = matches[0]
    for rec in records:
        for mesh in rec["meshes"]:
            transform = transforms.get(mesh["mesh"])
            if transform is None or not mesh.get("weights"):
                continue
            count = cmds.polyEvaluate(mesh_shape(transform), vertex=True)
            if count != mesh["vertex_count"]:
                problems.append(f"{mesh['mesh']} has {count} vertices, the file has {mesh['vertex_count']}")
    if problems:
        raise RuntimeError(f"Can't apply {label}: {'; '.join(dict.fromkeys(problems))}")

    taken = []
    for rec in records:
        name = rec["name"]
        if not cmds.objExists(name):
            continue
        shapes = [mesh_shape(transforms[m["mesh"]]) for m in rec["meshes"]]
        is_ours = cmds.nodeType(name) == rec["type"] and any(
            deformers.geometry_index(name, s) is not None for s in shapes
        )
        if not is_ours:
            taken.append(name)
    if taken:
        noun = "a wrap" if len(taken) == 1 else "wraps"
        raise RuntimeError(f"Names taken by other nodes, not {noun} of the same type on the same mesh: {', '.join(taken)}")
    return transforms


def rebuild(rec, transforms):
    """Bind proximityWrap record ``rec`` on its meshes and drivers (names
    mapped to transforms by :func:`check`), replacing the node of its name.
    Maya appends it after the meshes' existing deformers, on top of skin.
    Returns the new node."""
    if cmds.objExists(rec["name"]):
        cmds.delete(rec["name"])
    shapes = [mesh_shape(transforms[m["mesh"]]) for m in rec["meshes"]]
    driver_shapes = [mesh_shape(transforms[d["mesh"]]) for d in rec["drivers"]]
    node = cmds.proximityWrap(*shapes, name=rec["name"])[0]
    for attr in SETTINGS:
        cmds.setAttr(f"{node}.{attr}", rec["settings"][attr])
    cmds.proximityWrap(node, edit=True, addDrivers=driver_shapes)
    index_of = {shape: index for index, shape in drivers(node)}
    for shape, saved in zip(driver_shapes, rec["drivers"]):
        for attr in DRIVER_SETTINGS:
            cmds.setAttr(f"{node}.drivers[{index_of[shape]}].{attr}", saved[attr])
    for shape, mesh in zip(shapes, rec["meshes"]):
        deformers.write_weights(node, deformers.geometry_index(node, shape), mesh.get("weights", []))
    return node


# -- the datatype -----------------------------------------------------------


def _without(meshes):
    return [short(m) for m in meshes if not proximity_wraps(mesh_shape(m))]


def selection_problems(selection):
    """Why ``selection`` can't be gathered, as messages."""
    if not selection:
        return ["Nothing selected. Select the meshes with a proximityWrap to publish."]
    meshes = datatypes.meshes(selection)
    if not meshes:
        return ["No meshes selected. Select the meshes with a proximityWrap to publish."]
    bare = _without(meshes)
    if bare:
        return [f"No proximityWrap on: {', '.join(bare)}"]
    return []


def gather(nodes):
    """The proximityWraps on the meshes among ``nodes``."""
    found = []
    for mesh in datatypes.meshes(nodes):
        found.extend(proximity_wraps(mesh_shape(mesh)))
    found = list(dict.fromkeys(found))
    if not found:
        raise RuntimeError("No proximityWrap on the selected meshes to publish.")
    return {"deformers": [record(node) for node in found]}


def apply(payload, info=None):
    """Bind each saved proximityWrap; returns a message."""
    records = present(payload["deformers"])
    transforms = check(records)
    created = []
    for rec in records:
        created.append(rebuild(rec, transforms))
        meshes = ", ".join(m["mesh"] for m in rec["meshes"])
        driven_by = ", ".join(d["mesh"] for d in rec["drivers"])
        datatypes.report(info, f"{created[-1]}: on {meshes}, driven by {driven_by}")
    if not created:
        return "Created no proximityWraps"
    meshes = ", ".join(dict.fromkeys(m["mesh"] for r in records for m in r["meshes"]))
    return f"Created {', '.join(created)} on {meshes}"


def nodes(payload):
    return list(dict.fromkeys(m["mesh"] for r in payload["deformers"] for m in r["meshes"]))


def describe(payload):
    records = payload["deformers"]
    meshes = ", ".join(nodes(payload))
    driven_by = ", ".join(dict.fromkeys(d["mesh"] for r in records for d in r["drivers"]))
    return [plural(len(records), PROXIMITY), f"Meshes: {meshes}", f"Drivers: {driven_by}"]


def compare_view(payload):
    return payload


# -- QC checks --------------------------------------------------------------


def _wrapped(nodes):
    """``(mesh, node)`` for each proximityWrap on each mesh among ``nodes``."""
    return [(mesh, node) for mesh in datatypes.meshes(nodes) for node in proximity_wraps(mesh_shape(mesh))]


def _nodes(nodes):
    """The proximityWraps on the meshes among ``nodes``, each once."""
    return list(dict.fromkeys(node for _, node in _wrapped(nodes)))


def _check_none(nodes):
    return [
        Problem(f"{short(m)}: no proximityWrap", [short(m)])
        for m in datatypes.meshes(nodes)
        if not proximity_wraps(mesh_shape(m))
    ]


def _check_drivers(nodes):
    problems = []
    for node in _nodes(nodes):
        sources = _driver_sources(node)
        if not sources:
            problems.append(Problem(f"{node}: no drivers", [node]))
        for index, shape in sources:
            if shape is None:
                problems.append(Problem(f"{node}: driver {index} isn't connected", [node]))
            elif cmds.nodeType(shape) != "mesh":
                transform = cmds.listRelatives(shape, parent=True, fullPath=True)[0]
                problems.append(Problem(f"{node}: driver {short(transform)} isn't a mesh", [node, short(transform)]))
    return problems


def _check_below_skin(nodes):
    problems = []
    for mesh in datatypes.meshes(nodes):
        order = deformers.deformers_on(mesh_shape(mesh), [PROXIMITY, "skinCluster"])
        skins = [i for i, node in enumerate(order) if cmds.nodeType(node) == "skinCluster"]
        if not skins:
            continue
        last_skin = order[max(skins)]
        for node in order[: max(skins)]:
            if cmds.nodeType(node) == PROXIMITY:
                problems.append(Problem(f"{short(mesh)}: {node} evaluates before {last_skin}", [node, last_skin]))
    return problems


def _check_disabled(nodes):
    problems = []
    for node in _nodes(nodes):
        if abs(cmds.getAttr(f"{node}.envelope")) < 1e-6:
            problems.append(Problem(f"{node}: envelope is 0", [node]))
        state = cmds.getAttr(f"{node}.nodeState")
        if state:
            name = _NODE_STATES[state] if state < len(_NODE_STATES) else str(state)
            problems.append(Problem(f"{node}: node state is {name}", [node]))
    return problems


def _check_duplicate_names(nodes):
    names = []
    for mesh, node in _wrapped(nodes):
        names.append(short_name(mesh))
        names.extend(short_name(cmds.listRelatives(shape, parent=True, fullPath=True)[0]) for _, shape in drivers(node))
    problems = []
    for name in dict.fromkeys(names):
        same = sorted(cmds.ls(name, long=True) or [])
        if len(same) > 1:
            problems.append(Problem(f"{name}: {len(same)} nodes are called {name}", same))
    return problems


CHECKS = (
    Check("no_proximity", "No proximityWrap", "Selected meshes with no proximityWrap.", _check_none),
    Check(
        "missing_driver",
        "Missing driver",
        "proximityWraps with no drivers, or a driver input that's disconnected or isn't a mesh.",
        _check_drivers,
    ),
    Check(
        "below_skin",
        "Below skin",
        "proximityWraps that evaluate before the mesh's skinCluster, so the skin moves the mesh after the wrap.",
        _check_below_skin,
    ),
    Check("disabled", "Disabled", "proximityWraps with envelope 0 or a node state other than Normal.", _check_disabled),
    Check(
        "duplicate_names",
        "Duplicate names",
        "Wrapped meshes and drivers whose name another node also has; items find them by name.",
        _check_duplicate_names,
    ),
)
