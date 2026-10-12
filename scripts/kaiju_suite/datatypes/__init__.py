"""Rig data saved to files and applied back: the save/load half of the
Assembler's data products, shared with the tools.

One module per kind of data (:mod:`.skin`, ...). Each has ``KIND`` (the
file header's ``kaiju`` value), ``EXTENSION`` and these functions:

- ``gather(nodes)``: the payload (JSON-serializable) for ``nodes`` (long
  names). Raises with a message if it can't be gathered.
- ``apply(payload, info=None)``: apply a payload to the scene; returns a
  message for the user. Skips what's missing from the scene with a warning
  (see :func:`skip_missing`), checks the rest and raises before changing
  anything. ``info`` is called with one line per item applied.
- ``selection_problems(selection)``: why ``selection`` can't be gathered.
- ``describe(payload)``: info lines about a payload.
- ``nodes(payload)``: the names ``gather`` would take to gather it again.
- ``compare_view(payload)``: the payload as a side-by-side compare shows it.

:func:`save` and :func:`load` write and apply one module's files. The file
format is :mod:`kaiju_suite.core.datafile`'s.

Imports go ``tools`` → ``datatypes`` → ``core``: nothing here imports the
Assembler, ``ui``, ``rig_module`` or Qt. Warnings go through
``cmds.warning``; the Assembler's run log picks them up.
"""

from maya import cmds

from kaiju_suite.core import matching
from kaiju_suite.core.datafile import FORMAT, DataFormatError, read, write  # noqa: F401 (re-exported)
from kaiju_suite.core.log import get_logger
from kaiju_suite.core.nodes import unique_name  # noqa: F401 (re-exported)

log = get_logger(__name__)


class MissingNodesError(RuntimeError):
    """Nodes a data file needs that aren't in the scene; see :func:`require_nodes`."""

    def __init__(self, missing, label="nodes"):
        self.missing = list(missing)
        super().__init__(f"Missing {label}: {', '.join(self.missing)}")


# -- files ------------------------------------------------------------------


def save(module, path, nodes):
    """Gather ``nodes`` with datatype ``module`` and write them to ``path``."""
    return write(path, module.KIND, module.gather(nodes))


def load(module, path, info=None):
    """Apply the ``module.KIND`` file at ``path``; returns ``module.apply``'s
    message. Raises :class:`DataFormatError` if it holds another kind."""
    return module.apply(read(path, module.KIND), info=info)


def warning(message):
    """Show ``message`` as a Maya warning (the Assembler logs it for its step)."""
    cmds.warning(message)


def report(info, message):
    """Pass ``message`` to ``info``, or to the log if there's no ``info``."""
    (info or log.info)(message)


# -- nodes ------------------------------------------------------------------


def short(path):
    """The shortest unique name of ``path``, as Maya shows it."""
    return cmds.ls(path)[0]


def mesh_shape(transform):
    """The (non-intermediate) mesh shape of ``transform``, or ``None``."""
    found = cmds.listRelatives(transform, shapes=True, noIntermediate=True, type="mesh", fullPath=True)
    return found[0] if found else None


def meshes(selection):
    """The mesh transforms in ``selection`` (a shape or component stands for
    its transform), as long names, in order, each once."""
    found = []
    for node in cmds.ls(selection, objectsOnly=True, long=True) or []:
        if cmds.nodeType(node) == "mesh":
            node = cmds.listRelatives(node, parent=True, fullPath=True)[0]
        if cmds.objectType(node, isAType="transform") and mesh_shape(node):
            found.append(node)
    return list(dict.fromkeys(found))


def create_node(node_type, name, parent=None):
    """Create a ``node_type`` node under ``parent`` (world if ``None``), named
    ``name`` or the next free name (see :func:`unique_name`).

    Doesn't change the selection. Returns the node's UUID: keep that rather
    than its path, which goes stale when a parent is renamed or moved.
    """
    kwargs = {"name": unique_name(name), "skipSelect": True}
    if parent:
        kwargs["parent"] = parent
    node = cmds.createNode(node_type, **kwargs)
    return cmds.ls(node, uuid=True)[0]


def node_path(uuid):
    """The long path of the node with ``uuid``."""
    found = cmds.ls(uuid, long=True)
    if not found:
        raise RuntimeError(f"No node with UUID {uuid}")
    return found[0]


def require_nodes(names, label="nodes"):
    """Raise one :class:`MissingNodesError` naming every one of ``names`` that
    isn't in the scene, e.g. ``Missing influences: L_arm_jnt, R_arm_jnt``.

    Call it before changing anything, so applying never half-applies.
    """
    missing = [n for n in dict.fromkeys(names) if not cmds.objExists(n)]
    if missing:
        raise MissingNodesError(missing, label)


def skip_missing(names, label="nodes"):
    """The set of ``names`` that aren't in the scene, for the caller to skip.

    Shows one warning naming them, e.g. ``Skipped missing meshes: head``, so
    an Assembler step ends with the warning status instead of failing.
    """
    missing = [n for n in dict.fromkeys(names) if not cmds.objExists(n)]
    if missing:
        warning(f"Skipped missing {label}: {', '.join(missing)}")
    return set(missing)


def require_unique(names):
    """Raise if any of ``names`` matches several nodes, naming them all."""
    ambiguous = [f"{name} ({', '.join(cmds.ls(name, long=True))})" for name in names if len(cmds.ls(name)) > 1]
    if ambiguous:
        raise RuntimeError(f"Several nodes have the same name, can't tell which to use: {'; '.join(ambiguous)}")


def resolve_nodes(names):
    """Find each of ``names`` in the scene, for gathering again.

    Returns ``(paths, problems)``: the long path of each name that matches
    exactly one node, in order without repeats, and messages naming the ones
    that are missing or match several nodes. A component such as
    ``body.f[0:9]`` is found by its node and keeps its component.
    """
    paths, missing, ambiguous = [], [], []
    for name in dict.fromkeys(names):
        node, dot, component = name.partition(".")
        matches = cmds.ls(node, long=True) or []
        if not matches:
            missing.append(name)
        elif len(matches) > 1:
            ambiguous.append(f"Several nodes are called {node}, can't tell which to use: {', '.join(matches)}")
        else:
            paths.append(matches[0] + dot + component)
    problems = [f"Missing in the scene: {', '.join(missing)}"] if missing else []
    return paths, problems + list(dict.fromkeys(ambiguous))


def parent_of(path):
    """The long path of ``path``'s parent, or ``None`` under the world."""
    found = cmds.listRelatives(path, parent=True, fullPath=True)
    return found[0] if found else None


def outside_parents(records):
    """Map each saved parent name to the scene node of that name (``None``
    for world). Records whose parent is in the file itself (a set
    ``parent_index``) are skipped. Raises, before anything is created, if a
    name matches several nodes."""
    found, ambiguous = {}, []
    for record in records:
        name = record["parent"]
        if record.get("parent_index") is not None or not name or name in found:
            continue
        matches = cmds.ls(name, type="transform", long=True) or []
        if len(matches) > 1:
            ambiguous.append(f"{name} ({', '.join(matches)})")
        found[name] = matches[0] if matches else None
    if ambiguous:
        raise RuntimeError(f"Several nodes have the parent's name, can't tell which to use: {'; '.join(ambiguous)}")
    return found


def plural(count, word, plural=None):
    """``plural(2, "mesh", "meshes")`` → ``"2 meshes"``; ``plural`` defaults to ``word + "s"``."""
    return f"{count} {word if count == 1 else (plural or word + 's')}"


# -- changed topology -------------------------------------------------------

# Decimals kept for saved point positions.
_POINT_DECIMALS = 6


def saved_points(mesh):
    """``mesh``'s rest positions (object space, before deformers), rounded,
    to save with per-vertex data so it can be remapped later; see
    :func:`vertex_remap`."""
    return [[round(c, _POINT_DECIMALS) for c in p] for p in matching.rest_points(mesh)]


def count_problem(record, mesh, label):
    """Why ``record`` can't go onto ``mesh``, or ``None``: its vertex count
    differs and the file has no saved points to remap by (files published
    before points were saved)."""
    count = matching.vertex_count(mesh)
    if count == record["vertex_count"] or record.get("points"):
        return None
    return f"{label} has {count} vertices, the file has {record['vertex_count']}"


def vertex_remap(record, mesh, label, what):
    """``None`` if ``mesh`` has the vertex count saved in ``record``. Else,
    for each vertex of ``mesh``, the saved vertex closest to it (matching
    ``mesh``'s rest positions to the record's saved ``points``), with a
    warning that ``what`` were remapped."""
    count = matching.vertex_count(mesh)
    if count == record["vertex_count"]:
        return None
    mapping = matching.closest_indices(record["points"], matching.rest_points(mesh))
    warning(
        f"{label}: the vertex count changed from {record['vertex_count']} to {count}; "
        f"remapped {what} by closest point"
    )
    return mapping
