"""Version history for Assembler items: hidden snapshots kept next to them.

An item's versions live in ``<folder>/.versions/<item name>/v001<ext>``,
``v002<ext>``, ... The item itself keeps its name and is always the
current version, so the tree, order and builds never see the history
(scan() skips dot-names). No Qt here.

A folder's versions, ``v001.json``, ..., are build plans of it with the
version each item inside was at when it was published. The folder is at a
version while it matches that exactly; restoring one rebuilds it (see
..folder_versions).
"""

import filecmp
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass

from kaiju_suite.tools.assembler.products import Action, Panel, Product, product_for

HISTORY_DIR = ".versions"
# In an item's history folder: the number of the version its content builds on.
BASE_FILE = "base"

# Versions listed in the right-click submenu; the rest are under "Show More...".
MENU_LIMIT = 5

_VERSION_RE = re.compile(r"^v(\d+)$")

# Extension of a folder's version records.
FOLDER_EXT = ".json"
# In a folder's state: an item with content that no version of it holds.
UNPUBLISHED = "*"


@dataclass
class Version:
    number: int
    path: str
    mtime: float
    size: int

    @property
    def tag(self):
        return f"v{self.number:03d}"


@dataclass
class MenuItem:
    """One entry of the right-click Versions submenu.

    ``action`` restores the version; it's ``None`` for the current one.
    """

    label: str
    action: Action = None
    current: bool = False


def history_dir(path):
    """The folder holding ``path``'s versions (it may not exist yet)."""
    directory, name = os.path.split(os.path.normpath(path))
    return os.path.join(directory, HISTORY_DIR, name)


def list_versions(path):
    """``path``'s saved versions as :class:`Version`, newest first."""
    ext = _ext(path)
    folder = history_dir(path)
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    found = []
    for name in names:
        stem, name_ext = os.path.splitext(name)
        match = _VERSION_RE.match(stem)
        if not match or name_ext.lower() != ext.lower():
            continue
        version_path = os.path.join(folder, name)
        stat = os.stat(version_path)
        found.append(Version(int(match.group(1)), version_path, stat.st_mtime, stat.st_size))
    found.sort(key=lambda v: v.number, reverse=True)
    return found


def current_version(path):
    """The saved :class:`Version` whose content matches ``path`` now, or
    ``None`` if the file has changed since (or has no versions). A folder's
    current version is the one it was last published as or restored to, while
    it still matches it: same items, order, disabled ones and item versions."""
    if os.path.isdir(path):
        return _folder_versions().current(path)
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return None
    return next((v for v in list_versions(path) if filecmp.cmp(path, v.path, shallow=False)), None)


def save_version(path):
    """Copy ``path`` into its history as the next version and return it.

    Returns ``None`` without saving if the file is empty or already matches
    a saved version, so repeated saves don't pile up copies.

    A folder saves its build plan with its items' versions instead (see
    ..folder_versions); it raises if an item has unpublished changes.
    """
    if os.path.isdir(path):
        return _save_folder_version(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    if os.path.getsize(path) == 0 or current_version(path) is not None:
        return None

    number, target = _next_target(path)
    shutil.copy2(path, target)
    set_base(path, number)
    return list_versions(path)[0]


def _folder_versions():
    from kaiju_suite.tools.assembler import folder_versions  # lazily: it imports logic, which imports this

    return folder_versions


def _ext(path):
    return FOLDER_EXT if os.path.isdir(path) else os.path.splitext(path)[1]


def _next_target(path):
    """The number and file of ``path``'s next version; makes its history folder."""
    existing = list_versions(path)
    number = existing[0].number + 1 if existing else 1
    folder = history_dir(path)
    os.makedirs(folder, exist_ok=True)
    return number, os.path.join(folder, f"v{number:03d}{_ext(path)}")


# -- folders ------------------------------------------------------------------


def _walk(folder, prefix=""):
    """``(relative path, path)`` of the items under ``folder``, recursively:
    what the tree shows (no dot-names, ``__pycache__`` or unclaimed files).
    Relative paths use ``/``, e.g. ``sub/b.py``."""
    for name in sorted(os.listdir(folder), key=str.lower):
        if name.startswith(".") or name == "__pycache__":
            continue
        path = os.path.join(folder, name)
        if os.path.isdir(path):
            yield prefix + name, path
            yield from _walk(path, f"{prefix}{name}/")
        elif product_for(path) is not None:
            yield prefix + name, path


def item_state(path):
    """What the item ``path`` is at now: a version number, :data:`UNPUBLISHED`,
    or ``None`` (folders, items that aren't versioned, empty ones). A folder
    version records this for each item in it."""
    product = product_for(path)
    if os.path.isdir(path) or not product.versioned:
        return None
    current = current_version(path)
    if current is not None:
        return current.number
    return UNPUBLISHED if _unsaved(path, None) else None


def unpublished_items(folder):
    """Relative paths of the items under ``folder`` with unpublished changes."""
    return [rel for rel, path in _walk(folder) if item_state(path) == UNPUBLISHED]


def folder_publish_problems(folder):
    """Why ``folder`` can't be published now: items with unpublished changes."""
    unpublished = unpublished_items(folder)
    if not unpublished:
        return []
    return [f"Publish these first, they have changes not published yet: {', '.join(unpublished)}"]


def _save_folder_version(folder):
    problems = folder_publish_problems(folder)
    if problems:
        raise ValueError(f"Can't publish {os.path.basename(folder)}. {problems[0]}")
    if not any(True for _ in _walk(folder)) or current_version(folder) is not None:
        return None
    number, target = _next_target(folder)
    _folder_versions().save(folder, target)
    set_base(folder, number)
    return list_versions(folder)[0]


# -- publishing and restoring -------------------------------------------------


def published_message(path, version):
    """What to tell the user once ``path`` is published as ``version``,
    e.g. ``Published Scene ball.ma v003``."""
    product = product_for(path)
    kind = f"{product.type_name(path)} " if product is not None else ""
    return f"Published {kind}{os.path.basename(path)} {version.tag}"


def export_into(path, write_fn):
    """Replace ``path`` with what ``write_fn`` writes and save it as its next
    version. Returns a message, e.g. ``Published Joints spine.jnt v002``.

    ``write_fn(target)`` writes the new content to ``target``, a temporary
    file with the same name as ``path``. Only if it succeeds is ``path``
    replaced, so a failure changes nothing and saves no version. Old content
    not yet in the history is saved as a version first, so nothing is lost.
    Content that matches a saved version adds none: it's then that one.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    folder = tempfile.mkdtemp(prefix="kaiju_export_")
    try:
        target = os.path.join(folder, os.path.basename(path))
        write_fn(target)
        if not os.path.isfile(target) or os.path.getsize(target) == 0:
            raise RuntimeError(f"Nothing was written for {os.path.basename(path)}")
        save_version(path)
        shutil.copyfile(target, path)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    version = save_version(path) or current_version(path)
    return published_message(path, version)


def publish(path):
    """Save ``path`` as it is as its next version. Returns a message."""
    name = os.path.basename(path)
    version = save_version(path)
    if version:
        return published_message(path, version)
    current = current_version(path)
    return f"{name} is already published as {current.tag}" if current else f"{name} is empty: nothing to publish"


def publish_action(path):
    """The :class:`Action` for right-click Publish: the product's own, or
    :func:`publish` if it has none."""
    product = product_for(path)
    action = product.publish(path) if product is not None else None
    return action or Action("Publish", lambda: publish(path))


def publish_problems(path):
    """The pre-publish check: what stops ``path`` being published now, as
    messages (empty if nothing does). Run it before :func:`publish_action`."""
    product = product_for(path)
    return product.publish_problems(path) if product is not None else []


def publish_warnings(path):
    """What looks wrong about publishing ``path`` now without stopping it, as
    messages (empty if nothing does). Run it after :func:`publish_problems`."""
    product = product_for(path)
    return product.publish_warnings(path) if product is not None else []


def restore_version(path, number):
    """Replace ``path`` with version ``number``. Adds no version: content
    not published is lost, so callers should warn first (see
    :func:`panel`). Returns a message."""
    version = next((v for v in list_versions(path) if v.number == number), None)
    if version is None:
        raise FileNotFoundError(f"{os.path.basename(path)} has no version {number}")
    if os.path.isdir(path):
        return _folder_versions().restore(path, version)
    product = product_for(path)
    if product is not None:
        product.before_replace(path)
    shutil.copy2(version.path, path)
    set_base(path, number)
    return f"Restored {os.path.basename(path)} to {version.tag}"


def base_version(path):
    """The version ``path`` was last published as or restored to, which its
    current content builds on. Falls back to the latest version if there's
    no record (e.g. versions copied in by hand); ``None`` with no versions."""
    found = list_versions(path)
    try:
        with open(os.path.join(history_dir(path), BASE_FILE), encoding="utf-8") as f:
            number = int(f.read().strip())
    except (OSError, ValueError):
        number = None
    return next((v for v in found if v.number == number), found[0] if found else None)


def set_base(path, number):
    """Record that ``path``'s content now builds on version ``number`` (see :func:`base_version`)."""
    with open(os.path.join(history_dir(path), BASE_FILE), "w", encoding="utf-8") as f:
        f.write(str(number))


def move_history(old_path, new_path):
    """Move ``old_path``'s versions to go with the item now at ``new_path``."""
    old, new = history_dir(old_path), history_dir(new_path)
    if not os.path.isdir(old) or old == new:
        return
    if os.path.normcase(old) == os.path.normcase(new):
        os.rename(old, new)  # case-only rename; shutil.move would nest it
        return
    if os.path.exists(new):
        shutil.rmtree(new)  # stale history of an item that no longer exists
    os.makedirs(os.path.dirname(new), exist_ok=True)
    shutil.move(old, new)
    _prune(os.path.dirname(old))


def delete_history(path):
    """Delete ``path``'s versions, if it has any."""
    folder = history_dir(path)
    if os.path.isdir(folder):
        shutil.rmtree(folder)
        _prune(os.path.dirname(folder))


def _prune(folder):
    """Remove the ``.versions`` folder once nothing is left in it."""
    try:
        os.rmdir(folder)
    except OSError:
        pass


def _when(timestamp):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


def _unsaved(path, current):
    """Whether ``path`` has content that no saved version holds; for a folder,
    whether its items have changed since it was published."""
    if os.path.isdir(path):
        return current is None and bool(list_versions(path))
    return current is None and os.path.isfile(path) and os.path.getsize(path) > 0


def summary(path):
    """One line about ``path``'s history, for info panels."""
    found = list_versions(path)
    if not found:
        return "No versions published yet."
    count = f"{len(found)} version{'s' if len(found) != 1 else ''}"
    current = current_version(path)
    if current is not None:
        return f"Current: {current.tag} ({count})"
    if _unsaved(path, current):
        return f"Has changes not published yet ({count})"
    return count


def _describe(path, version):
    if os.path.isdir(path):
        count = _folder_versions().item_count(version)
        return f"{version.tag}  {_when(version.mtime)}, {count} item{'s' if count != 1 else ''}"
    return f"{version.tag}  {_when(version.mtime)}, {version.size / 1024:.1f} KB"


def _restore_action(path, version, unsaved):
    """Switching between saved versions loses nothing, so it only asks when
    the file has changes no version holds (for a folder: when items in it
    have them, since restoring replaces or removes every item)."""
    confirm = None
    if os.path.isdir(path):
        lost = _folder_versions().lost_by_restoring(path)
        if lost:
            confirm = (
                f"Switch {os.path.basename(path)} to {version.tag}?"
                f" Unpublished changes in {', '.join(lost)} will be lost."
            )
    elif unsaved:
        confirm = (
            f"Replace {os.path.basename(path)} with {version.tag}?"
            " Your unpublished changes will be lost."
        )
    return Action(f"Restore {_describe(path, version)}", lambda n=version.number: restore_version(path, n), confirm)


def menu(path, limit=MENU_LIMIT):
    """Entries for the right-click Versions submenu and whether more exist.

    Returns ``(items, more)``: the newest ``limit`` versions as
    :class:`MenuItem`, with the current one marked.
    """
    found = list_versions(path)
    current = current_version(path)
    unsaved = _unsaved(path, current)
    items = [
        MenuItem(_describe(path, v), None, True)
        if current is not None and v.number == current.number
        else MenuItem(_describe(path, v), _restore_action(path, v, unsaved))
        for v in found[:limit]
    ]
    return items, len(found) > limit


def tree_label(path):
    """Text for the tree's version column and whether it's the latest.

    ``("", True)`` with no versions, ``("v002", False)`` when an older version
    is restored. A ``*`` marks unpublished changes on top of the version the
    file builds on, e.g. ``("v002*", True)``.
    """
    if not os.path.exists(path):
        return "", True
    found = list_versions(path)
    if not found:
        return "", True
    current = current_version(path)
    if current is not None:
        return current.tag, current.number == found[0].number
    base = base_version(path)
    return f"{base.tag}*", base.number == found[0].number


def menu_status(path):
    """A note to show above the submenu's versions, or ``None`` for none."""
    current = current_version(path)
    if not list_versions(path):
        return "No versions published yet."
    if _unsaved(path, current):
        return "Has changes not published yet"
    return None


def panel(path):
    """A :class:`Panel` with one Restore button per version other than the
    current one. Restoring asks first only if unsaved content would be lost."""
    current = current_version(path)
    unsaved = _unsaved(path, current)
    actions = [
        _restore_action(path, v, unsaved)
        for v in list_versions(path)
        if current is None or v.number != current.number
    ]
    return Panel([summary(path)], actions)


# -- comparing ----------------------------------------------------------------


def can_compare(path):
    """Whether ``path`` gets Versions ▸ Compare With: a file of a product
    that can compare two of its versions (see ``Product.compare_files``)."""
    product = product_for(path)
    return (
        product is not None
        and os.path.isfile(path)
        and type(product).compare_files is not Product.compare_files
    )


def compare_choices(path):
    """The versions to compare ``path`` with, newest first: every one but the
    version the file is at now."""
    current = current_version(path)
    return [v for v in list_versions(path) if current is None or v.number != current.number]


def compare_menu(path, limit=MENU_LIMIT):
    """Entries for the Compare With submenu: ``(label, version number)`` of
    the newest ``limit`` :func:`compare_choices`."""
    return [(_describe(path, v), v.number) for v in compare_choices(path)[:limit]]


def compare_panel(path, number):
    """A :class:`Panel` saying what changed from version ``number`` to
    ``path`` as it is now; the first line names the two."""
    version = next((v for v in list_versions(path) if v.number == number), None)
    if version is None:
        raise FileNotFoundError(f"{os.path.basename(path)} has no version {number}")
    current = current_version(path)
    empty = os.path.getsize(path) == 0
    if current is not None:
        now = f"current ({current.tag})"
    else:
        now = "current (empty)" if empty else "current (not published)"
    if empty:
        lines = ["The current file is empty."]
    else:
        try:
            lines = product_for(path).compare_files(version.path, path)
        except (OSError, ValueError) as e:
            lines = [f"Can't compare: {e}"]
    return Panel([f"{version.tag} → {now}", *lines], [])
