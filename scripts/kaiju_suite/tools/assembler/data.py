"""Rig-data products: JSON files published from the scene and applied back.

Each file holds one item, with a header naming what it is::

    {"kaiju": "joints", "format": 1, "data": {...}}

:func:`read` and :func:`write` live in :mod:`kaiju_suite.core.datafile`
and are re-exported here.

:class:`DataProduct` is the base class for such products (Joints, Mesh,
SkinCluster, ...): subclasses only say how to gather the payload from the
selection and how to apply it. The node helpers here (:func:`unique_name`,
:func:`create_node`, :func:`require_nodes`, :func:`plural`, ...) are
shared by them. No Qt here.
"""

import os

from maya import cmds

from kaiju_suite.core import matching
from kaiju_suite.core.datafile import FORMAT, DataFormatError, read, write  # noqa: F401 (re-exported)
from kaiju_suite.core.nodes import unique_name  # noqa: F401 (re-exported)
from kaiju_suite.core.undo import undo_chunk
from kaiju_suite.tools.assembler import runlog, versions
from kaiju_suite.tools.assembler.products import Action, Creator, Panel, Product, is_empty, new_path

class MissingNodesError(RuntimeError):
    """Nodes a data file needs that aren't in the scene; see :func:`require_nodes`."""

    def __init__(self, missing, label="nodes"):
        self.missing = list(missing)
        super().__init__(f"Missing {label}: {', '.join(self.missing)}")


# -- nodes ------------------------------------------------------------------


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

    Call it before changing anything, so a Run never half-applies.
    """
    missing = [n for n in dict.fromkeys(names) if not cmds.objExists(n)]
    if missing:
        raise MissingNodesError(missing, label)


def skip_missing(names, label="nodes"):
    """The set of ``names`` that aren't in the scene, for the caller to skip.

    Logs one warning naming them, e.g. ``Skipped missing meshes: head``, so
    the step ends with the warning status (see :mod:`.runlog`) instead of
    failing.
    """
    missing = [n for n in dict.fromkeys(names) if not cmds.objExists(n)]
    if missing:
        runlog.warning(f"Skipped missing {label}: {', '.join(missing)}")
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
    runlog.warning(
        f"{label}: the vertex count changed from {record['vertex_count']} to {count}; "
        f"remapped {what} by closest point"
    )
    return mapping


# -- the product base class -------------------------------------------------


class DataProduct(Product):
    """A product whose items are data files published from the selection.

    Subclasses set ``name``, ``kind`` (the header's ``kaiju`` value),
    ``extension`` (one, lower case, with the dot) and ``order``, and implement
    :meth:`gather`, :meth:`apply`, :meth:`selection_problems` and
    :meth:`describe`, and optionally :meth:`nodes` for right-click **Update
    from Scene**. The rest (New, Run, Publish, versions, the double-click
    panel) comes from here.
    """

    kind = ""
    extension = ""
    runnable = True
    versioned = True

    @property
    def extensions(self):
        return (self.extension,)

    @property
    def creators(self):
        return (Creator(self.name, self.create),)

    # -- for subclasses ------------------------------------------------------

    def gather(self, selection):
        """The payload (JSON-serializable) to publish from ``selection``
        (long names). Raise with a message if it can't be published."""
        raise NotImplementedError

    def apply(self, payload):
        """Apply a payload to the scene. May return a message for the user.

        Skip what's missing from the scene with a warning (see
        :func:`skip_missing`); check the rest first and raise before changing
        anything. Runs inside one undo chunk.
        """
        raise NotImplementedError

    def selection_problems(self):
        """Why the current selection can't be published, as messages."""
        return []

    def describe(self, payload):
        """Info lines about a payload for the double-click panel."""
        return []

    def nodes(self, payload):
        """The names of the nodes (or components) ``payload`` was gathered
        from, such that :meth:`gather` on them gathers the same kind of
        payload again. Implementing it adds right-click **Update from Scene**;
        products that don't, don't get it."""
        raise NotImplementedError

    # -- Update from Scene ---------------------------------------------------

    @property
    def can_update(self):
        """Whether items get **Update from Scene** (the product implements :meth:`nodes`)."""
        return type(self).nodes is not DataProduct.nodes

    def _update_targets(self, path):
        """``(paths, problems)`` for re-gathering ``path`` from the scene."""
        if is_empty(path):
            return [], [f"{os.path.basename(path)} is empty. Publish it from a selection first."]
        try:
            names = self.nodes(read(path, self.kind))
        except (OSError, ValueError, KeyError) as e:
            return [], [f"Can't read {os.path.basename(path)}: {e}"]
        return resolve_nodes(names)

    def update_problems(self, path):
        """Why ``path`` can't be updated from the scene now, as messages:
        nodes in its file that are missing or match several nodes."""
        return self._update_targets(path)[1]

    def update_from_scene(self, path):
        """Gather again from the nodes named in ``path`` and publish the
        result as its next version, whatever is selected. Raises, saving
        nothing, if any of those nodes is missing or ambiguous."""
        paths, problems = self._update_targets(path)
        if problems:
            raise RuntimeError(f"Can't update {os.path.basename(path)} from the scene. {' '.join(problems)}")
        payload = self.gather(paths)
        return versions.export_into(path, lambda target: write(target, self.kind, payload))

    def actions(self, path):
        if not self.can_update or is_empty(path):
            return []
        return [Action("Update from Scene", lambda: self.update_from_scene(path))]

    # -- Product -------------------------------------------------------------

    def create(self, directory, name, ext=None):
        """New ▸ <name>: an empty entry that a build skips until published into."""
        path = new_path(directory, name, self.extension)
        with open(path, "wb"):
            pass
        return path

    def run(self, path):
        if is_empty(path):
            return None
        payload = read(path, self.kind)
        with undo_chunk(f"Assembler {self.name}"):
            return self.apply(payload)

    def publish(self, path):
        # No question first: the content it replaces is kept as a version.
        return Action("Publish", lambda: self.publish_into(path))

    def publish_into(self, path):
        """Write the current selection into ``path`` as its next version."""
        payload = self.gather(cmds.ls(selection=True, long=True) or [])
        return versions.export_into(path, lambda target: write(target, self.kind, payload))

    def publish_problems(self, path):
        return self.selection_problems()

    def publish_warnings(self, path):
        return self.selection_warnings()

    def selection_warnings(self):
        """Messages about the selection that don't stop Publish; the user is
        asked whether to publish anyway. None unless overridden."""
        return []

    def panel(self, path):
        if is_empty(path):
            return Panel(["Empty: nothing published into it yet."], [])
        try:
            lines = self.describe(read(path, self.kind))
        except (OSError, ValueError) as e:
            lines = [f"Can't read {os.path.basename(path)}: {e}"]
        return Panel(list(lines), [])
