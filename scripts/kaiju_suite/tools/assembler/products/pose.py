"""Pose (.pose): attribute values saved from the selection and set back.

Publish saves, for each selected node (any type), the value at the current
frame of every keyable, unlocked, scalar attribute, user-defined ones
included, even if the attribute is animated or connected. Nodes are saved
by their shortest unique name.

Run sets the values on the scene's nodes of those names with ``setAttr``.
It creates no keys and leaves existing keys alone (on a keyed attribute it
only changes the current value). Nodes missing from the scene, and
attributes that are now missing, locked or driven by a connection, are
skipped with a warning.
"""

from maya import cmds

from kaiju_suite.tools.assembler import data, runlog


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


class PoseProduct(data.DataProduct):
    name = "Pose"
    utility = "Pose Tool"
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
        missing = data.skip_missing(record["name"] for record in records)
        records = [record for record in records if record["name"] not in missing]
        data.require_unique([record["name"] for record in records])

        set_count, skipped = 0, []
        for record in records:
            node = record["name"]
            node_count = 0
            for attr, value in record["attrs"].items():
                reason = _skip_reason(node, attr)
                if reason:
                    skipped.append(f"{node}.{attr} ({reason})")
                    continue
                cmds.setAttr(f"{node}.{attr}", value)
                node_count += 1
            runlog.info(f"{node}: set {data.plural(node_count, 'attribute')}")
            set_count += node_count

        message = f"Set {data.plural(set_count, 'attribute')} on {data.plural(len(records), 'node')}"
        if skipped:
            skipped = f"Skipped {data.plural(len(skipped), 'attribute')}: {', '.join(skipped)}"
            runlog.warning(skipped)
            message += f". {skipped}"
        return message

    def describe(self, payload):
        records = payload["nodes"]
        count = sum(len(record["attrs"]) for record in records)
        return [
            data.plural(len(records), "node"),
            data.plural(count, "attribute"),
            f"Nodes: {', '.join(record['name'] for record in records)}",
        ]


PRODUCT = PoseProduct()
