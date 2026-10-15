"""Pose (.pose): attribute values saved from the selection and set back.

:func:`gather` saves, for each given node (any type), the value at the
current frame of every keyable, unlocked, scalar attribute, user-defined
ones included, even if the attribute is animated or connected. Nodes are
saved by their shortest unique name.

:func:`apply` sets the values on the scene's nodes of those names with
``setAttr``. It creates no keys and leaves existing keys alone (on a keyed
attribute it only changes the current value). Nodes missing from the
scene, and attributes that are now missing, locked or driven by a
connection, are skipped with a warning.

:data:`CHECKS` are QC checks on given nodes (driven attributes, nothing to
save, duplicate names), run by the Pose Tool's QC tab and before Scripter
publishes. They change nothing.
"""

from maya import cmds

from kaiju_suite.core.checks import Check, Problem
from kaiju_suite.core.selection import short_name
from kaiju_suite.datatypes import plural, report, require_unique, short, skip_missing, warning

KIND = "pose"
EXTENSION = ".pose"

_NOTHING_TO_SAVE = "The selected nodes have no keyable attributes to save."


def pose_attributes(node):
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


def is_driven(plug):
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
    if is_driven(plug):
        return "connected"
    return None


def selection_problems(selection):
    if not selection:
        return ["Nothing selected. Select the nodes whose pose to publish."]
    if not any(pose_attributes(node) for node in selection):
        return [_NOTHING_TO_SAVE]
    return []


def gather(nodes):
    records = []
    for path in dict.fromkeys(nodes):
        attrs = pose_attributes(path)
        if attrs:
            records.append({"name": short(path), "attrs": attrs})
    if not records:
        raise RuntimeError(_NOTHING_TO_SAVE)
    return {"nodes": records}


def apply(payload, info=None):
    records = payload["nodes"]
    missing = skip_missing(record["name"] for record in records)
    records = [record for record in records if record["name"] not in missing]
    require_unique([record["name"] for record in records])

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
        report(info, f"{node}: set {plural(node_count, 'attribute')}")
        set_count += node_count

    message = f"Set {plural(set_count, 'attribute')} on {plural(len(records), 'node')}"
    if skipped:
        skipped = f"Skipped {plural(len(skipped), 'attribute')}: {', '.join(skipped)}"
        warning(skipped)
        message += f". {skipped}"
    return message


def nodes(payload):
    return [record["name"] for record in payload["nodes"]]


def describe(payload):
    records = payload["nodes"]
    count = sum(len(record["attrs"]) for record in records)
    return [
        plural(len(records), "node"),
        plural(count, "attribute"),
        f"Nodes: {', '.join(record['name'] for record in records)}",
    ]


def compare_view(payload):
    # Already one record per node with its values by attribute: shown as saved.
    return payload


# -- QC checks --------------------------------------------------------------


def _checked(nodes):
    """The nodes among ``nodes`` (components stand for their node), long names, each once."""
    return list(dict.fromkeys(cmds.ls(nodes, objectsOnly=True, long=True) or [])) if nodes else []


def _check_driven(nodes):
    problems = []
    for node in _checked(nodes):
        driven = [attr for attr in pose_attributes(node) if is_driven(f"{node}.{attr}")]
        if driven:
            problems.append(
                Problem(
                    f"{short(node)}: {plural(len(driven), 'driven attribute')} (Run will skip them): {', '.join(driven)}",
                    [short(node)],
                )
            )
    return problems


def _check_nothing_to_save(nodes):
    return [
        Problem(f"{short(node)}: no keyable, unlocked attributes", [short(node)])
        for node in _checked(nodes)
        if not pose_attributes(node)
    ]


def _check_duplicate_names(nodes):
    problems = []
    for node in _checked(nodes):
        name = short_name(node)
        same = sorted(cmds.ls(name) or [])
        if len(same) > 1:
            problems.append(Problem(f"{short(node)}: {len(same)} nodes are called {name}", same))
    return problems


CHECKS = (
    Check(
        "driven",
        "Driven attributes",
        "Keyable attributes driven by a connection (not their own time keys); Run skips them.",
        _check_driven,
    ),
    Check(
        "nothing_to_save",
        "Nothing to save",
        "Nodes with no keyable, unlocked attributes; a pose leaves them out.",
        _check_nothing_to_save,
    ),
    Check(
        "duplicate_names",
        "Duplicate names",
        "Nodes whose name another node also has; Run finds nodes by name.",
        _check_duplicate_names,
    ),
)
