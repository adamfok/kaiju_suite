"""Joints (.jnt): a skeleton saved as data and rebuilt as new joints.

:func:`gather` saves the given joints and every joint below them. :func:`apply`
always creates new joints and never changes existing ones: a name that's
taken gets the next free one (``spine_jnt`` → ``spine_jnt1``). A joint whose
parent isn't in the file goes under the scene's node of that name, if there
is one, otherwise under the world.
"""

from maya import cmds

from kaiju_suite.core.selection import short_name
from kaiju_suite.datatypes import create_node, node_path, outside_parents, parent_of

KIND = "joints"
EXTENSION = ".jnt"

_VECTORS = ("translate", "rotate", "jointOrient", "scale", "preferredAngle")
_INTS = ("rotateOrder", "side", "type")


def _joints_under(selection):
    """The selected joints and their descendant joints, parents first, each
    root's joints together, roots in selection order."""
    selected = cmds.ls(selection, type="joint", long=True) or []
    members = set()
    for joint in selected:
        members.add(joint)
        members.update(cmds.listRelatives(joint, allDescendents=True, type="joint", fullPath=True) or [])

    ordered = []

    def walk(joint):
        ordered.append(joint)
        for child in cmds.listRelatives(joint, children=True, type="joint", fullPath=True) or []:
            walk(child)

    for joint in dict.fromkeys(selected):
        if parent_of(joint) not in members:
            walk(joint)
    return ordered


def _record(path, index_of):
    parent = parent_of(path)
    record = {
        "name": short_name(path),
        "parent": short_name(parent) if parent else None,
        "parent_index": index_of.get(parent),
    }
    for attr in _VECTORS:
        record[attr] = list(cmds.getAttr(f"{path}.{attr}")[0])
    for attr in _INTS:
        record[attr] = int(cmds.getAttr(f"{path}.{attr}"))
    record["segmentScaleCompensate"] = bool(cmds.getAttr(f"{path}.segmentScaleCompensate"))
    record["radius"] = float(cmds.getAttr(f"{path}.radius"))
    record["otherType"] = cmds.getAttr(f"{path}.otherType") or ""
    return record


def _set_values(path, record):
    for attr in _VECTORS:
        cmds.setAttr(f"{path}.{attr}", *record[attr])
    for attr in _INTS:
        cmds.setAttr(f"{path}.{attr}", record[attr])
    cmds.setAttr(f"{path}.segmentScaleCompensate", record["segmentScaleCompensate"])
    cmds.setAttr(f"{path}.radius", record["radius"])
    cmds.setAttr(f"{path}.otherType", record["otherType"], type="string")


def selection_problems(selection):
    if not selection:
        return ["Nothing selected. Select the root joints to publish."]
    if not cmds.ls(selection, type="joint"):
        return ["No joints selected. Select the root joints to publish."]
    return []


def gather(nodes):
    paths = _joints_under(nodes)
    if not paths:
        raise RuntimeError("No joints selected to publish.")
    index_of = {}
    records = []
    for path in paths:
        records.append(_record(path, index_of))
        index_of[path] = len(records) - 1
    return {"joints": records}


def apply(payload, info=None):
    records = payload["joints"]
    outside = outside_parents(records)
    uuids, renamed = [], []
    for record in records:
        index = record["parent_index"]
        parent = node_path(uuids[index]) if index is not None else outside.get(record["parent"])
        uuid = create_node("joint", record["name"], parent)
        path = node_path(uuid)
        _set_values(path, record)
        uuids.append(uuid)
        if short_name(path) != record["name"]:
            renamed.append(f"{record['name']} → {short_name(path)}")
    message = f"Created {len(records)} joint{'s' if len(records) != 1 else ''}"
    if renamed:
        message += f" (names taken, renamed: {', '.join(renamed)})"
    return message


def nodes(payload):
    return [r["name"] for r in payload["joints"]]


def describe(payload):
    records = payload["joints"]
    roots = [r["name"] for r in records if r["parent_index"] is None]
    return [f"{len(records)} joint{'s' if len(records) != 1 else ''}", f"Roots: {', '.join(roots)}"]


def compare_view(payload):
    # parent_index shifts whenever joints are added or removed; the parent's name says enough.
    return {**payload, "joints": [{k: v for k, v in r.items() if k != "parent_index"} for r in payload["joints"]]}
