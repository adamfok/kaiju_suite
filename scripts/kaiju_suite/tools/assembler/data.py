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
import re

from maya import cmds

from kaiju_suite.core.datafile import FORMAT, DataFormatError, read, write  # noqa: F401 (re-exported)
from kaiju_suite.core.undo import undo_chunk
from kaiju_suite.tools.assembler import runlog, versions
from kaiju_suite.tools.assembler.products import Action, Creator, Panel, Product, is_empty, new_path

_TRAILING_DIGITS = re.compile(r"\d+$")


class MissingNodesError(RuntimeError):
    """Nodes a data file needs that aren't in the scene; see :func:`require_nodes`."""

    def __init__(self, missing, label="nodes"):
        self.missing = list(missing)
        super().__init__(f"Missing {label}: {', '.join(self.missing)}")


# -- nodes ------------------------------------------------------------------


def unique_name(name):
    """``name`` if no node has it, else the next free one, numbered the way
    Maya does it: ``spine_jnt`` → ``spine_jnt1``, a taken ``joint1`` → ``joint2``.

    Checks every node, not just siblings, so names found later by name
    stay unambiguous.
    """
    if not cmds.objExists(name):
        return name
    base = _TRAILING_DIGITS.sub("", name) or name
    number = 1
    while cmds.objExists(f"{base}{number}"):
        number += 1
    return f"{base}{number}"


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


# -- the product base class -------------------------------------------------


class DataProduct(Product):
    """A product whose items are data files published from the selection.

    Subclasses set ``name``, ``kind`` (the header's ``kaiju`` value),
    ``extension`` (one, lower case, with the dot) and ``order``, and implement
    :meth:`gather`, :meth:`apply`, :meth:`selection_problems` and
    :meth:`describe`. The rest (New, Run, Publish, versions, the double-click
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
