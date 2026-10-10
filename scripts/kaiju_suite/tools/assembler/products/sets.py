"""Sets & Layers (.sets): object sets and display layers, saved by name.

Publish saves the selected object sets (animator control sets, export sets,
...) with every set nested in them, and the selected display layers. Select
them in the Outliner, or with ``select -noExpand``. For each set it saves
its members; for each layer its members, display type (normal, template,
reference), visibility, hide on playback and color. Members are saved by
their shortest unique name. Only plain ``objectSet`` nodes count as sets:
shading groups, deformer sets and other set types are left out.

Run creates each set and layer that isn't in the scene and reuses one of the
same name and type that is, then adds the saved members found by name (it
doesn't remove other members) and sets the layer's display settings.
Members missing from the scene are skipped with one warning. A member name
that matches several nodes, or a set or layer name used by a node of
another type, stops the Run before it changes anything.
"""

from maya import cmds

from kaiju_suite.tools.assembler import data, runlog

_LAYER_ATTRS = {"displayType": int, "visibility": bool, "hideOnPlayback": bool, "color": int}


def _is_set(node):
    return cmds.nodeType(node) == "objectSet"


def _is_layer(node):
    return cmds.nodeType(node) == "displayLayer" and node != "defaultLayer"


def _names(nodes):
    """Shortest unique names of ``nodes`` (components kept as they are), sorted."""
    return sorted(cmds.ls(nodes or []))


def _set_members(node):
    return _names(cmds.sets(node, query=True))


def _layer_members(layer):
    return _names(cmds.editDisplayLayerMembers(layer, query=True, fullNames=True))


def _picked(selection):
    """The selected sets and display layers, as ``(sets, layers)``."""
    nodes = list(dict.fromkeys(cmds.ls(selection) or []))
    return [n for n in nodes if _is_set(n)], [n for n in nodes if _is_layer(n)]


def _with_nested(selected):
    """``selected`` and every object set nested in them, parents first."""
    ordered = []

    def walk(node):
        if node in ordered:
            return
        ordered.append(node)
        for member in _set_members(node):
            if cmds.objExists(member) and _is_set(member):
                walk(member)

    for node in selected:
        walk(node)
    return ordered


def _owner_problems(records, node_type):
    """Names in ``records`` that a node of another type already uses."""
    return [
        f"{r['name']} (a {cmds.nodeType(r['name'])})"
        for r in records
        if cmds.objExists(r["name"]) and cmds.nodeType(r["name"]) != node_type
    ]


def _counts(set_count, layer_count):
    parts = []
    if set_count:
        parts.append(data.plural(set_count, "set"))
    if layer_count:
        parts.append(data.plural(layer_count, "display layer"))
    return " and ".join(parts)


class SetsProduct(data.DataProduct):
    name = "Sets & Layers"
    kind = "sets"
    extension = ".sets"
    order = 118
    menu_slot = (4, 6)

    def selection_problems(self):
        selection = cmds.ls(selection=True)
        if not selection:
            return ["Nothing selected. Select the object sets and display layers to publish."]
        if not any(_picked(selection)):
            return [
                "No sets or display layers selected. Select the object sets and display layers to publish "
                "(in the Outliner), not their members."
            ]
        return []

    def gather(self, selection):
        selected_sets, layers = _picked(selection)
        if not selected_sets and not layers:
            raise RuntimeError("No sets or display layers selected to publish.")
        set_records = [{"name": node, "members": _set_members(node)} for node in _with_nested(selected_sets)]
        layer_records = []
        for layer in layers:
            record = {"name": layer, "members": _layer_members(layer)}
            for attr, kind in _LAYER_ATTRS.items():
                record[attr] = kind(cmds.getAttr(f"{layer}.{attr}"))
            layer_records.append(record)
        return {"sets": set_records, "layers": layer_records}

    def apply(self, payload):
        set_records, layer_records = payload["sets"], payload["layers"]
        set_names = {r["name"] for r in set_records}

        # Check everything before changing anything.
        taken = _owner_problems(set_records, "objectSet") + _owner_problems(layer_records, "displayLayer")
        if taken:
            raise RuntimeError(f"Names already used by other node types: {'; '.join(taken)}")
        wanted = [m for r in set_records + layer_records for m in r["members"] if m not in set_names]
        missing = data.skip_missing(wanted, "members")
        data.require_unique([m for m in dict.fromkeys(wanted) if m not in missing])

        def found(members):
            return [m for m in members if m not in missing]

        created, updated = [0, 0], [0, 0]
        for record in set_records:
            exists = cmds.objExists(record["name"])
            if not exists:
                cmds.sets(name=record["name"], empty=True)
            (updated if exists else created)[0] += 1
        for record in set_records:
            members = found(record["members"])
            if members:
                cmds.sets(members, add=record["name"])
            runlog.info(f"{record['name']}: {data.plural(len(members), 'member')}")

        for record in layer_records:
            layer = record["name"]
            exists = cmds.objExists(layer)
            if not exists:
                cmds.createDisplayLayer(name=layer, empty=True, noRecurse=True, makeCurrent=False)
            (updated if exists else created)[1] += 1
            members = found(record["members"])
            if members:
                cmds.editDisplayLayerMembers(layer, members, noRecurse=True)
            for attr in _LAYER_ATTRS:
                cmds.setAttr(f"{layer}.{attr}", record[attr])
            runlog.info(f"{layer}: {data.plural(len(members), 'member')}")

        parts = []
        if any(created):
            parts.append(f"Created {_counts(*created)}")
        if any(updated):
            parts.append(f"{'Updated' if not parts else 'updated'} {_counts(*updated)}")
        return "; ".join(parts) or "Nothing to apply"

    def describe(self, payload):
        set_records, layer_records = payload["sets"], payload["layers"]
        lines = [data.plural(len(set_records), "set"), data.plural(len(layer_records), "display layer")]
        if set_records:
            lines.append(f"Sets: {', '.join(r['name'] for r in set_records)}")
        if layer_records:
            lines.append(f"Display layers: {', '.join(r['name'] for r in layer_records)}")
        return lines


PRODUCT = SetsProduct()
