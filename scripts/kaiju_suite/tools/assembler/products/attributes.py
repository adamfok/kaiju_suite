"""Attributes (.attr): custom attributes and channel lock/hide state, applied by node name.

Publish saves, for each selected node, its custom attributes (type, min/max,
default, enum names, keyable, channel box, locked) and the lock/hide state of
its translate, rotate, scale and visibility channels. Run finds the nodes by
name, adds the attributes they're missing, updates the ones they have (values
are left alone) and applies the lock/hide state. Missing nodes are skipped
with a warning. The read/write logic lives in :mod:`kaiju_suite.core.attributes`.
"""

from maya import cmds

from kaiju_suite.core import attributes
from kaiju_suite.core.selection import short_name
from kaiju_suite.tools.assembler import data, runlog


def _check(records):
    """Raise, before anything changes, if a node's name matches several
    nodes or an attribute can't be applied (e.g. a different type)."""
    data.require_unique([r["name"] for r in records])
    problems = []
    for record in records:
        for attr in record["attributes"]:
            problems.extend(attributes.attribute_problems(record["name"], attr))
    if problems:
        raise RuntimeError(f"Can't apply Attributes: {'; '.join(problems)}")


class AttributesProduct(data.DataProduct):
    name = "Attributes"
    utility = "Attribute Manager"
    kind = "attributes"
    extension = ".attr"
    order = 117
    menu_slot = (4, 5)

    def selection_problems(self):
        if not cmds.ls(selection=True):
            return ["Nothing selected. Select the nodes whose attributes to publish."]
        return []

    def gather(self, selection):
        nodes = list(dict.fromkeys(cmds.ls(selection, objectsOnly=True, long=True) or []))
        if not nodes:
            raise RuntimeError("Nothing selected to publish.")
        return {"nodes": [{"name": short_name(n), **attributes.read_node(n)} for n in nodes]}

    def apply(self, payload):
        records = payload["nodes"]
        missing = data.skip_missing([r["name"] for r in records], "nodes")
        records = [r for r in records if r["name"] not in missing]
        _check(records)
        for record in records:
            node = record["name"]
            done = {"added": [], "updated": []}
            for attr in record["attributes"]:
                done[attributes.apply_attribute(node, attr)].append(attr["name"])
            attributes.apply_channels(node, record["channels"])
            parts = [f"{k} {', '.join(v)}" for k, v in done.items() if v]
            runlog.info(f"{node}: {'; '.join(parts + ['channels set'])}")
        if not records:
            return "Applied attributes to no nodes"
        return f"Applied attributes to {', '.join(r['name'] for r in records)}"

    def describe(self, payload):
        records = payload["nodes"]
        count = sum(len(r["attributes"]) for r in records)
        return [
            f"{data.plural(len(records), 'node')}, {data.plural(count, 'custom attribute')}",
            f"Nodes: {', '.join(r['name'] for r in records)}",
        ]


PRODUCT = AttributesProduct()
