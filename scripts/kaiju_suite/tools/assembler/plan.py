"""Build plans: a whole Assembler tree as one JSON, to export and import.

A plan lists a folder's items in build order; folders nest::

    {"items": [
        {"name": "setup.py", "content": "..."},
        {"name": "arms", "enabled": false, "items": [
            {"name": "L_arm.rig", "module": "simple_ik", "params": {...}},
            {"name": "body.mesh"}
        ]}
    ]}

An item with ``items`` is a folder; any other is a file, whose extension
says its product. ``enabled`` defaults to true. The rest of an item is its
content, as its product describes it (see ``Product.to_plan``): Scripts
carry their code, Scenes the Maya file's path, Rig Modules their module and
parameters. Other items (Mesh, Joints, ...) are planned as empty entries to
publish into. Versions and run logs aren't part of a plan.

Plan files hold a plan under the usual Kaiju header (``buildPlan`` kind),
but :func:`parse_plan` also takes a bare one, e.g. pasted from an AI chat.
No Qt here.
"""

import json
import os

from kaiju_suite.core import datafile
from kaiju_suite.tools.assembler import logic
from kaiju_suite.tools.assembler.products import product_for_name

KIND = "buildPlan"


def export_plan(root, include_folder=False):
    """The plan of everything under ``root``, in build order. With
    ``include_folder``, the plan holds ``root`` itself (its name and whether
    it's enabled) with everything in it, so importing it re-creates the
    folder."""
    items = _export(logic.scan(root))
    if include_folder:
        folder = {"name": os.path.basename(os.path.normpath(root))}
        if not logic.is_enabled(root):
            folder["enabled"] = False
        folder["items"] = items
        items = [folder]
    return {"items": items}


def _export(entries):
    items = []
    for entry in entries:
        item = {"name": entry.name}
        if not entry.enabled:
            item["enabled"] = False
        if entry.is_dir:
            item["items"] = _export(entry.children)
        else:
            item.update(entry.product.to_plan(entry.path))
        items.append(item)
    return items


# -- checking -----------------------------------------------------------------


def plan_problems(plan):
    """Everything wrong with ``plan``, as messages naming the item, e.g.
    ``arms/L_arm.rig: no rig module 'ikfk'``. Empty if it can be imported."""
    if not isinstance(plan, dict) or not isinstance(plan.get("items"), list):
        return ["The plan needs an items list."]
    problems = []
    _check(plan["items"], "", problems)
    return problems


def _check(items, prefix, problems):
    where = prefix.rstrip("/") or "top level"
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            problems.append(f"{where}: every item must be an object, not {item!r}")
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            problems.append(f"{where}: every item needs a name")
            continue
        found = _item_problems(item, name, seen)
        seen.add(name.lower())
        problems.extend(f"{prefix}{name}: {p}" for p in found)
        if "items" in item and isinstance(item["items"], list) and not found:
            _check(item["items"], f"{prefix}{name}/", problems)


def _item_problems(item, name, seen):
    if "/" in name or "\\" in name:
        return ["names can't contain / or \\"]
    if name.startswith("."):
        return ["names can't start with a dot (the Assembler hides those)"]
    if name.lower() in seen:
        return [f"more than one item named {name} in this folder"]
    problems = []
    if not isinstance(item.get("enabled", True), bool):
        problems.append("enabled must be true or false")
    if "items" in item:
        if not isinstance(item["items"], list):
            problems.append("items must be a list (it's a folder)")
        return problems
    product = product_for_name(name)
    if product is None:
        ext = os.path.splitext(name)[1]
        kind = f"uses {ext}" if ext else "uses files with no extension; a folder needs an items list"
        return problems + [f"no item type {kind}"]
    return problems + product.plan_problems(item)


# -- import -------------------------------------------------------------------


def import_plan(plan, root):
    """Create ``plan``'s items in ``root``, after what's already there, and
    return their paths. They start with no versions. An item whose name is
    taken in ``root`` gets a free one, as Paste does (``setup_copy.py``).

    Checks everything first (see :func:`plan_problems`) and raises
    :class:`ValueError` listing every problem before creating anything. If
    creating fails part-way, what was created is removed again.
    """
    if not os.path.isdir(root):
        raise FileNotFoundError(f"Folder not found: {root}")
    problems = plan_problems(plan)
    if problems:
        raise ValueError("Can't import the build plan:\n" + "\n".join(f"- {p}" for p in problems))

    existing = {n.lower() for n in os.listdir(root)}
    # A new name mustn't take one the plan uses further on, either.
    taken = existing | {i["name"].lower() for i in plan["items"]}
    names = []
    for item in plan["items"]:
        name = logic.free_name(item["name"], taken) if item["name"].lower() in existing else item["name"]
        taken.add(name.lower())
        names.append(name)

    created = []
    try:
        for item, name in zip(plan["items"], names):
            path = os.path.join(root, name)
            created.append(path)
            _create(item, path)
    except Exception:
        for path in created:
            if os.path.exists(path):
                logic.delete_path(path)
        raise
    logic.append_to_order(root, names)
    for item, path in zip(plan["items"], created):
        if not item.get("enabled", True):
            logic.set_enabled(path, False)
    return created


def _create(item, path):
    if "items" in item:
        os.makedirs(path)
        for child in item["items"]:
            child_path = os.path.join(path, child["name"])
            _create(child, child_path)
            if not child.get("enabled", True):
                logic.set_enabled(child_path, False)
        logic.append_to_order(path, [c["name"] for c in item["items"]])
    else:
        product_for_name(item["name"]).from_plan(path, item)


# -- plan files ---------------------------------------------------------------


def save_plan(root, path, include_folder=False):
    """Export ``root``'s plan (see :func:`export_plan`) to the file ``path``;
    returns ``path``."""
    return datafile.write(path, KIND, export_plan(root, include_folder))


def load_plan(path):
    """The plan in the file ``path`` (see :func:`parse_plan`)."""
    with open(path, encoding="utf-8") as f:
        return parse_plan(f.read())


def parse_plan(text):
    """The plan in JSON ``text``, with or without the Kaiju header. Raises
    :class:`~kaiju_suite.core.datafile.DataFormatError` if it isn't one.
    Doesn't check the items: see :func:`plan_problems`."""
    try:
        content = json.loads(text)
    except ValueError as e:
        raise datafile.DataFormatError(f"Not a build plan: {e}") from e
    if isinstance(content, dict) and "kaiju" in content:
        if content["kaiju"] != KIND:
            raise datafile.DataFormatError(f"Not a build plan: it holds {content['kaiju']!r} data.")
        file_format = content.get("format")
        if not isinstance(file_format, int) or file_format > datafile.FORMAT:
            raise datafile.DataFormatError("This build plan was written by a newer Kaiju Suite.")
        content = content.get("data")
    return content
