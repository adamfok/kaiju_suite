"""The guide module base class.

A guide module lays out the guides for one part of a rig (a chain, a
hand, a leg...) and builds them, with joints that follow them live. Its
layout is plain data (names and world positions), so it can be saved
(:mod:`.spec`), read back from the scene with :meth:`GuideModule.layout`
and built again with :meth:`GuideModule.build`. No Qt here.

Every guide module builds under one top group, ``<name>_guides_grp``,
tagged with the guide module's key (:data:`TAG`), which is how
:mod:`.spec` finds the guide module of any guide, group or joint.
"""

from maya import cmds

from kaiju_suite.core.selection import short_name
from kaiju_suite.core.undo import undo_chunk

# On a guide module's top group: the key of the guide module that built it.
TAG = "kaijuGuideModule"


class GuideError(ValueError):
    """A layout a guide module can't build."""


def is_point(value):
    """Whether ``value`` is an ``[x, y, z]`` position, as layouts hold them."""
    return (
        isinstance(value, (list, tuple))
        and len(value) == 3
        and all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in value)
    )


def flipped_axis(axis):
    """``axis`` (``"x"``, ``"-y"``...) pointing the other way."""
    return axis[1:] if axis.startswith("-") else f"-{axis}"


def flip_x(point):
    """``point`` mirrored across X (the YZ plane)."""
    # + 0.0 keeps 0 from turning into -0.0.
    return [-point[0] + 0.0, point[1], point[2]]


def tag(group, key):
    """Mark ``group`` as the top group of the guide module keyed ``key``."""
    if not cmds.attributeQuery(TAG, node=group, exists=True):
        cmds.addAttr(group, longName=TAG, dataType="string")
    cmds.setAttr(f"{group}.{TAG}", key, type="string")


def tagged_key(node):
    """The guide module key ``node`` is tagged with, or ``None``."""
    if cmds.objExists(node) and cmds.attributeQuery(TAG, node=node, exists=True):
        return cmds.getAttr(f"{node}.{TAG}") or None
    return None


class GuideModule:
    """Subclass, set ``key`` (saved in guide files; never change it) and
    ``name``, and implement :meth:`default_layout`, :meth:`check`,
    :meth:`create`, :meth:`layout`, :meth:`reset`, :meth:`mirrored` and
    :meth:`delete` (plus :meth:`check_extract` if extracting can fail);
    override :meth:`rebuild` if an earlier build can leave something to
    reuse."""

    key = ""
    name = ""
    mirrorable = True  # Assembler items get a right-click Mirror (see :meth:`mirrored`)

    def problems(self, layout):
        """Why ``layout`` can't be built in the current scene, as messages;
        empty if it can."""
        if not isinstance(layout, dict):
            return [f"The {self.name} layout must be a dictionary."]
        return self.check(layout)

    def build(self, layout):
        """Check ``layout``, then build its guides as one undo step and tag
        their top group. Raises :class:`GuideError` listing the problems
        before changing anything. Returns the top group."""
        problems = self.problems(layout)
        if problems:
            raise GuideError(f"Can't build {self.name}:\n" + "\n".join(f"- {p}" for p in problems))
        with undo_chunk(f"Kaiju {self.name}"):
            group = self.create(layout)
            tag(group, self.key)
        return group

    def rebuild(self, layout):
        """Like :meth:`build`, but reusing what an earlier build of
        ``layout`` left in the scene (e.g. joints after Delete Guides),
        where the guide module has something to reuse. The base class
        hasn't: it builds."""
        return self.build(layout)

    def restore(self, group, layout):
        """Put the guides under ``group`` back as ``layout`` has them, as
        one undo step, and return their top group (a new one if they had to
        be made again). Raises :class:`GuideError`, changing nothing, if
        ``group`` holds guides of another name or ``layout`` can't be put
        back."""
        if not isinstance(layout, dict):
            raise GuideError(f"The {self.name} layout must be a dictionary.")
        current = self.layout(group)["name"]
        if current != layout.get("name"):
            raise GuideError(f"{short_name(group)} holds {current}, not {layout.get('name')}.")
        try:
            with undo_chunk(f"Kaiju {self.name}"):
                group = self.reset(group, layout)
                tag(group, self.key)
        except ValueError as e:
            raise GuideError(f"Can't put back {current}: {e}") from None
        return group

    def extract(self, group):
        """Delete the guides under ``group``, keeping their joints where they
        are, as one undo step. Returns the joints. Raises
        :class:`GuideError`, changing nothing, if they can't be extracted."""
        problems = self.check_extract(group)
        if problems:
            raise GuideError(
                f"Can't extract the joints of {short_name(group)}:\n" + "\n".join(f"- {p}" for p in problems)
            )
        with undo_chunk(f"Kaiju {self.name} to Joints"):
            return self.delete(group)

    def nodes(self, layout):
        """The scene nodes to read the layout back from: the top group."""
        return [f"{layout['name']}_guides_grp"]

    def describe(self, layout):
        """Info lines about ``layout``."""
        return [layout["name"]]

    # -- for subclasses ------------------------------------------------------

    def default_layout(self, name):
        """A layout for new guides named ``name``, for a new Assembler item."""
        raise NotImplementedError

    def check(self, layout):
        """Module-specific problems with ``layout`` (a dict), as messages."""
        return []

    def create(self, layout):
        """Build the guides from a checked ``layout``; return the top group."""
        raise NotImplementedError

    def layout(self, group):
        """The layout of the guides under ``group`` as they are now."""
        raise NotImplementedError

    def reset(self, group, layout):
        """Put the guides under ``group`` back as ``layout`` (same name) has
        them; return the top group. Raises ``ValueError`` before changing
        anything if it can't."""
        raise NotImplementedError

    def mirrored(self, layout):
        """``layout`` for the other side (``L_arm`` -> ``R_arm``)."""
        raise NotImplementedError

    def check_extract(self, group):
        """Why the joints under ``group`` can't be extracted now, as messages."""
        return []

    def delete(self, group):
        """Delete ``group`` and its guides, leaving their joints where they
        are, free of the guides; return the joints."""
        raise NotImplementedError
