"""Folder versions: a build plan of the folder, with each item's version.

Publishing a folder saves what Build ▸ Export would (its items in build
order, which are disabled, each item's plan content; see ..plan), and adds
the version each item is at. Restoring one rebuilds the folder to match:
items the version doesn't have are removed, ones it has that are missing
are created, and every item is set back to the version it recorded, so a
folder can go up or down between versions with different children.

Removed items keep their version history, so switching back brings them
back as they were. A removed subfolder is moved whole into the hidden
history (see :func:`_stash_path`) for the same reason: its items' histories
live inside it. An item whose history is gone (deleted by hand) is made from
its plan content instead; data items, which plans hold as empty entries,
come back empty. No Qt here.
"""

import json
import os
import shutil

from kaiju_suite.tools.assembler import logic, plan, versions
from kaiju_suite.tools.assembler.products import product_for_name

# In a subfolder's history folder: the subfolder itself while a restored
# version doesn't have it.
STASH_DIR = "removed"


def snapshot(folder):
    """What a folder version records: ``folder``'s build plan, each file item
    with the ``version`` it's at (a number, or ``versions.UNPUBLISHED``; none
    for empty and unversioned items)."""
    return plan.export_plan(folder, fields=_fields)


def _fields(entry):
    try:
        item = entry.product.to_plan(entry.path)
    except (OSError, ValueError, LookupError):
        item = {}  # unreadable now; its version still holds it
    state = versions.item_state(entry.path)
    if state is not None:
        item["version"] = state
    return item


def plan_of(version):
    """The plan a folder ``version`` recorded, or ``None`` if unreadable."""
    try:
        with open(version.path, encoding="utf-8") as f:
            recorded = json.load(f)["plan"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return recorded if isinstance(recorded, dict) and isinstance(recorded.get("items"), list) else None


def save(folder, target):
    """Write ``folder``'s :func:`snapshot` to the version file ``target``."""
    with open(target, "w", encoding="utf-8") as f:
        json.dump({"plan": snapshot(folder)}, f, indent=2)


def current(folder):
    """``folder``'s base version (the one last published or restored) if it
    still matches the folder, or ``None``. Unlike a file, a folder never
    jumps to another version that happens to match, e.g. when a subfolder is
    switched back: it shows its own version with a ``*``."""
    base = versions.base_version(folder)
    return base if base is not None and plan_of(base) == _now(folder) else None


def _now(folder):
    return json.loads(json.dumps(snapshot(folder)))  # as a saved one reads back


def item_count(version):
    """How many items (not folders) a folder ``version`` recorded."""
    return sum(1 for _ in _files((plan_of(version) or {}).get("items", []), "", ""))


def _files(items, directory, prefix):
    """``(relative path, path, item)`` of every file item in ``items``, recursively."""
    for item in items:
        path = os.path.join(directory, item["name"])
        rel = prefix + item["name"]
        if "items" in item:
            yield from _files(item["items"], path, rel + "/")
        else:
            yield rel, path, item


def _has_version(path, number):
    return any(v.number == number for v in versions.list_versions(path))


# -- restoring ----------------------------------------------------------------


def lost_by_restoring(folder):
    """Items under ``folder`` whose unpublished changes a restore would lose:
    every one with some, since a restore replaces or removes all of them."""
    return versions.unpublished_items(folder)


def restore(folder, version):
    """Rebuild ``folder`` as folder ``version`` recorded it. Returns a message.

    Checks first that every item there now still has the version it would be
    set to, and changes nothing if one doesn't.
    """
    name = os.path.basename(folder)
    recorded = plan_of(version)
    if recorded is None:
        raise ValueError(f"Can't read {version.tag} of {name}")
    for rel, path, item in _files(recorded["items"], folder, ""):
        number = item.get("version")
        if isinstance(number, int) and os.path.isfile(path) and not _has_version(path, number):
            raise FileNotFoundError(f"{rel} has no version v{number:03d} any more")

    remade = []
    _apply(folder, recorded["items"], "", remade)
    versions.set_base(folder, version.number)
    message = f"Restored {name} to {version.tag}"
    if remade:
        message += (
            f". Their versions were deleted, so these were made from the plan"
            f" (published data comes back empty): {', '.join(remade)}"
        )
    return message


def _apply(directory, items, prefix, remade):
    planned = {item["name"].lower(): item["name"] for item in items}
    for name in logic.item_names(directory):
        wanted = planned.get(name.lower())
        if wanted is None:
            _remove(os.path.join(directory, name))
        elif wanted != name:
            logic.rename_path(os.path.join(directory, name), wanted)  # case only

    for item in items:
        path = os.path.join(directory, item["name"])
        rel = prefix + item["name"]
        if "items" in item:
            _bring_back_folder(path)
            _apply(path, item["items"], rel + "/", remade)
        else:
            _restore_item(path, item, rel, remade)
    logic.set_layout(
        directory,
        [item["name"] for item in items],
        [item["name"] for item in items if not item.get("enabled", True)],
    )


def _stash_path(path):
    """Where the subfolder ``path`` is kept while a restored version doesn't have it."""
    return os.path.join(versions.history_dir(path), STASH_DIR)


def _remove(path):
    """Remove an item the restored version doesn't have, keeping its history."""
    if os.path.isdir(path):
        stash = _stash_path(path)
        if os.path.exists(stash):
            shutil.rmtree(stash)
        os.makedirs(os.path.dirname(stash), exist_ok=True)
        shutil.move(path, stash)
    else:
        os.remove(path)


def _bring_back_folder(path):
    if os.path.isfile(path):
        os.remove(path)
    if os.path.isdir(path):
        return
    stash = _stash_path(path)
    if os.path.isdir(stash):
        shutil.move(stash, path)
        for empty in (os.path.dirname(stash), os.path.dirname(os.path.dirname(stash))):
            try:
                os.rmdir(empty)  # no folder versions of its own
            except OSError:
                break
    else:
        os.makedirs(path)


def _restore_item(path, item, rel, remade):
    if os.path.isdir(path):
        _remove(path)
    product = product_for_name(item["name"])
    number = item.get("version")
    if isinstance(number, int):
        if _has_version(path, number):
            now = versions.current_version(path) if os.path.isfile(path) else None
            if now is None or now.number != number:
                versions.restore_version(path, number)
            return
        remade.append(rel)
        if os.path.isfile(path):
            return  # came back with its subfolder: keep what it has
    elif os.path.isfile(path) and not product.versioned:
        return  # e.g. a separator: nothing to set back
    if os.path.isfile(path):
        product.before_replace(path)
    product.from_plan(path, item)
