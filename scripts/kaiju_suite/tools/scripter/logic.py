"""Kaiju Scripter logic: a folder of scripts, in your order, run on demand.

The tree is the folder on disk; its items are the kinds in :mod:`.items`
(scripts, folders, separators, breakpoints, data and file items). Each folder keeps its order and disabled items in
``<folder>/.scripter/order.json``, by name; anything not listed there comes
after, sorted by name. Dot-names and ``__pycache__`` aren't shown.

:class:`Runner` runs the selected items and keeps each one's status, in
memory only. No Qt here.
"""

import json
import os
import shutil
import sys
import traceback
from dataclasses import dataclass, field

from maya import cmds

from kaiju_suite.core import settings
from kaiju_suite.core.log import get_logger
from kaiju_suite.core.undo import undo_chunk
from kaiju_suite.tools.scripter import items, versions
from kaiju_suite.tools.scripter.items import (  # noqa: F401 (re-exported)
    BREAKPOINT,
    CONTROLSHAPE,
    EXPORT_FILE,
    EXTENSIONS,
    FOLDER,
    IMPORT_FILE,
    JOINTS,
    MESH,
    SCRIPT,
    SELECTION,
    SEPARATOR,
    SKIN,
    kind_of,
    run_script,
)
from kaiju_suite.tools.scripter.versions import HIDDEN_DIR  # noqa: F401 (everything Scripter keeps in a folder)

log = get_logger(__name__)

SETTINGS_KEY = "scripter"
# How many folders the folder dropdown remembers.
MAX_RECENT = 10

ORDER_FILE = "order.json"
SKIP_DIRS = ("__pycache__",)

# A separator's Version and Type columns, so it reads as a divider.
SEPARATOR_TEXT = "====="


@dataclass
class Entry:
    name: str
    path: str
    kind: str
    enabled: bool = True
    children: list = field(default_factory=list)

    @property
    def is_dir(self):
        return self.kind == FOLDER

    @property
    def label(self):
        """Name shown in the tree: files lose their extension."""
        return self.name if self.is_dir else os.path.splitext(self.name)[0]

    @property
    def type_label(self):
        """The Type column: the kind, blank for folders, a rule for separators."""
        if self.kind == FOLDER:
            return ""
        if self.kind == SEPARATOR:
            return SEPARATOR_TEXT
        return self.kind


def scan(root):
    """The items under ``root`` as a list of :class:`Entry`, in its order."""
    disabled = set(_load_meta(root)["disabled"])
    entries = []
    for name in _ordered_names(root):
        path = os.path.join(root, name)
        kind = kind_of(path)
        entry = Entry(name, path, kind, enabled=name not in disabled)
        if kind == FOLDER:
            entry.children = scan(path)
        entries.append(entry)
    return entries


def _listed_names(root):
    """The names :func:`scan` shows in ``root``, sorted by name."""
    try:
        names = os.listdir(root)
    except OSError:
        log.exception("Cannot list %s", root)
        return []
    shown = []
    for name in sorted(names, key=str.lower):
        if name.startswith(".") or name in SKIP_DIRS:
            continue
        if kind_of(os.path.join(root, name)) is not None:
            shown.append(name)
    return shown


def _ordered_names(root):
    names = _listed_names(root)
    present = set(names)
    ordered = [n for n in _load_meta(root)["order"] if n in present]
    seen = set(ordered)
    return ordered + [n for n in names if n not in seen]


# -- the order file ---------------------------------------------------------


def _meta_path(directory):
    return os.path.join(directory, HIDDEN_DIR, ORDER_FILE)


def _load_meta(directory):
    meta = {"order": [], "disabled": []}
    path = _meta_path(directory)
    if not os.path.isfile(path):
        return meta
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for key in meta:
            value = data.get(key, [])
            if isinstance(value, list):
                meta[key] = [str(v) for v in value]
    except (OSError, ValueError, AttributeError):
        log.warning("Ignoring unreadable %s", path)
    return meta


def _save_meta(directory, meta):
    path = _meta_path(directory)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def _forget(path):
    """Drop ``path`` from its folder's order file. Returns whether it was disabled."""
    directory, name = os.path.split(os.path.normpath(path))
    meta = _load_meta(directory)
    was_disabled = name in meta["disabled"]
    if was_disabled or name in meta["order"]:
        meta["order"] = [n for n in meta["order"] if n != name]
        meta["disabled"] = [n for n in meta["disabled"] if n != name]
        _save_meta(directory, meta)
    return was_disabled


def _insert_order(directory, current, names, anchor):
    """Save ``directory``'s order as ``current`` with ``names`` before ``anchor``."""
    moving = set(names)
    order = [n for n in current if n not in moving]
    at = order.index(anchor) if anchor is not None else len(order)
    order[at:at] = names
    meta = _load_meta(directory)
    meta["order"] = order
    _save_meta(directory, meta)


def _anchor(current, index, moving):
    """The first name at or after ``index`` in ``current`` that isn't moving;
    new items go before it. ``None`` means the end."""
    if index is None:
        return None
    return next((n for n in current[index:] if n not in moving), None)


def is_enabled(path):
    directory, name = os.path.split(os.path.normpath(path))
    return name not in _load_meta(directory)["disabled"]


def set_enabled(paths, enabled):
    """Enable or disable items. A run of their folder skips disabled ones,
    and everything inside a disabled folder."""
    for path in paths:
        directory, name = os.path.split(os.path.normpath(path))
        meta = _load_meta(directory)
        meta["disabled"] = [n for n in meta["disabled"] if n != name]
        if not enabled:
            meta["disabled"].append(name)
        _save_meta(directory, meta)


# -- editing the tree -------------------------------------------------------


def _new_path(directory, name, ext):
    """Check a new item's name and return its path in ``directory``.
    ``ext`` is added unless the name ends with it; ``None`` for folders."""
    name = name.strip()
    if not name:
        raise ValueError("Please provide a name.")
    if "/" in name or "\\" in name:
        raise ValueError("Name can't contain path separators.")
    if ext and not name.lower().endswith(ext):
        name += ext
    path = os.path.join(directory, name)
    if os.path.exists(path):
        raise FileExistsError(f"Already exists: {name}")
    return path


def create_item(kind, directory, name, index=None):
    """Create a new ``kind`` item named ``name`` in ``directory`` and put it
    at ``index``, a position in the folder's order; ``None`` puts it last.
    Returns its path."""
    current = _ordered_names(directory)
    path = _new_path(directory, name, EXTENSIONS.get(kind))
    if kind == FOLDER:
        os.makedirs(path)
    elif kind in EXTENSIONS:
        with open(path, "w", encoding="utf-8"):
            pass
    else:
        raise ValueError(f"Unknown item kind: {kind}")
    _insert_order(directory, current, [os.path.basename(path)], _anchor(current, index, set()))
    return path


def create_data_item(kind, directory, name, selection, index=None):
    """Create a Joints, Skin or Mesh item from ``selection`` (long names),
    published as v001, at ``index`` as in :func:`create_item`. Raises,
    creating nothing, if the selection can't be published."""
    problems = items.selection_problems(kind, selection)
    if problems:
        raise ValueError(" ".join(problems))
    path = create_item(kind, directory, name, index)
    try:
        items.write_data(kind, path, selection)
        versions.publish(path)
    except Exception:
        delete_paths([path])
        raise
    return path


def create_file_item(kind, directory, name, target, index=None):
    """Create an Import or Export File item pointing to ``target``, at
    ``index`` as in :func:`create_item`. Raises, creating nothing, if
    ``target`` can't be used (e.g. a format Export can't write)."""
    items.check_target(kind, target)
    path = create_item(kind, directory, name, index)
    try:
        items.set_target(path, target)
    except Exception:
        delete_paths([path])
        raise
    return path


def create_selection_item(directory, name, selection, index=None):
    """Create a Selection item with one Selected entry holding the names in
    ``selection`` (none if it's empty), at ``index`` as in :func:`create_item`."""
    path = create_item(SELECTION, directory, name, index)
    items.write_entries(path, items.add_selected([], selection))
    return path


def default_name(kind, directory):
    """The name a new ``kind`` item starts with: the kind, with ``_2``,
    ``_3``... if an item in ``directory`` already has that name."""
    taken = set()
    for name in os.listdir(directory):
        taken |= {name.lower(), os.path.splitext(name)[0].lower()}
    name, n = kind, 2
    while name.lower() in taken:
        name, n = f"{kind}_{n}", n + 1
    return name


def rename_path(path, name):
    """Rename an item in place and return its new path. Files keep their
    extension, and the item keeps its place, disabled state and versions."""
    path = os.path.normpath(path)
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    directory, old = os.path.split(path)
    ext = "" if os.path.isdir(path) else os.path.splitext(old)[1]
    name = name.strip()
    if ext and name.lower().endswith(ext.lower()):
        name = name[: -len(ext)]
    if name + ext == old:
        return path
    if name.lower() + ext.lower() == old.lower():
        new = os.path.join(directory, name + ext)  # a case-only change
    else:
        new = _new_path(directory, name, ext or None)
    os.rename(path, new)
    versions.move_history(path, new)

    new_name = os.path.basename(new)
    meta = _load_meta(directory)
    if old in meta["order"] or old in meta["disabled"]:
        for key in meta:
            meta[key] = [new_name if n == old else n for n in meta[key]]
        _save_meta(directory, meta)
    return new


def _top_level(paths):
    """Normalized, de-duplicated ``paths`` minus any inside another of them."""
    srcs = list(dict.fromkeys(os.path.normpath(p) for p in paths))
    return [p for p in srcs if not any(p.startswith(o + os.sep) for o in srcs)]


def place(paths, directory, index):
    """Move ``paths`` into ``directory`` at ``index`` (a position in its
    order before the move; ``None`` is the end), in the given order. Items
    keep their disabled state and versions. Everything is checked before anything moves.
    Returns the new paths."""
    directory = os.path.normpath(directory)
    srcs = _top_level(paths)
    names = [os.path.basename(p) for p in srcs]
    if len(set(names)) != len(names):
        raise FileExistsError("Can't move two items with the same name into one folder.")
    for src in srcs:
        if not os.path.exists(src):
            raise FileNotFoundError(src)
        if directory == src or directory.startswith(src + os.sep):
            raise ValueError("Can't move a folder into itself.")
        if os.path.dirname(src) != directory and os.path.exists(os.path.join(directory, os.path.basename(src))):
            raise FileExistsError(f"Already exists there: {os.path.basename(src)}")

    current = _ordered_names(directory)
    anchor = _anchor(current, index, set(names))
    new_paths = []
    for src in srcs:
        new = os.path.join(directory, os.path.basename(src))
        if new != src:
            was_disabled = _forget(src)
            shutil.move(src, new)
            versions.move_history(src, new)
            if was_disabled:
                set_enabled([new], False)
        new_paths.append(new)
    _insert_order(directory, current, names, anchor)
    return new_paths


def _copy_name(directory, name, is_dir):
    """``name`` if it's free in ``directory``, else ``<name>_copy``,
    ``<name>_copy_2``... (before a file's extension)."""
    stem, ext = (name, "") if is_dir else os.path.splitext(name)
    candidate, n = name, 1
    while os.path.exists(os.path.join(directory, candidate)):
        candidate = f"{stem}_copy{'' if n == 1 else f'_{n}'}{ext}"
        n += 1
    return candidate


def paste(paths, directory, index=None):
    """Copy ``paths`` into ``directory`` at ``index`` (as in :func:`place`),
    in the given order. A name already taken there gets ``_copy`` added.
    Copies keep their disabled state and versions; a folder comes with
    everything in it. An Import or Export File copy points to the same file
    (files inside a copied folder point to their copies). Everything is
    checked before anything is copied. Returns the new paths."""
    directory = os.path.normpath(directory)
    srcs = _top_level(paths)
    for src in srcs:
        if not os.path.exists(src):
            raise FileNotFoundError(src)
        if directory == src or directory.startswith(src + os.sep):
            raise ValueError("Can't paste a folder into itself.")

    current = _ordered_names(directory)
    anchor = _anchor(current, index, set())
    new_paths = []
    for src in srcs:
        is_dir = os.path.isdir(src)
        new = os.path.join(directory, _copy_name(directory, os.path.basename(src), is_dir))
        if is_dir:
            shutil.copytree(src, new)
        else:
            shutil.copy2(src, new)
            versions.copy_history(src, new)
            if kind_of(src) in items.FILE_KINDS:
                _keep_target(src, new)
        if not is_enabled(src):
            set_enabled([new], False)
        new_paths.append(new)
    _insert_order(directory, current, [os.path.basename(p) for p in new_paths], anchor)
    return new_paths


def _keep_target(src, new):
    """Point the File item ``new``, copied from ``src``, to ``src``'s file:
    a path stored relative to ``src``'s folder doesn't hold in another one."""
    try:
        target = items.target(src)
    except ValueError:  # no file set yet: the copy has none either
        return
    items.set_target(new, target)


def delete_paths(paths):
    """Delete items and folders (with everything in them). If any is
    missing, nothing is deleted and FileNotFoundError is raised."""
    targets = _top_level(paths)
    for path in targets:
        if not os.path.exists(path):
            raise FileNotFoundError(path)
    for path in targets:
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
            versions.delete_history(path)
        _forget(path)


# -- recent folders ---------------------------------------------------------


def recent_folders():
    """Folders picked lately, newest first; ones that no longer exist are left out."""
    try:
        folders = json.loads(settings.get(SETTINGS_KEY, "recent_folders", "[]"))
    except (TypeError, ValueError):
        folders = []
    return [f for f in folders if isinstance(f, str) and os.path.isdir(f)]


def remember_folder(folder):
    """Put ``folder`` first in :func:`recent_folders`."""
    folder = os.path.normpath(folder)
    folders = [folder] + [f for f in recent_folders() if os.path.normcase(f) != os.path.normcase(folder)]
    settings.set(SETTINGS_KEY, "recent_folders", json.dumps(folders[:MAX_RECENT]))


# -- run --------------------------------------------------------------------

# Item statuses (Runner.status) and run results (Runner.run, continue_run).
RAN = "ran"
FAILED = "failed"
PAUSED = "paused"
DONE = "done"


def _sort_key(path, cache):
    """Where ``path`` sits in the tree: its index in each folder's order, top down."""
    key = []
    parts = os.path.normpath(path)
    while True:
        directory, name = os.path.split(parts)
        if not name or directory == parts:
            break
        if directory not in cache:
            cache[directory] = {n: i for i, n in enumerate(_ordered_names(directory))}
        key.append(cache[directory].get(name, len(cache[directory])))
        parts = directory
    return [os.path.splitdrive(parts)[0].lower()] + key[::-1]


def _folder_steps(folder):
    """The enabled runnable items and breakpoints under ``folder``, in order;
    disabled folders are skipped with everything in them."""
    steps = []
    for entry in scan(folder):
        if not entry.enabled:
            continue
        if entry.kind == FOLDER:
            steps.extend(_folder_steps(entry.path))
        elif entry.kind in items.RUNNABLE or entry.kind == BREAKPOINT:
            steps.append(entry.path)
    return steps


def steps_for(paths):
    """What running ``paths`` runs, in tree order. A selected folder brings
    its enabled items (even if it's disabled itself); a selected item runs
    even if disabled; a selected breakpoint is ignored; an item reached both
    ways runs once."""
    steps = []
    for path in _top_level(paths):
        kind = kind_of(path)
        if kind == FOLDER:
            steps.extend(_folder_steps(path))
        elif kind in items.RUNNABLE:
            steps.append(path)
    cache = {}
    return sorted(dict.fromkeys(steps), key=lambda p: _sort_key(p, cache))


def runs_a_folder(paths):
    """Whether running ``paths`` runs a whole folder."""
    return any(kind_of(path) == FOLDER for path in paths)


def scene_is_new():
    """Whether the scene is a fresh, untitled one with no changes."""
    return not cmds.file(query=True, sceneName=True) and not cmds.file(query=True, modified=True)


def start_new_scene():
    """Start a new scene, dropping any unsaved changes."""
    cmds.file(new=True, force=True)


class Runner:
    """Runs items and remembers how each one went, and where a run paused."""

    def __init__(self):
        self._status = {}
        self._remaining = []
        self.paused_at = None

    def status(self, path):
        """``(status, message)`` of ``path`` in the latest run: :data:`RAN`,
        :data:`FAILED` (with the error), :data:`PAUSED`, or ``None`` if it
        didn't run."""
        return self._status.get(os.path.normpath(path), (None, ""))

    def can_continue(self, path):
        return self.paused_at is not None and os.path.normpath(path) == self.paused_at

    def run(self, paths):
        """Run ``paths`` (see :func:`steps_for`) as one undo step. Clears
        the last run's statuses and pause first. Stops at the first failure
        or enabled breakpoint. Returns :data:`DONE`, :data:`FAILED` or
        :data:`PAUSED`; ``None`` when there's nothing to run (such as only
        breakpoints selected), which leaves the last run's pause alone."""
        if not paths:
            raise ValueError("Select items to run.")
        steps = steps_for(paths)
        if not steps:
            return None
        self._status = {}
        self._remaining = []
        self.paused_at = None
        return self._run(steps)

    def continue_run(self, path):
        """Carry on a run paused at the breakpoint ``path``, reading the
        files again. Returns as :meth:`run` does."""
        if not self.can_continue(path):
            raise ValueError("The run isn't paused at this breakpoint.")
        self._status[self.paused_at] = (RAN, "")
        self.paused_at = None
        steps, self._remaining = self._remaining, []
        return self._run(steps)

    def _run(self, steps):
        with undo_chunk("Kaiju Scripter Run"):
            for i, path in enumerate(steps):
                if kind_of(path) == BREAKPOINT:
                    self._status[path] = (PAUSED, "")
                    self.paused_at = path
                    self._remaining = steps[i + 1 :]
                    return PAUSED
                try:
                    items.run(path)
                except Exception as e:
                    sys.stderr.write(traceback.format_exc())
                    self._status[path] = (FAILED, f"{type(e).__name__}: {e}")
                    return FAILED
                self._status[path] = (RAN, "")
        return DONE
