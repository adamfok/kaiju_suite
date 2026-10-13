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

from kaiju_suite.core.undo import undo_chunk

# On a guide module's top group: the key of the guide module that built it.
TAG = "kaijuGuideModule"


class GuideError(ValueError):
    """A layout a guide module can't build."""


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
    :meth:`create`, :meth:`layout` and :meth:`mirrored`."""

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

    def mirrored(self, layout):
        """``layout`` for the other side (``L_arm`` -> ``R_arm``)."""
        raise NotImplementedError
