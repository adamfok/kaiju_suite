"""Version history for Assembler items: hidden snapshots kept next to them.

An item's versions live in ``<folder>/.versions/<item name>/v001<ext>``,
``v002<ext>``, ... The item itself keeps its name and is always the
current version, so the tree, order and builds never see the history
(scan() skips dot-names). No Qt here.

A folder's versions, ``v001.json``, ..., are build plans of it with the
version each item inside was at when it was published. The folder is at a
version while it matches that exactly; restoring one rebuilds it (see
..folder_versions).

Every version can have a short description of what changed, kept in
``descriptions.json`` next to the ``base`` file, so it moves, copies and is
deleted with the history. The user types it on Publish (see
:func:`describing`); versions saved without them publishing describe
themselves, e.g. "Republished v002".
"""

import filecmp
import json
import os
import re
import shutil
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace

from kaiju_suite.tools.assembler import compare
from kaiju_suite.tools.assembler.products import Action, Panel, Product, product_for

HISTORY_DIR = ".versions"
# In an item's history folder: the number of the version its content builds on.
BASE_FILE = "base"
# In a history folder: each version's description, as ``{"3": "Fixed the knee"}``.
DESCRIPTIONS_FILE = "descriptions.json"

# Shown for a version saved without a description (e.g. before they existed).
NO_DESCRIPTION = "(no description)"
# The description of old content that publishing new content saves first.
KEPT_UNPUBLISHED = "Unpublished changes, kept automatically"
# Descriptions longer than this are shortened in titles, e.g. of the compare window.
LABEL_DESCRIPTION_LIMIT = 40

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
    description: str = ""

    @property
    def tag(self):
        return f"v{self.number:03d}"


@dataclass
class ChangelogRow:
    """One version in the Versions window. ``restore`` is ``None`` for the current one."""

    number: int
    tag: str
    when: str
    description: str
    current: bool
    restore: Action = None


@dataclass
class Changelog:
    """What the Versions window shows: a ``summary`` line, then every version
    as a :class:`ChangelogRow`, newest first. ``can_compare`` says whether
    rows can be compared with the file as it is now."""

    summary: str
    rows: list
    can_compare: bool


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
    descriptions = _read_descriptions(folder)
    for name in names:
        stem, name_ext = os.path.splitext(name)
        match = _VERSION_RE.match(stem)
        if not match or name_ext.lower() != ext.lower():
            continue
        version_path = os.path.join(folder, name)
        stat = os.stat(version_path)
        number = int(match.group(1))
        found.append(Version(number, version_path, stat.st_mtime, stat.st_size, descriptions.get(str(number), "")))
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


def save_version(path, latest=False, description=None):
    """Copy ``path`` into its history as the next version and return it.

    Returns ``None`` without saving if the file is empty or already matches
    a saved version, so repeated saves don't pile up copies. With
    ``latest``, content matching an older version is saved again as the
    newest, so publishing an older version makes it the latest; its
    description then says which one, e.g. "Republished v002".

    ``description`` says what changed; ``None`` takes the one given to
    :func:`describing`, if any.

    A folder saves its build plan with its items' versions instead (see
    ..folder_versions); it raises if an item has unpublished changes.
    """
    if os.path.isdir(path):
        return _save_folder_version(path, latest, description)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    if os.path.getsize(path) == 0 or _is_saved(path, latest):
        return None

    text = _new_description(path, description)
    number, target = _next_target(path)
    shutil.copy2(path, target)
    _finish(path, number, text)
    return list_versions(path)[0]


def _finish(path, number, text):
    set_base(path, number)
    _write_description(path, number, text)


# -- descriptions ---------------------------------------------------------------

_described = []  # what :func:`describing` blocks were given, innermost last


@contextmanager
def describing(text):
    """Describe every version saved inside the ``with`` block as ``text``,
    unless it's saved with a description of its own. This lets one prompt
    describe whatever a Publish action saves, however it saves it."""
    _described.append(text)
    try:
        yield
    finally:
        _described.pop()


def _given(description):
    if description is None and _described:
        description = _described[-1]
    return (description or "").strip()


def _new_description(path, description):
    """The description for a version about to be saved from ``path``: the
    given one, saying which version it republishes if it matches an older one."""
    text = _given(description)
    current = current_version(path)
    if current is None:
        return text
    return f"{text} (republished {current.tag})" if text else f"Republished {current.tag}"


def _read_descriptions(folder):
    try:
        with open(os.path.join(folder, DESCRIPTIONS_FILE), encoding="utf-8") as f:
            found = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(found, dict):
        return {}
    return {k: v for k, v in found.items() if isinstance(v, str)}


def _write_description(path, number, text):
    folder = history_dir(path)
    stored = os.path.join(folder, DESCRIPTIONS_FILE)
    found = _read_descriptions(folder)
    found.pop(str(number), None)  # a stale one, e.g. of a version deleted by hand
    if text:
        found[str(number)] = text
    if not found and not os.path.exists(stored):
        return
    with open(stored, "w", encoding="utf-8") as f:
        json.dump(found, f, indent=2, sort_keys=True)


def description_text(version):
    """``version``'s description, or :data:`NO_DESCRIPTION`."""
    return version.description or NO_DESCRIPTION


def _short(text, limit=LABEL_DESCRIPTION_LIMIT):
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def suggested_description(path):
    """What the Publish prompt starts with: for a folder, the item versions
    that changed since its last version (e.g. ``a.py v002, removed b.py``);
    nothing for a file."""
    if not os.path.isdir(path):
        return ""
    return ", ".join(_folder_versions().changes(path))


def _folder_versions():
    from kaiju_suite.tools.assembler import folder_versions  # lazily: it imports logic, which imports this

    return folder_versions


def _is_saved(path, latest):
    """Whether ``path`` needs no new version: it matches a saved one (with
    ``latest``, the newest one)."""
    current = current_version(path)
    if current is None:
        return False
    return not latest or current.number == list_versions(path)[0].number


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


def _save_folder_version(folder, latest=False, description=None):
    problems = folder_publish_problems(folder)
    if problems:
        raise ValueError(f"Can't publish {os.path.basename(folder)}. {problems[0]}")
    if not any(True for _ in _walk(folder)) or _is_saved(folder, latest):
        return None
    text = _new_description(folder, description)
    number, target = _next_target(folder)
    _folder_versions().save(folder, target)
    _finish(folder, number, text)
    return list_versions(folder)[0]


# -- publishing and restoring -------------------------------------------------


def published_message(path, version):
    """What to tell the user once ``path`` is published as ``version``,
    e.g. ``Published Scene ball.ma v003``."""
    product = product_for(path)
    kind = f"{product.type_name(path)} " if product is not None else ""
    return f"Published {kind}{os.path.basename(path)} {version.tag}"


def export_into(path, write_fn, description=None):
    """Replace ``path`` with what ``write_fn`` writes and save it as its next
    version, described as ``description`` (see :func:`save_version`).
    Returns a message, e.g. ``Published Joints spine.jnt v002``.

    ``write_fn(target)`` writes the new content to ``target``, a temporary
    file with the same name as ``path``. Only if it succeeds is ``path``
    replaced, so a failure changes nothing and saves no version. Old content
    not yet in the history is saved as a version first, so nothing is lost
    (described as :data:`KEPT_UNPUBLISHED`).
    Content that matches the latest version adds none; content that matches
    an older one is saved again as the latest.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    folder = tempfile.mkdtemp(prefix="kaiju_export_")
    try:
        target = os.path.join(folder, os.path.basename(path))
        write_fn(target)
        if not os.path.isfile(target) or os.path.getsize(target) == 0:
            raise RuntimeError(f"Nothing was written for {os.path.basename(path)}")
        save_version(path, description=KEPT_UNPUBLISHED)
        shutil.copyfile(target, path)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    version = save_version(path, latest=True, description=description) or current_version(path)
    return published_message(path, version)


def publish(path, description=None):
    """Save ``path`` as it is as its next version. Returns a message.

    Publishing an older version saves it again as the latest."""
    name = os.path.basename(path)
    version = save_version(path, latest=True, description=description)
    if version:
        return published_message(path, version)
    current = current_version(path)
    return f"{name} is already published as {current.tag}" if current else f"{name} is empty: nothing to publish"


def publish_action(path):
    """The :class:`Action` for right-click Publish: the product's own, or
    :func:`publish` if it has none. It asks for a description (``describe``):
    run it inside :func:`describing`."""
    product = product_for(path)
    action = product.publish(path) if product is not None else None
    return replace(action or Action("Publish", lambda: publish(path)), describe=True)


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


def copy_history(src, new):
    """Give the copy at ``new`` its own copy of ``src``'s versions."""
    old, target = history_dir(src), history_dir(new)
    if not os.path.isdir(old):
        return
    if os.path.exists(target):
        shutil.rmtree(target)  # stale history of an item that no longer exists
    shutil.copytree(old, target)


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
    """A version's menu label: tag, date, size or item count, and its description, shortened."""
    if os.path.isdir(path):
        count = _folder_versions().item_count(version)
        details = f"{count} item{'s' if count != 1 else ''}"
    else:
        details = f"{version.size / 1024:.1f} KB"
    return f"{version.tag}  {_when(version.mtime)}, {details}  -  {_short(description_text(version))}"


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


def changelog(path):
    """The Versions window's :class:`Changelog`: every version with its date
    and description, and a Restore for each but the current one. Restoring
    asks first only if unsaved content would be lost."""
    current = current_version(path)
    unsaved = _unsaved(path, current)
    rows = []
    for v in list_versions(path):
        is_current = current is not None and v.number == current.number
        restore = None if is_current else _restore_action(path, v, unsaved)
        rows.append(ChangelogRow(v.number, v.tag, _when(v.mtime), description_text(v), is_current, restore))
    return Changelog(summary(path), rows, can_compare(path))


# -- comparing ----------------------------------------------------------------


def can_compare(path):
    """Whether ``path``'s Versions window has Compare: a file of a product
    that can compare two of its versions (see ``Product.compare_files``)."""
    product = product_for(path)
    return (
        product is not None
        and os.path.isfile(path)
        and type(product).compare_files is not Product.compare_files
    )


def compare_panel(path, number):
    """A :class:`Panel` comparing version ``number`` (left) with ``path`` as
    it is now (right), side by side."""
    version = next((v for v in list_versions(path) if v.number == number), None)
    if version is None:
        raise FileNotFoundError(f"{os.path.basename(path)} has no version {number}")
    if os.path.getsize(path) == 0:
        return Panel(["The current file is empty."], [])
    current = current_version(path)
    now = current.tag if current is not None else "not published"
    return _compare_result(_describe(path, version), f"Current file ({now})", product_for(path), version.path, path)


def can_compare_items(paths):
    """Whether right-click Compare shows for the selected ``paths``: exactly
    two files of one product that can compare (see :func:`can_compare`)."""
    if len(paths) != 2 or not all(can_compare(p) for p in paths):
        return False
    first, second = (product_for(p) for p in paths)
    return first is second


def compare_items_panel(old_path, new_path):
    """A :class:`Panel` comparing item ``old_path`` (left) with item
    ``new_path`` (right), laid out like :func:`compare_panel`."""
    empty = [os.path.basename(p) for p in (old_path, new_path) if os.path.getsize(p) == 0]
    if empty:
        return Panel([f"{name} is empty." for name in empty], [])
    titles = (os.path.basename(p) for p in (old_path, new_path))
    return _compare_result(*titles, product_for(new_path), old_path, new_path)


def _compare_result(old_title, new_title, product, old_path, new_path):
    try:
        rows = product.compare_files(old_path, new_path)
    except (OSError, ValueError) as e:
        return Panel([f"Can't compare: {e}"], [])
    info = [] if compare.has_changes(rows) else [compare.NO_CHANGES]
    return Panel(info, [], diff=compare.Diff(old_title, new_title, rows))
