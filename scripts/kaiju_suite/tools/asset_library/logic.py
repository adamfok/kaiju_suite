"""Asset Library: asset folders in one or more library folders. No Qt here.

An asset is a folder holding an ``asset.json`` (a Kaiju data file with its
type, tags and notes; its name is the folder's name) in this layout::

    hero/
      asset.json
      thumbnail.png   optional
      files/          source files (model, textures)
      build/          Assembler build folder
      publish/        finished rigs

The current asset is the one the ``ASSET`` environment variable points to,
so Assembler Scene and Output items under it store ``$ASSET/...`` paths.
It's remembered per user and set again by :func:`restore_current`.
"""

import json
import os
import re
from collections import namedtuple

from kaiju_suite.core import datafile, settings
from kaiju_suite.core.log import get_logger

log = get_logger(__name__)

KIND = "asset"
ASSET_FILE = "asset.json"
THUMBNAIL = "thumbnail.png"
FOLDERS = ("files", "build", "publish")
PUBLISH_EXTENSIONS = (".ma", ".mb", ".fbx")
VARIABLE = "ASSET"
SETTINGS_KEY = "asset_library"

# Folder names that work in paths on every platform.
_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]*$")


class Asset(namedtuple("Asset", "path name type tags notes")):
    __slots__ = ()

    @property
    def thumbnail(self):
        """The thumbnail image's path, or ``None`` if there's none."""
        path = os.path.join(self.path, THUMBNAIL)
        return path if os.path.isfile(path) else None


# -- assets ---------------------------------------------------------------------


def is_asset(folder):
    return os.path.isfile(os.path.join(folder, ASSET_FILE))


def _clean_tags(tags):
    return list(dict.fromkeys(tag.strip() for tag in tags or () if tag.strip()))


def read_asset(folder):
    """The :class:`Asset` in ``folder``; raises ``datafile.DataFormatError``
    or ``OSError`` if its ``asset.json`` can't be read."""
    data = datafile.read(os.path.join(folder, ASSET_FILE), KIND)
    if not isinstance(data, dict):
        raise datafile.DataFormatError(f"{ASSET_FILE} in {folder} holds no asset fields.")
    folder = os.path.normpath(folder)
    return Asset(
        folder,
        os.path.basename(folder),
        str(data.get("type", "")),
        _clean_tags(data.get("tags", [])),
        str(data.get("notes", "")),
    )


def _write(folder, asset_type, tags, notes):
    datafile.write(
        os.path.join(folder, ASSET_FILE),
        KIND,
        {"type": asset_type, "tags": _clean_tags(tags), "notes": notes},
    )
    return read_asset(folder)


def create_asset(library, name, asset_type="", tags=(), notes=""):
    """Make asset ``name`` in ``library`` with the folder layout; returns it."""
    if not _NAME.match(name or ""):
        raise ValueError(f"Asset name {name!r} can't be used: use letters, digits, _ and -.")
    if not os.path.isdir(library):
        raise FileNotFoundError(f"The library folder {library} doesn't exist.")
    folder = os.path.join(library, name)
    if os.path.exists(folder):
        raise ValueError(f"There's already a folder called {name} in {library}.")
    for sub in FOLDERS:
        os.makedirs(os.path.join(folder, sub))
    return _write(folder, asset_type, tags, notes)


def update_asset(folder, asset_type=None, tags=None, notes=None):
    """Change the given fields of the asset in ``folder``; returns it."""
    asset = read_asset(folder)
    return _write(
        folder,
        asset.type if asset_type is None else asset_type,
        asset.tags if tags is None else tags,
        asset.notes if notes is None else notes,
    )


def scan(library):
    """The assets in ``library``, sorted by name (ignoring case). Folders
    without an ``asset.json`` are left out, unreadable ones logged."""
    if not os.path.isdir(library):
        return []
    found = []
    for name in os.listdir(library):
        folder = os.path.join(library, name)
        if not is_asset(folder):
            continue
        try:
            found.append(read_asset(folder))
        except (OSError, ValueError) as e:
            log.warning("Skipped asset %s: %s", folder, e)
    return sorted(found, key=lambda a: a.name.lower())


# -- filtering ------------------------------------------------------------------


def filter_assets(assets, text="", asset_type=None, tag=None):
    """The ``assets`` whose name, tags or notes contain ``text`` (ignoring
    case), of type ``asset_type`` and with tag ``tag`` when given."""
    text = text.strip().lower()

    def keep(asset):
        if asset_type and asset.type != asset_type:
            return False
        if tag and tag not in asset.tags:
            return False
        if text:
            haystack = " ".join([asset.name, asset.notes, *asset.tags]).lower()
            return text in haystack
        return True

    return [asset for asset in assets if keep(asset)]


def types_in_use(assets):
    return sorted({asset.type for asset in assets if asset.type})


def tags_in_use(assets):
    return sorted({tag for asset in assets for tag in asset.tags})


# -- folders in an asset --------------------------------------------------------


def build_folder(folder):
    return os.path.join(folder, "build")


def has_build(folder):
    """Whether the asset's build folder exists and has something in it."""
    build = build_folder(folder)
    return os.path.isdir(build) and bool(os.listdir(build))


def latest_publish(folder):
    """The newest ``.ma``, ``.mb`` or ``.fbx`` file in the asset's
    ``publish/`` folder, or ``None`` if there's none."""
    publish = os.path.join(folder, "publish")
    if not os.path.isdir(publish):
        return None
    files = [
        os.path.join(publish, name)
        for name in os.listdir(publish)
        if name.lower().endswith(PUBLISH_EXTENSIONS) and os.path.isfile(os.path.join(publish, name))
    ]
    return max(files, key=os.path.getmtime, default=None)


# -- libraries ------------------------------------------------------------------


def libraries():
    """The user's library folders, in the order they were added."""
    try:
        found = json.loads(settings.get(SETTINGS_KEY, "libraries", "[]"))
    except ValueError:
        return []
    return [path for path in found if isinstance(path, str)] if isinstance(found, list) else []


def _save_libraries(paths):
    settings.set(SETTINGS_KEY, "libraries", json.dumps(paths))


def _same(a, b):
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def add_library(path):
    current = libraries()
    if not any(_same(path, p) for p in current):
        _save_libraries(current + [os.path.normpath(path)])


def remove_library(path):
    _save_libraries([p for p in libraries() if not _same(path, p)])


# -- the current asset ----------------------------------------------------------


def set_current(folder):
    """Make the asset in ``folder`` current: set ``ASSET`` to it for this
    session and remember it. Returns the asset."""
    if not is_asset(folder):
        raise ValueError(f"{folder} isn't an asset (it has no {ASSET_FILE}).")
    asset = read_asset(folder)
    os.environ[VARIABLE] = asset.path
    settings.set(SETTINGS_KEY, "current_asset", asset.path)
    return asset


def current():
    """The remembered current asset, or ``None`` if there's none or it's gone."""
    folder = settings.get(SETTINGS_KEY, "current_asset", "")
    if not folder or not is_asset(folder):
        return None
    try:
        return read_asset(folder)
    except (OSError, ValueError):
        return None


def restore_current():
    """Set ``ASSET`` to the remembered asset again (e.g. when Maya starts).
    Forgets it, leaving ``ASSET`` alone, if it's gone. Returns the asset or ``None``."""
    asset = current()
    if asset is None:
        settings.remove(SETTINGS_KEY, "current_asset")
        return None
    os.environ[VARIABLE] = asset.path
    return asset


def clear_current():
    """Forget the current asset and unset ``ASSET``."""
    settings.remove(SETTINGS_KEY, "current_asset")
    os.environ.pop(VARIABLE, None)
