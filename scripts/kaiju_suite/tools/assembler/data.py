"""Rig-data products: JSON files published from the scene and applied back.

Each file holds one item, with a header naming what it is::

    {"kaiju": "joints", "format": 1, "data": {...}}

The save/load half (gather a payload, apply it, describe it) lives in
:mod:`kaiju_suite.datatypes`, shared with the tools; so do the node helpers
(:func:`unique_name`, :func:`create_node`, :func:`require_nodes`,
:func:`plural`, ...), re-exported here. :class:`DataProduct` is the
Assembler step on top: New, Publish, versions, the info panel, Run in one
undo chunk. No Qt here.
"""

import os

from maya import cmds

from kaiju_suite.datatypes import (  # noqa: F401 (re-exported)
    FORMAT,
    DataFormatError,
    MissingNodesError,
    count_problem,
    create_node,
    node_path,
    outside_parents,
    parent_of,
    plural,
    read,
    require_nodes,
    require_unique,
    resolve_nodes,
    saved_points,
    skip_missing,
    unique_name,
    vertex_remap,
    write,
)
from kaiju_suite.core.undo import undo_chunk
from kaiju_suite.tools.assembler import compare
from kaiju_suite.tools.assembler import runlog, versions
from kaiju_suite.tools.assembler.products import Action, Creator, Panel, Product, is_empty, new_path


# -- the product base class -------------------------------------------------


class DataProduct(Product):
    """A product whose items are data files published from the selection.

    Subclasses set ``name``, ``order`` and ``datatype``: the
    :mod:`kaiju_suite.datatypes` module that gathers, applies and describes
    the data (``kind`` and ``extension`` come from it). The rest (New, Run,
    Publish, versions, the double-click panel, right-click **Update from
    Scene**) comes from here.

    Products not moved to :mod:`kaiju_suite.datatypes` yet set ``kind`` and
    ``extension`` (one, lower case, with the dot) themselves and implement
    :meth:`gather`, :meth:`apply`, :meth:`selection_problems`,
    :meth:`describe` and optionally :meth:`nodes` and :meth:`compare_view`.
    """

    datatype = None
    runnable = True
    versioned = True

    @property
    def kind(self):
        return self.datatype.KIND

    @property
    def extension(self):
        return self.datatype.EXTENSION

    @property
    def extensions(self):
        return (self.extension,)

    @property
    def creators(self):
        return (Creator(self.name, self.create),)

    # -- the datatype, or for subclasses to override --------------------------

    def gather(self, selection):
        """The payload (JSON-serializable) to publish from ``selection``
        (long names). Raise with a message if it can't be published."""
        if self.datatype is None:
            raise NotImplementedError
        return self.datatype.gather(selection)

    def apply(self, payload):
        """Apply a payload to the scene. May return a message for the user.

        Skip what's missing from the scene with a warning (see
        :func:`skip_missing`); check the rest first and raise before changing
        anything. Runs inside one undo chunk.
        """
        if self.datatype is None:
            raise NotImplementedError
        return self.datatype.apply(payload, info=runlog.info)

    def selection_problems(self):
        """Why the current selection can't be published, as messages."""
        if self.datatype is None:
            return []
        return self.datatype.selection_problems(cmds.ls(selection=True, long=True) or [])

    def describe(self, payload):
        """Info lines about a payload for the double-click panel."""
        if self.datatype is None:
            return []
        return self.datatype.describe(payload)

    def nodes(self, payload):
        """The names of the nodes (or components) ``payload`` was gathered
        from, such that :meth:`gather` on them gathers the same kind of
        payload again. Products whose datatype has it, or that implement it,
        get right-click **Update from Scene**; the others don't."""
        if self.datatype is None:
            raise NotImplementedError
        return self.datatype.nodes(payload)

    def compare_view(self, payload):
        """``payload`` as the side-by-side compare window shows it. As saved
        unless the datatype (or an override) says otherwise, e.g. to key
        weights by influence name so the same weights in another order
        compare equal."""
        view = getattr(self.datatype, "compare_view", None)
        return view(payload) if view else payload

    # -- Update from Scene ---------------------------------------------------

    @property
    def can_update(self):
        """Whether items get **Update from Scene** (the product or its datatype has :meth:`nodes`)."""
        if self.datatype is not None:
            return hasattr(self.datatype, "nodes")
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

    def compare_files(self, old_path, new_path):
        payloads = read(old_path, self.kind), read(new_path, self.kind)
        try:
            payloads = [self.compare_view(p) for p in payloads]
        except (KeyError, TypeError, ValueError, AttributeError, IndexError):
            pass  # a payload the product doesn't expect (e.g. an older format): show it as saved
        return compare.tree(*payloads)

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
