"""Connections (.conn): utility node networks and direct connections, saved as JSON.

Publish takes the selected nodes. Selected DAG nodes (controls, joints,
...) are scene nodes: they aren't saved, only their connections, and Run
finds them by name. Selected utility nodes (multiplyDivide,
plusMinusAverage, condition, blendColors, remapValue, multMatrix, ... any
non-DAG node that isn't a deformer, anim curve, set or other node another
item type covers) are saved, and so is every utility node on a path between
selected nodes, so selecting the two ends of a network is enough. For each
utility node the file holds its type and the values that aren't the default
(connected inputs aren't saved; multi elements, such as
``input1D[1]``, always are). Then every connection between the saved and
selected nodes, as ``[source plug, destination plug]`` by node name.

Unit conversions aren't saved: a connection through one is saved as a
direct connection, and Maya inserts the conversion again on Run.

The file is explicit JSON rather than mayaAscii (as Material uses), so a
change shows as a readable diff.

Run checks first, and changes nothing if a scene node's name matches several
nodes, or a utility node's name is taken by a node of another type. Scene
nodes that are missing are skipped with one warning, and so are
connections to attributes they don't have. It then replaces each utility
node that already exists under the same name and type (its connections go
with it), creates the rest, sets their values and makes the connections.
"""

import os

from maya import cmds
import maya.api.OpenMaya as om

from kaiju_suite.tools.assembler import data, runlog

# Non-DAG node types (and the types derived from them) that aren't utility
# nodes: other item types cover them, or they're Maya's bookkeeping.
_NOT_UTILITY = {
    "abstractBaseCreate",
    "animCurve",
    "animLayer",
    "character",
    "dagPose",
    "displayLayer",
    "geometryFilter",
    "groupId",
    "groupParts",
    "hyperGraphInfo",
    "hyperLayout",
    "lambert",
    "materialInfo",
    "nodeGraphEditorInfo",
    "objectSet",
    "polyBase",
    "reference",
    "renderLayer",
    "script",
    "time",
    "unitConversion",
}
_SCALARS = {"bool", "long", "short", "byte", "char", "enum", "float", "double", "doubleLinear", "doubleAngle", "time"}
_IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
_DIGITS = 6


# -- publish ----------------------------------------------------------------


def _is_dag(node):
    return bool(cmds.ls(node, dag=True))


def _is_utility(node):
    if _is_dag(node) or node in cmds.ls(defaultNodes=True):
        return False
    return not _NOT_UTILITY.intersection(cmds.nodeType(node, inherited=True) or [])


def _name(node):
    """``node``'s shortest unique name, as saved in the file."""
    return cmds.ls(node)[0]


def _reach(starts, upstream):
    """Utility nodes reachable from ``starts`` through utility nodes only,
    following connections upstream or downstream."""
    found, queue = set(), list(starts)
    while queue:
        node = queue.pop()
        neighbours = cmds.listConnections(node, source=upstream, destination=not upstream, skipConversionNodes=True)
        for other in cmds.ls(neighbours or [], long=True):
            if other not in found and _is_utility(other):
                found.add(other)
                queue.append(other)
    return found


def _split_selection(selection):
    """``(scene nodes, utility nodes, others)`` from a selection, long names."""
    scene, utility, others = [], [], []
    for node in cmds.ls(selection, objectsOnly=True, long=True) or []:
        if _is_dag(node):
            scene.append(node)
        elif _is_utility(node):
            utility.append(node)
        else:
            others.append(node)
    return list(dict.fromkeys(scene)), list(dict.fromkeys(utility)), list(dict.fromkeys(others))


def _network(selection):
    """``(scene nodes, utility nodes)`` to publish from ``selection``: the
    selected utility nodes plus those on a path between selected nodes."""
    scene, utility, _others = _split_selection(selection)
    starts = scene + utility
    between = _reach(starts, upstream=False) & _reach(starts, upstream=True)
    return scene, sorted(set(utility) | between, key=_name)


def _indexed(node, plug):
    """``plug``'s attribute, with the ``[0]`` listConnections leaves off a
    source array such as ``worldMatrix``."""
    attr = plug.split(".", 1)[1]
    if "." not in attr and "[" not in attr and cmds.attributeQuery(attr, node=node, multi=True):
        attr += "[0]"
    return attr


def _connections(members):
    """Every connection between ``members``, as sorted ``[source, destination]`` plugs."""
    members = set(members)
    found = set()
    for node in members:
        pairs = cmds.listConnections(node, source=True, destination=False, plugs=True, connections=True,
                                     skipConversionNodes=True) or []
        for dest, source in zip(pairs[::2], pairs[1::2]):
            owner = cmds.ls(source, objectsOnly=True, long=True)[0]
            if owner in members:
                found.add((f"{_name(owner)}.{_indexed(owner, source)}", f"{_name(node)}.{dest.split('.', 1)[1]}"))
    return [list(pair) for pair in sorted(found)]


def _plug(name):
    return om.MSelectionList().add(name).getPlug(0)


def _leaf(attr):
    """``input3D[1].input3Dx`` → ``input3Dx``: the name attributeQuery takes."""
    return attr.rsplit(".", 1)[-1].split("[", 1)[0]


def _round(value):
    return round(value, _DIGITS) if isinstance(value, float) else value


def _values(node):
    """``{attribute: value}`` for ``node``'s stored values that aren't the
    default and aren't connected inputs. Multi elements are always kept."""
    found = {}
    for attr in cmds.listAttr(node, multi=True, settable=True) or []:
        plug = f"{node}.{attr}"
        try:
            kind = cmds.getAttr(plug, type=True)
            if kind not in _SCALARS and kind not in ("string", "matrix"):
                continue
            if not om.MFnAttribute(_plug(plug).attribute()).storable:
                continue
            if cmds.connectionInfo(plug, isDestination=True):
                continue
            value = cmds.getAttr(plug)
        except (RuntimeError, ValueError):
            continue
        is_element = "[" in attr
        if kind == "matrix":
            value = [_round(float(v)) for v in value]
            if is_element or value != _IDENTITY:
                found[attr] = value
        elif kind == "string":
            if value:
                found[attr] = value
        else:
            value = _round(value)
            default = cmds.attributeQuery(_leaf(attr), node=node, listDefault=True) or [None]
            if is_element or default[0] is None or abs(float(value) - float(default[0])) > 10 ** -_DIGITS:
                found[attr] = value
    return dict(sorted(found.items()))


def _plugin(node):
    """The plug-in that defines ``node``'s type, or ``""`` for Maya's own."""
    path = om.MFnDependencyNode(om.MSelectionList().add(node).getDependNode(0)).pluginName
    return os.path.splitext(os.path.basename(path))[0] if path else ""


def _record(node):
    record = {"name": _name(node), "type": cmds.nodeType(node), "attrs": _values(node)}
    plugin = _plugin(node)
    if plugin:
        record["plugin"] = plugin
    return record


def _nothing_to_publish():
    return "No connections between the selected nodes. Select the nodes to link and any utility nodes between them."


# -- run --------------------------------------------------------------------


def _node_of(plug):
    return plug.split(".", 1)[0]


def _has_attr(plug):
    node, attr = plug.split(".", 1)
    return cmds.attributeQuery(_leaf(attr), node=node, exists=True)


def _load_plugins(records):
    known = set(cmds.ls(nodeTypes=True))
    unknown = []
    for record in records:
        if record["type"] in known:
            continue
        plugin = record.get("plugin")
        if plugin:
            try:
                cmds.loadPlugin(plugin, quiet=True)
            except RuntimeError:
                pass
            known = set(cmds.ls(nodeTypes=True))
        if record["type"] not in known:
            unknown.append(f"{record['type']} ({plugin})" if plugin else record["type"])
    if unknown:
        raise RuntimeError(f"Unknown node types, load their plug-ins first: {', '.join(dict.fromkeys(unknown))}")


def _check_names(records):
    """Raise, before anything changes, if a utility node's name matches
    several nodes or a node of another type."""
    problems = []
    for record in records:
        matches = cmds.ls(record["name"], long=True)
        if len(matches) > 1:
            problems.append(f"{record['name']} matches several nodes ({', '.join(matches)})")
        elif matches and cmds.nodeType(matches[0]) != record["type"]:
            problems.append(f"{record['name']} is taken by a {cmds.nodeType(matches[0])}, not a {record['type']}")
    if problems:
        raise RuntimeError(f"Can't apply Connections: {'; '.join(problems)}")


def _set_value(plug, value):
    if isinstance(value, str):
        cmds.setAttr(plug, value, type="string")
    elif isinstance(value, list):
        cmds.setAttr(plug, *value, type="matrix")
    else:
        cmds.setAttr(plug, value)


def _create(record):
    """Replace or create the utility node ``record`` describes and set its
    values. Returns the node's name in the scene."""
    if cmds.objExists(record["name"]):
        cmds.delete(record["name"])
    node = data.node_path(data.create_node(record["type"], record["name"]))
    failed = []
    for attr, value in record["attrs"].items():
        try:
            _set_value(f"{node}.{attr}", value)
        except RuntimeError:
            failed.append(attr)
    if failed:
        runlog.warning(f"{node}: couldn't set {', '.join(failed)}")
    return node


class ConnectionsProduct(data.DataProduct):
    name = "Connections"
    kind = "connections"
    extension = ".conn"
    order = 150
    menu_slot = (6, 2)

    def selection_problems(self):
        selection = cmds.ls(selection=True)
        if not selection:
            return ["Nothing selected. Select the nodes whose connections to publish."]
        _scene, _utility, others = _split_selection(selection)
        if others:
            return [f"Not utility nodes, so not saved here: {', '.join(cmds.ls(others))}"]
        scene, utility = _network(selection)
        if not utility and not _connections(scene):
            return [_nothing_to_publish()]
        return []

    def gather(self, selection):
        scene, utility = _network(selection)
        links = _connections(scene + utility)
        if not utility and not links:
            raise RuntimeError(_nothing_to_publish())
        return {"nodes": [_record(n) for n in utility], "connections": links}

    def apply(self, payload):
        records = payload["nodes"]
        own = {r["name"] for r in records}
        ends = sorted({_node_of(p) for link in payload["connections"] for p in link} - own)

        missing = data.skip_missing(ends, "nodes")
        data.require_unique([e for e in ends if e not in missing])
        _load_plugins(records)
        _check_names(records)

        links, no_attr = [], []
        for source, dest in payload["connections"]:
            if _node_of(source) in missing or _node_of(dest) in missing:
                continue
            ends_ok = all(_has_attr(p) for p in (source, dest) if _node_of(p) not in own)
            (links if ends_ok else no_attr).append((source, dest))
        if no_attr:
            runlog.warning(f"Skipped connections to missing attributes: {'; '.join(f'{s} -> {d}' for s, d in no_attr)}")

        names = {r["name"]: _create(r) for r in records}

        def scene_plug(plug):
            node, attr = plug.split(".", 1)
            return f"{names.get(node, node)}.{attr}"

        made, failed = 0, []
        for source, dest in links:
            source, dest = scene_plug(source), scene_plug(dest)
            try:
                if not cmds.isConnected(source, dest):
                    cmds.connectAttr(source, dest, force=True)
                made += 1
            except RuntimeError as e:
                failed.append(f"{source} -> {dest} ({str(e).strip()})")
        if failed:
            runlog.warning(f"Couldn't connect: {'; '.join(failed)}")
        if records:
            runlog.info(f"Created {', '.join(names.values())}")

        return (f"Created {data.plural(len(records), 'utility node')} "
                f"and made {data.plural(made, 'connection')}")

    def describe(self, payload):
        names = sorted(r["name"] for r in payload["nodes"])
        own = set(names)
        ends = sorted({_node_of(p) for link in payload["connections"] for p in link} - own)
        lines = [
            f"{data.plural(len(names), 'utility node')}: {', '.join(names)}" if names else "0 utility nodes",
            data.plural(len(payload["connections"]), "connection"),
        ]
        if ends:
            lines.append(f"Scene nodes: {', '.join(ends)}")
        return lines


PRODUCT = ConnectionsProduct()
