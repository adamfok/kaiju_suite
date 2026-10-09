"""Pose (.pose): attribute values saved from the selection and set back.

Publish saves, for each selected node (any type), the value at the current
frame of every keyable, unlocked, scalar attribute, user-defined ones
included, even if the attribute is animated or connected. Nodes are saved
by their shortest unique name.

Run sets the values on the scene's nodes of those names with ``setAttr``.
It creates no keys and leaves existing keys alone (on a keyed attribute it
only changes the current value). Attributes that are now missing, locked or
driven by a connection are skipped and listed in the returned message.
"""

from maya import cmds

from kaiju_suite.tools.assembler import data


def _plural(count, word):
    return f"{count} {word}{'s' if count != 1 else ''}"


def _short_name(path):
    """The shortest name that still picks out only this node."""
    return cmds.ls(path)[0]


def _pose_attributes(node):
    """``{attr: value}`` of the node's keyable, unlocked, scalar attributes.

    Leaves out multi attributes and children of multis (``listAttr`` lists
    those as ``parent.child`` with no index), so every saved name can be set
    as ``node.attr``.
    """
    values = {}
    for attr in cmds.listAttr(node, keyable=True, unlocked=True, scalar=True) or []:
        if "." in attr or cmds.attributeQuery(attr, node=node, multi=True):
            continue
        value = cmds.getAttr(f"{node}.{attr}")
        if isinstance(value, (bool, int, float)):
            values[attr] = value
    return values


def _is_driven(plug):
    """Whether ``plug`` gets its value from a connection other than its own
    time keys (setting a keyed attribute only changes its current value)."""
    sources = cmds.listConnections(plug, source=True, destination=False, skipConversionNodes=True) or []
    return any(not cmds.nodeType(source).startswith("animCurveT") for source in sources)


def _skip_reason(node, attr):
    if not cmds.attributeQuery(attr, node=node, exists=True):
        return "missing"
    plug = f"{node}.{attr}"
    if cmds.getAttr(plug, lock=True):
        return "locked"
    if _is_driven(plug):
        return "connected"
    return None


def _require_unique(names):
    ambiguous = [f"{name} ({', '.join(cmds.ls(name, long=True))})" for name in names if len(cmds.ls(name)) > 1]
    if ambiguous:
        raise RuntimeError(f"Several nodes have the same name, can't tell which to use: {'; '.join(ambiguous)}")


class PoseProduct(data.DataProduct):
    name = "Pose"
    kind = "pose"
    extension = ".pose"
    order = 100

    def selection_problems(self):
        selection = cmds.ls(selection=True, long=True)
        if not selection:
            return ["Nothing selected. Select the nodes whose pose to publish."]
        if not any(_pose_attributes(node) for node in selection):
            return ["The selected nodes have no keyable attributes to save."]
        return []

    def gather(self, selection):
        records = []
        for path in dict.fromkeys(selection):
            attrs = _pose_attributes(path)
            if attrs:
                records.append({"name": _short_name(path), "attrs": attrs})
        if not records:
            raise RuntimeError("The selected nodes have no keyable attributes to save.")
        return {"nodes": records}

    def apply(self, payload):
        records = payload["nodes"]
        names = [record["name"] for record in records]
        data.require_nodes(names)
        _require_unique(names)

        set_count, skipped = 0, []
        for record in records:
            node = record["name"]
            for attr, value in record["attrs"].items():
                reason = _skip_reason(node, attr)
                if reason:
                    skipped.append(f"{node}.{attr} ({reason})")
                    continue
                cmds.setAttr(f"{node}.{attr}", value)
                set_count += 1

        message = f"Set {_plural(set_count, 'attribute')} on {_plural(len(records), 'node')}"
        if skipped:
            message += f". Skipped {_plural(len(skipped), 'attribute')}: {', '.join(skipped)}"
        return message

    def describe(self, payload):
        records = payload["nodes"]
        count = sum(len(record["attrs"]) for record in records)
        return [
            _plural(len(records), "node"),
            _plural(count, "attribute"),
            f"Nodes: {', '.join(record['name'] for record in records)}",
        ]


PRODUCT = PoseProduct()
