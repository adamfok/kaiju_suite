"""Assembler logic: browse, order, and build a folder of products.

Everything type-specific (which files are listed, how each one runs) lives
in :mod:`.products`; this module only deals with the tree and the build.
No Qt here, so it can be scripted and tested headless. Functions raise on
bad input instead of warning; the widget decides how to tell the user.
"""

import json
import os
import shutil
import time
import traceback
from dataclasses import dataclass, field

from kaiju_suite.core.log import get_logger
from kaiju_suite.core.undo import undo_chunk
from kaiju_suite.tools.assembler import runlog, versions
from kaiju_suite.tools.assembler.products import Product, ext_of, product_for

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
        return "" if self.is_dir else ext_of(self.name)

    @property
    def label(self):
        """Name shown in the tree: files lose their extension."""
        return self.name if self.is_dir else os.path.splitext(self.name)[0]

    @property
    def type_label(self):
        """Product shown next to the label (its :meth:`~.products.Product.type_name`
        for this item, e.g. ``Simple IK`` for a Rig Module). The extension is added only when
        the product has several, e.g. ``Script(.py)`` but ``Mesh``; blank for
        folders. A product with ``columns_text`` shows that instead."""
        if self.is_dir or self.product is None:
            return ""
        if self.product.columns_text is not None:
            return self.product.columns_text
        name = self.product.type_name(self.path)
        if len(self.product.extensions) > 1:
            return f"{name}({self.ext})"
        return name

    @property
    def version_label(self):
        """Fixed text for the Version column, or ``None`` to leave it to the
        version history (see ``versions.tree_label``)."""
        if self.is_dir or self.product is None:
            return None
        return self.product.columns_text


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


def utility_for(product):
    """The TOOL dict of ``product``'s utility, which double-click opens, or
    ``None`` if it has none (or that tool isn't installed)."""
    if not product.utility:
        return None
    from kaiju_suite import registry  # lazily: the registry imports every tool

    return registry.find(product.utility)


def open_utility(product, path):
    """Double-click: open ``product``'s utility. A tool that edits files (its
    TOOL dict has ``"open": fn(path)``) is opened on ``path``; any other is
    just launched."""
    tool = utility_for(product)
    if tool is None:
        raise LookupError(f"{product.utility} isn't installed.")
    if "open" in tool:
        tool["open"](path)
    else:
        tool["launch"]()



def has_info(product):
    """Whether ``product``'s items get right-click Info: those with an info
    window (:meth:`Product.panel`)."""
    return type(product).panel is not Product.panel


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
    versions.delete_history(path)
    runlog.delete(path)
    _forget(path)


def rename_path(path, name):
    """Rename an item or folder in place and return its new path.

    Files keep their extension, which is added unless ``name`` already ends
    with it. The item keeps its place in the folder's order and its disabled
    state, and a file keeps its versions. A case-only change is allowed.
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
    versions.move_history(path, new)
    runlog.move(path, new)

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
            versions.move_history(src, new)
            runlog.move(src, new)
            if was_disabled:
                set_enabled(new, False)
        new_paths.append(new)

    _insert_order(directory, current, names, anchor)
    return new_paths


def paste_paths(paths, directory, index):
    """Copy ``paths`` into ``directory`` and put the copies at ``index``.

    Works like :func:`place` but leaves the originals alone. A copy whose
    name is taken gets ``_copy`` (then ``_copy2``, ...) before its extension.
    Copies keep their disabled state and versions, and a copied folder keeps
    its contents' order, disabled states and versions. Everything is checked
    before anything is copied. Returns the new paths.
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
        name = free_name(os.path.basename(src), taken)
        taken.add(name.lower())
        names.append(name)

    new_paths = []
    for src, name in zip(srcs, names):
        new = os.path.join(directory, name)
        if os.path.isdir(src):
            shutil.copytree(src, new)
        else:
            shutil.copy2(src, new)
        versions.copy_history(src, new)
        if not is_enabled(src):
            set_enabled(new, False)
        new_paths.append(new)

    _insert_order(directory, current, names, anchor)
    return new_paths


def _top_level(paths):
    """Normalized, de-duplicated ``paths`` minus any inside another of them."""
    srcs = list(dict.fromkeys(os.path.normpath(p) for p in paths))
    return [p for p in srcs if not any(p.startswith(o + os.sep) for o in srcs)]


def free_name(name, taken):
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


def item_names(directory):
    """Names of the items :func:`scan` shows in ``directory``, in its order."""
    return _ordered_names(directory)


def set_layout(directory, order, disabled):
    """Save exactly ``order`` as ``directory``'s order and ``disabled`` as its disabled items."""
    _save_meta(directory, {"order": list(order), "disabled": list(disabled)})


def append_to_order(directory, names):
    """Put ``names``, already in ``directory``, last in its order, in the given order."""
    _insert_order(directory, _ordered_names(directory), list(names), None)


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
WARNING = "warning"  # ran, but logged warnings (a skipped missing node, say)
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

    Each step's log (see :mod:`.runlog`) is saved next to it, failed or not.

    ``on_status(path, status)``, if given, is called with :data:`RUNNING`
    before each step and, after it, :data:`ERROR` if it failed,
    :data:`WARNING` if it logged warnings or errors, else :data:`SUCCESS`.
    Steps after a failure get no call.
    """
    paths = list(paths)
    report = on_status or (lambda path, status: None)
    with undo_chunk("Assembler"):
        for path in paths:
            report(path, RUNNING)
            product = product_for(path)
            status, failure, start = SUCCESS, None, time.perf_counter()
            with runlog.capture() as run:
                try:
                    if product is None or not product.runnable:
                        raise ValueError("Not something the Assembler can run.")
                    message = product.run(path)
                    if isinstance(message, str):
                        run.info(message)
                except Exception as e:
                    run.error(traceback.format_exc())
                    status, failure = ERROR, e
            if status == SUCCESS and run.has_problems:
                status = WARNING
            _save_log(path, run, status, product, time.perf_counter() - start)
            report(path, status)
            if failure is not None:
                raise StepError(path, failure) from failure
    return paths


def _save_log(path, run, status, product, seconds):
    try:
        runlog.save(path, run, status, product.type_name(path) if product else "Item", seconds)
    except OSError:
        log.exception("Couldn't save the run log of %s", path)


def run_folder(folder):
    """Run every enabled item under ``folder``; see :func:`run_steps`."""
    return run_steps(collect_steps(folder))
