"""Rig-data products: JSON files published from the scene and applied back.

Each file holds one item, with a header naming what it is::

    {"kaiju": "joints", "format": 1, "data": {...}}

:class:`DataProduct` is the base class for such products (Joints, Mesh,
SkinCluster, ...): subclasses only say how to gather the payload from the
selection and how to apply it. The node helpers here (:func:`unique_name`,
:func:`create_node`, :func:`require_nodes`) are shared by them. No Qt here.
"""

import json
import os
import re

from maya import cmds

from kaiju_suite.core.undo import undo_chunk
from kaiju_suite.tools.assembler import versions
from kaiju_suite.tools.assembler.products import Action, Creator, Panel, Product, new_path

# The file format this code writes; files with a newer one are refused.
FORMAT = 1

_TRAILING_DIGITS = re.compile(r"\d+$")


class DataFormatError(ValueError):
    """A data file that isn't valid, or isn't the kind expected."""


class MissingNodesError(RuntimeError):
    """Nodes a data file needs that aren't in the scene; see :func:`require_nodes`."""

    def __init__(self, missing, label="nodes"):
        self.missing = list(missing)
        super().__init__(f"Missing {label}: {', '.join(self.missing)}")


# -- files ------------------------------------------------------------------


def write(path, kind, payload):
    """Write ``payload`` to ``path`` as a ``kind`` data file.

    The output is deterministic (no timestamps), so publishing unchanged
    content gives the same bytes and adds no new version.
    """
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"kaiju": kind, "format": FORMAT, "data": payload}, f, indent=1)
        f.write("\n")
    return path


def read(path, kind):
    """The payload of the ``kind`` data file at ``path``.

    Raises :class:`DataFormatError` if it isn't JSON, holds another kind,
    or was written in a newer format.
    """
    name = os.path.basename(path)
    try:
        with open(path, encoding="utf-8") as f:
            content = json.load(f)
    except (ValueError, UnicodeDecodeError) as e:
        raise DataFormatError(f"{name} is not a Kaiju data file: {e}") from e
    if not isinstance(content, dict) or "kaiju" not in content:
        raise DataFormatError(f"{name} is not a Kaiju data file.")
    if content["kaiju"] != kind:
        raise DataFormatError(f"{name} holds {content['kaiju']!r} data, not {kind!r}.")
    file_format = content.get("format")
    if not isinstance(file_format, int):
        raise DataFormatError(f"{name} has no format number.")
    if file_format > FORMAT:
        raise DataFormatError(f"{name} uses format {file_format}; this Kaiju Suite reads up to {FORMAT}. Update it.")
    if "data" not in content:
        raise DataFormatError(f"{name} has no data.")
    return content["data"]


def is_empty(path):
    """Whether ``path`` is an empty entry, created but not published into yet."""
    return os.path.getsize(path) == 0


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

        Check everything first (see :func:`require_nodes`) and raise before
        changing anything. Runs inside one undo chunk.
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
