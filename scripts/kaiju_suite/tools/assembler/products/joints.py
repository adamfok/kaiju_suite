"""Joints (.jnt): a skeleton saved as data and rebuilt as new joints.

Publish saves the selected joints and every joint below them. Run always
creates new joints and never changes existing ones: a name that's taken gets
the next free one (``spine_jnt`` → ``spine_jnt1``). A joint whose parent
isn't in the file goes under the scene's node of that name, if there is one,
otherwise under the world.

Other rigs find these joints by name, so Publish warns (and asks whether to
publish anyway) when the latest published version has joints this publish
removes, renames or moves to another parent. Added joints don't warn.
"""

from maya import cmds

from kaiju_suite.core.selection import short_name
from kaiju_suite.tools.assembler import data, versions
from kaiju_suite.tools.assembler.products import Line

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


def _contract_changes(old, new):
    """``(removed, renamed, moved)`` going from records ``old`` to ``new``:
    what breaks rigs that find these joints by name. ``renamed`` pairs a
    removed joint with an added one under the same parent at the same place;
    ``moved`` is ``(name, old parent, new parent)``, a renamed parent not
    counting as a move. Added joints aren't changes."""
    new_by = {r["name"]: r for r in new}
    old_names = {r["name"] for r in old}
    gone = [r for r in old if r["name"] not in new_by]
    added = [r for r in new if r["name"] not in old_names]

    renamed = {}

    def place(record, old_side=False):
        parent = renamed.get(record["parent"], record["parent"]) if old_side else record["parent"]
        return parent, tuple(round(v, 4) for v in record["translate"])

    # A gone joint and an added one match when exactly one of each sits there.
    # Records are parents first, so a parent's new name is known before its children.
    for record in gone:
        here = place(record, old_side=True)
        matches = [a for a in added if place(a) == here]
        if len(matches) == 1 and sum(place(g, old_side=True) == here for g in gone) == 1:
            renamed[record["name"]] = matches[0]["name"]
    removed = [r["name"] for r in gone if r["name"] not in renamed]

    moved = []
    for record in old:
        current = new_by.get(record["name"])
        if current is not None and renamed.get(record["parent"], record["parent"]) != current["parent"]:
            moved.append((record["name"], record["parent"], current["parent"]))
    return removed, list(renamed.items()), moved


def _contract_warnings(version, old, new, paths):
    """One :class:`Line` per change of ``_contract_changes(old, new)``, in
    three groups (removed, renamed, reparented), each selecting the joint
    it's about (``paths`` maps a name to the selected joints' long names); a
    removed joint selects nothing."""
    removed, renamed, moved = _contract_changes(old, new)
    since = f"since {version.tag}"
    lines = [Line(name, group=f"Removed {since}") for name in removed]
    lines += [Line(f"{was} → {now}", paths[now], f"Renamed {since}") for was, now in renamed]
    lines += [
        Line(f"{name}: was under {was or 'the world'}, now under {now or 'the world'}", paths[name], f"Reparented {since}")
        for name, was, now in moved
    ]
    return lines


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
    menu_slot = (2, 1)

    def selection_problems(self):
        selection = cmds.ls(selection=True)
        if not selection:
            return ["Nothing selected. Select the root joints to publish."]
        if not cmds.ls(selection, type="joint"):
            return ["No joints selected. Select the root joints to publish."]
        return []

    def publish_warnings(self, path):
        """Joints the latest published version has that this publish removes,
        renames or moves to another parent. Skin, Pose Correctives, Wrap and
        Animation items find joints by name, so these break them."""
        warnings = super().publish_warnings(path)
        latest = next(iter(versions.list_versions(path)), None)
        if latest is None:
            return warnings
        selection = cmds.ls(selection=True, long=True) or []
        paths = {}
        for joint in _joints_under(selection):
            paths.setdefault(short_name(joint), []).append(joint)
        try:
            old = data.read(latest.path, self.kind)["joints"]
            new = self.gather(selection)["joints"]
            return warnings + _contract_warnings(latest, old, new, {k: tuple(v) for k, v in paths.items()})
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            return warnings  # nothing to publish, or a version this can't read

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

    def nodes(self, payload):
        return [r["name"] for r in payload["joints"]]

    def describe(self, payload):
        records = payload["joints"]
        roots = [r["name"] for r in records if r["parent_index"] is None]
        return [f"{len(records)} joint{'s' if len(records) != 1 else ''}", f"Roots: {', '.join(roots)}"]

    def compare_view(self, payload):
        # parent_index shifts whenever joints are added or removed; the parent's name says enough.
        return {**payload, "joints": [{k: v for k, v in r.items() if k != "parent_index"} for r in payload["joints"]]}


PRODUCT = JointsProduct()
