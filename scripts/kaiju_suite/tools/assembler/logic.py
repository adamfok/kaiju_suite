"""Assembler logic: browse, order, and build a folder of products.

Everything type-specific (which files are listed, how each one runs) lives
in :mod:`.products`; this module only deals with the tree and the build.
No Qt here, so it can be scripted and tested headless. Functions raise on
bad input instead of warning; the widget decides how to tell the user.
"""

import json
import os
import shutil
from dataclasses import dataclass, field

from kaiju_suite.core.log import get_logger
from kaiju_suite.core.undo import undo_chunk
from kaiju_suite.tools.assembler.products import product_for

log = get_logger(__name__)

SKIP_DIRS = ("__pycache__",)

# Hidden file in each snippet folder holding the custom order and the
# disabled items, by name. It travels with the folder; scan() skips it.
META_FILE = ".assembler.json"


@dataclass
class Entry:
    name: str
    path: str
    is_dir: bool
    children: list = field(default_factory=list)
    enabled: bool = True
    product: object = None

    @property
    def ext(self):
        return "" if self.is_dir else os.path.splitext(self.name)[1].lower()

    @property
    def label(self):
        """Name shown in the tree: files lose their extension."""
        return self.name if self.is_dir else os.path.splitext(self.name)[0]

    @property
    def type_label(self):
        """Product and extension shown next to the label, e.g. ``Script(.py)``;
        blank for folders."""
        return "" if self.is_dir or self.product is None else f"{self.product.name}({self.ext})"


def ext_of(path):
    return os.path.splitext(path)[1].lower()


def scan(root):
    """Return the product tree under ``root`` as a list of :class:`Entry`.

    Entries follow the folder's saved order; anything not in it comes after,
    folders first, then files, each sorted by name. Hidden entries and
    ``__pycache__`` are skipped, and so are files no product claims; empty
    folders are kept so items can be dropped into them.
    """
    meta = _load_meta(root)
    disabled = set(meta["disabled"])
    entries = []
    for name in _ordered_names(root, meta):
        path = os.path.join(root, name)
        product = product_for(path)
        if os.path.isdir(path):
            entries.append(Entry(name, path, True, scan(path), enabled=name not in disabled, product=product))
        else:
            entries.append(Entry(name, path, False, enabled=name not in disabled, product=product))
    return entries


def _listed_names(root):
    """Names scan() shows in ``root``, in the default order."""
    try:
        names = os.listdir(root)
    except OSError:
        log.exception("Cannot list %s", root)
        return []

    dirs, files = [], []
    for name in sorted(names, key=str.lower):
        if name.startswith("."):
            continue
        path = os.path.join(root, name)
        if os.path.isdir(path):
            if name not in SKIP_DIRS:
                dirs.append(name)
        elif product_for(path) is not None:
            files.append(name)
    return dirs + files


def _ordered_names(root, meta=None):
    names = _listed_names(root)
    present = set(names)
    ordered = [n for n in (meta or _load_meta(root))["order"] if n in present]
    seen = set(ordered)
    return ordered + [n for n in names if n not in seen]


# -- folder metadata --------------------------------------------------------


def _load_meta(directory):
    meta = {"order": [], "disabled": []}
    path = os.path.join(directory, META_FILE)
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
    path = os.path.join(directory, META_FILE)
    if not meta["order"] and not meta["disabled"]:
        if os.path.isfile(path):
            os.remove(path)
        return
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def _forget(path):
    """Drop ``path`` from its folder's metadata. Returns whether it was disabled."""
    directory, name = os.path.split(os.path.normpath(path))
    meta = _load_meta(directory)
    was_disabled = name in meta["disabled"]
    if was_disabled or name in meta["order"]:
        meta["order"] = [n for n in meta["order"] if n != name]
        meta["disabled"] = [n for n in meta["disabled"] if n != name]
        _save_meta(directory, meta)
    return was_disabled


def is_enabled(path):
    directory, name = os.path.split(os.path.normpath(path))
    return name not in _load_meta(directory)["disabled"]


def set_enabled(path, enabled):
    """Enable or disable an item or folder. :func:`run_folder` skips disabled
    ones, and everything inside a disabled folder."""
    directory, name = os.path.split(os.path.normpath(path))
    meta = _load_meta(directory)
    meta["disabled"] = [n for n in meta["disabled"] if n != name]
    if not enabled:
        meta["disabled"].append(name)
    _save_meta(directory, meta)


def matches(name, text):
    """Case-insensitive search rule used by the filter box."""
    return text.lower() in name.lower()


def delete_path(path):
    if os.path.isfile(path):
        os.remove(path)
    elif os.path.isdir(path):
        shutil.rmtree(path)
    else:
        raise FileNotFoundError(path)
    _forget(path)


def rename_path(path, name):
    """Rename an item or folder in place and return its new path.

    Files keep their extension, which is added unless ``name`` already ends
    with it. The item keeps its place in the folder's order and its disabled
    state. A case-only change is allowed.
    """
    path = os.path.normpath(path)
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    directory, old = os.path.split(path)
    name = name.strip()
    if not name:
        raise ValueError("Please provide a name.")
    if "/" in name or "\\" in name:
        raise ValueError("Name can't contain path separators.")
    ext = "" if os.path.isdir(path) else os.path.splitext(old)[1]
    if ext and not name.lower().endswith(ext.lower()):
        name += ext
    if name == old:
        return path
    new = os.path.join(directory, name)
    if os.path.exists(new) and name.lower() != old.lower():
        raise FileExistsError(f"Already exists: {name}")
    os.rename(path, new)

    meta = _load_meta(directory)
    if old in meta["order"] or old in meta["disabled"]:
        for key in meta:
            meta[key] = [name if n == old else n for n in meta[key]]
        _save_meta(directory, meta)
    return new


def _check_move(src, target_dir):
    if target_dir == src or target_dir.startswith(src + os.sep):
        raise ValueError("Cannot move a folder into itself.")
    if os.path.dirname(src) != target_dir and os.path.exists(os.path.join(target_dir, os.path.basename(src))):
        raise FileExistsError(f"Already exists at destination: {os.path.basename(src)}")


def move_path(src, target):
    """Move ``src`` into ``target`` (a folder, or a file whose folder is used).

    Returns the new path, or ``src`` unchanged if it's already there.
    """
    src = os.path.normpath(src)
    target_dir = os.path.normpath(target if os.path.isdir(target) else os.path.dirname(target))
    _check_move(src, target_dir)
    if os.path.dirname(src) == target_dir:
        return src
    return place([src], target_dir, None)[0]


def place(paths, directory, index):
    """Move ``paths`` into ``directory`` and put them at ``index``, in the given order.

    ``index`` is a position in the folder's current order, counted before the
    move (so "below the 3rd item" is 3); ``None`` means the end. Items inside
    another moved folder ride along with it. Everything is checked before
    anything moves. Returns the new paths.
    """
    directory = os.path.normpath(directory)
    srcs = _top_level(paths)

    names = [os.path.basename(p) for p in srcs]
    if len(set(names)) != len(names):
        raise FileExistsError("Can't move two items with the same name into one folder.")
    for src in srcs:
        if not os.path.exists(src):
            raise FileNotFoundError(src)
        _check_move(src, directory)

    current = _ordered_names(directory)
    anchor = _anchor(current, index, set(names))

    new_paths = []
    for src in srcs:
        new = os.path.join(directory, os.path.basename(src))
        if new != src:
            was_disabled = _forget(src)
            shutil.move(src, new)
            if was_disabled:
                set_enabled(new, False)
        new_paths.append(new)

    _insert_order(directory, current, names, anchor)
    return new_paths


def paste_paths(paths, directory, index):
    """Copy ``paths`` into ``directory`` and put the copies at ``index``.

    Works like :func:`place` but leaves the originals alone. A copy whose
    name is taken gets ``_copy`` (then ``_copy2``, ...) before its extension.
    Copies keep their disabled state, and a copied folder keeps its contents'
    order and disabled states. Everything is checked before anything is
    copied. Returns the new paths.
    """
    directory = os.path.normpath(directory)
    srcs = _top_level(paths)
    for src in srcs:
        if not os.path.exists(src):
            raise FileNotFoundError(src)
        if os.path.isdir(src) and (directory == src or directory.startswith(src + os.sep)):
            raise ValueError("Cannot paste a folder into itself.")

    current = _ordered_names(directory)
    anchor = _anchor(current, index, set())

    names, taken = [], {n.lower() for n in os.listdir(directory)}
    for src in srcs:
        name = _free_name(os.path.basename(src), taken)
        taken.add(name.lower())
        names.append(name)

    new_paths = []
    for src, name in zip(srcs, names):
        new = os.path.join(directory, name)
        if os.path.isdir(src):
            shutil.copytree(src, new)
        else:
            shutil.copy2(src, new)
        if not is_enabled(src):
            set_enabled(new, False)
        new_paths.append(new)

    _insert_order(directory, current, names, anchor)
    return new_paths


def _top_level(paths):
    """Normalized, de-duplicated ``paths`` minus any inside another of them."""
    srcs = list(dict.fromkeys(os.path.normpath(p) for p in paths))
    return [p for p in srcs if not any(p.startswith(o + os.sep) for o in srcs)]


def _free_name(name, taken):
    """``name``, or ``name_copy``, ``name_copy2``... if it's in ``taken`` (lowercase)."""
    if name.lower() not in taken:
        return name
    stem, ext = os.path.splitext(name)
    candidate, n = f"{stem}_copy{ext}", 2
    while candidate.lower() in taken:
        candidate, n = f"{stem}_copy{n}{ext}", n + 1
    return candidate


def _anchor(current, index, moving):
    """The first name at or after ``index`` in ``current`` that isn't moving;
    new items go before it. ``None`` means the end."""
    if index is None:
        return None
    return next((n for n in current[index:] if n not in moving), None)


def _insert_order(directory, current, names, anchor):
    """Save ``directory``'s order as ``current`` with ``names`` before ``anchor``."""
    moving = set(names)
    order = [n for n in current if n not in moving]
    at = order.index(anchor) if anchor is not None else len(order)
    order[at:at] = names
    meta = _load_meta(directory)
    meta["order"] = order
    _save_meta(directory, meta)


# Step statuses passed to run_steps(on_status=...).
RUNNING = "running"
SUCCESS = "success"
ERROR = "error"


class StepError(RuntimeError):
    """A step in a build failed; ``path`` says which one."""

    def __init__(self, path, error):
        super().__init__(f"{os.path.basename(path)}: {error}")
        self.path = path
        self.error = error


def collect_steps(folder):
    """Enabled runnable items under ``folder``, recursively, in display order.

    Disabled subfolders are skipped with everything in them. ``folder``
    itself is collected even if disabled, since it was asked for directly.
    """
    paths = []
    for entry in scan(folder):
        if entry.is_dir:
            if entry.enabled:
                paths.extend(collect_steps(entry.path))
        elif entry.enabled and entry.product is not None and entry.product.runnable:
            paths.append(entry.path)
    return paths


def run_steps(paths, on_status=None):
    """Run items in order as one undo step, whether enabled or not.

    Each item is run by its product (scripts execute, scenes import). Stops
    at the first failure and raises :class:`StepError`; steps that already
    ran stay applied. One undo reverts them, unless a scene was imported:
    Maya flushes undo on import. Returns ``paths``.

    ``on_status(path, status)``, if given, is called with :data:`RUNNING`
    before each step and :data:`SUCCESS` or :data:`ERROR` after it. Steps
    after a failure get no call.
    """
    paths = list(paths)
    report = on_status or (lambda path, status: None)
    with undo_chunk("Assembler"):
        for path in paths:
            report(path, RUNNING)
            try:
                product = product_for(path)
                if product is None or not product.runnable:
                    raise ValueError("Not something the Assembler can run.")
                product.run(path)
            except Exception as e:
                report(path, ERROR)
                raise StepError(path, e) from e
            report(path, SUCCESS)
    return paths


def run_folder(folder):
    """Run every enabled item under ``folder``; see :func:`run_steps`."""
    return run_steps(collect_steps(folder))
