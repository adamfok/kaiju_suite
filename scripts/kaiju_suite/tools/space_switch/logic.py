"""Space Switch Tool: switch the space of controls built by the Space Switch
rig module without them jumping. No Qt here.

The switch math is :func:`kaiju_suite.rig.space_switch.switch`, shared with
the rig module; this adds working on several controls as one undo step.
"""

from collections import namedtuple

from kaiju_suite.core.undo import undoable
from kaiju_suite.rig import space_switch

Result = namedtuple("Result", "changed skipped")


def space_controls(nodes):
    """The nodes among ``nodes`` that have a ``space`` enum, in order."""
    return [node for node in nodes if space_switch.has_spaces(node)]


def common_spaces(nodes):
    """Space labels every space control among ``nodes`` has, in the first
    one's order; empty if none has spaces."""
    controls = space_controls(nodes)
    if not controls:
        return []
    shared = set.intersection(*(set(space_switch.spaces(c)) for c in controls))
    return [label for label in space_switch.spaces(controls[0]) if label in shared]


def current_space(node):
    """The label of ``node``'s current space."""
    return space_switch.current(node)


@undoable
def switch(nodes, space, key=False):
    """Switch each of ``nodes`` to ``space`` (a label) keeping it in place in
    the world; with ``key``, key the frame before and the current frame.
    Nodes without that space are skipped."""
    changed, skipped = [], []
    for node in nodes:
        if space in space_switch.spaces(node):
            space_switch.switch(node, space, key=key)
            changed.append(node)
        else:
            skipped.append(node)
    return Result(changed, skipped)
