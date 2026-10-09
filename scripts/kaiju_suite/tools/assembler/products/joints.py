"""Joints (.jnt): a skeleton saved as data and rebuilt as new joints.

Publish saves the selected joints and every joint below them. Run always
creates new joints and never changes existing ones: a name that's taken gets
the next free one (``spine_jnt`` → ``spine_jnt1``). A joint whose parent
isn't in the file goes under the scene's node of that name, if there is one,
otherwise under the world.
"""

from maya import cmds

from kaiju_suite.core.selection import short_name
from kaiju_suite.tools.assembler import data

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
        if data.parent_of(joint) not in members:
            walk(joint)
    return ordered


def _record(path, index_of):
    parent = data.parent_of(path)
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


class JointsProduct(data.DataProduct):
    name = "Joints"
    utility = "Joint Tool"
    kind = "joints"
    extension = ".jnt"
    order = 40

    def selection_problems(self):
        selection = cmds.ls(selection=True)
        if not selection:
            return ["Nothing selected. Select the root joints to publish."]
        if not cmds.ls(selection, type="joint"):
            return ["No joints selected. Select the root joints to publish."]
        return []

    def gather(self, selection):
        paths = _joints_under(selection)
        if not paths:
            raise RuntimeError("No joints selected to publish.")
        index_of = {}
        records = []
        for path in paths:
            records.append(_record(path, index_of))
            index_of[path] = len(records) - 1
        return {"joints": records}

    def apply(self, payload):
        records = payload["joints"]
        outside = data.outside_parents(records)
        uuids, renamed = [], []
        for record in records:
            index = record["parent_index"]
            parent = data.node_path(uuids[index]) if index is not None else outside.get(record["parent"])
            uuid = data.create_node("joint", record["name"], parent)
            path = data.node_path(uuid)
            _set_values(path, record)
            uuids.append(uuid)
            if short_name(path) != record["name"]:
                renamed.append(f"{record['name']} → {short_name(path)}")
        message = f"Created {len(records)} joint{'s' if len(records) != 1 else ''}"
        if renamed:
            message += f" (names taken, renamed: {', '.join(renamed)})"
        return message

    def describe(self, payload):
        records = payload["joints"]
        roots = [r["name"] for r in records if r["parent_index"] is None]
        return [f"{len(records)} joint{'s' if len(records) != 1 else ''}", f"Roots: {', '.join(roots)}"]


PRODUCT = JointsProduct()
