"""Space Switch: lets a control follow one of several spaces (world, chest,
head, ...), picked by a ``space`` enum on the control.

Given a control, a group above it and a list of spaces (``label=node``, see
:mod:`kaiju_suite.rig.space_switch`), builds::

    hand_ctrl_grp             ``driven``, or a new hand_ctrl_space_grp
      hand_ctrl_space_parentConstraint   one target per space
      hand_ctrl                gets a keyable ``space`` enum, one entry per space

The constraint keeps its offsets, so building doesn't move the control.
Each target's weight is driven by the enum through a condition node
(``hand_ctrl_<i>_space_cnd``): 1 at that space's index, 0 otherwise.

``driven`` must be above the control (its parent, or higher), and its
translate and rotate must be free to constrain. Leave it blank to insert a
new ``<control>_space_grp`` between the control and its parent, at the
parent's position (the world origin if the control has no parent).
``default_space`` is the label the enum starts at and resets to; blank is
the first space. Switching without a pop is :func:`kaiju_suite.rig.space_switch.switch`
(the Space Switch Tool).
"""

from maya import cmds

from kaiju_suite.rig import helpers
from kaiju_suite.rig import space_switch
from kaiju_suite.rig.module import Param, RigModule


def _long(name):
    return cmds.ls(name, long=True)[0]


def _is_at_or_below(node, ancestor):
    return node == ancestor or node.startswith(ancestor + "|")


class SpaceSwitchModule(RigModule):
    key = "space_switch"
    name = "Space Switch"
    params = (
        Param("control", "Control", "node", "", required=True, tooltip="The control that gets the space enum, e.g. L_hand_ik_ctrl."),
        Param(
            "driven",
            "Driven group",
            "node",
            "",
            tooltip="Group above the control that the spaces move (e.g. its offset group); blank inserts <control>_space_grp above it.",
        ),
        Param(
            "spaces",
            "Spaces",
            "string",
            "world=world_space",
            required=True,
            tooltip="label=node, separated by commas, e.g. world=main_offset_ctrl, chest=chest_ctrl, head=head_ctrl.",
        ),
        Param("default_space", "Default space", "string", "", tooltip="Label of the space the control starts in; blank is the first."),
    )

    def check(self, params):
        control = params["control"].strip()
        driven = params["driven"].strip()
        found = helpers.node_problems("Control", control)
        if driven:
            found.extend(helpers.node_problems("Driven group", driven))

        if not found:
            control_path = _long(control)
            if space_switch.has_spaces(control_path) or cmds.attributeQuery(space_switch.ATTR, node=control_path, exists=True):
                found.append(f"{control} already has a space attribute; it has spaces already.")
            if driven:
                found.extend(self._driven_problems(control_path, _long(driven), driven))
            elif cmds.objExists(f"{helpers.short(control_path)}_space_grp"):
                found.append(f"{helpers.short(control_path)}_space_grp already exists; set Driven group or rename it.")

        space_problems = space_switch.spaces_problems(params["spaces"])
        found.extend(space_problems)
        if not space_problems:
            pairs = space_switch.parse_spaces(params["spaces"])
            for label, node in pairs:
                node_found = helpers.node_problems(f"Space {label!r} node", node)
                found.extend(node_found)
                if node_found or not cmds.ls(control, long=True):
                    continue
                # The constrained group's own subtree can't drive it.
                moved = _long(driven) if driven and cmds.ls(driven) else _long(control)
                if _is_at_or_below(_long(node), moved):
                    found.append(f"Space {label!r} node {node} moves with the control, so it can't be a space for it.")
            default = params["default_space"].strip()
            if default and default not in [label for label, _ in pairs]:
                found.append(f"Default space {default!r} isn't one of the spaces.")
        return found

    @staticmethod
    def _driven_problems(control_path, driven_path, driven):
        if control_path == driven_path or not control_path.startswith(driven_path + "|"):
            return [f"Driven group {driven} must be above the control (its parent or higher)."]
        found = []
        for attr in ("translate", "rotate"):
            plugs = [f"{driven_path}.{attr}{axis}" for axis in ("", "X", "Y", "Z")]
            if any(cmds.getAttr(p, lock=True) or cmds.listConnections(p, source=True, destination=False) for p in plugs):
                found.append(f"Driven group {driven} has locked or connected {attr}; the spaces can't move it.")
        return found

    def create(self, params):
        control = _long(params["control"].strip())
        name = helpers.short(control).replace("|", "_")
        pairs = space_switch.parse_spaces(params["spaces"])
        labels = [label for label, _ in pairs]
        default = params["default_space"].strip()
        default_index = labels.index(default) if default else 0

        with helpers.kept_selection():
            driven = params["driven"].strip()
            if driven:
                driven = helpers.short(driven)
            else:
                parent = cmds.listRelatives(control, parent=True, fullPath=True)
                driven = helpers.group(f"{name}_space_grp", parent[0] if parent else None)
                control = _long(cmds.parent(control, driven)[0])

            # Add the enum first, at the default, so the constraint's offsets
            # are worked out with the default space's weights only.
            space_switch.add_space_attr(control, labels, default_index)
            targets = [node for _, node in pairs]
            constraint = cmds.parentConstraint(*targets, driven, maintainOffset=True, name=f"{name}_space_parentConstraint")[0]
            space_switch.drive_weights(control, constraint, name)

        return {
            "control": helpers.short(control),
            "driven": helpers.short(driven),
            "constraint": helpers.short(constraint),
            "spaces": labels,
        }


MODULE = SpaceSwitchModule()
