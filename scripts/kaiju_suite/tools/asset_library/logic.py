"""Asset Library: asset folders in one or more library folders. No Qt here.

An asset is a folder holding an ``asset.json`` (a Kaiju data file that marks
the folder as an asset; its name is the folder's name) in this layout::

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

import os
import re
import tempfile
from collections import namedtuple

from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite import registry
from kaiju_suite.core import datafile, settings
from kaiju_suite.core.log import get_logger

log = get_logger(__name__)

KIND = "asset"
ASSET_FILE = "asset.json"
THUMBNAIL = "thumbnail.png"
# Thumbnails fit in a square this many pixels wide.
THUMBNAIL_SIZE = 256
FOLDERS = ("files", "build", "publish")
PUBLISH_EXTENSIONS = (".ma", ".mb", ".fbx")
VARIABLE = "ASSET"
SETTINGS_KEY = "asset_library"

# Folder names that work in paths on every platform.
_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]*$")


class Asset(namedtuple("Asset", "path name")):
    __slots__ = ()

    @property
    def thumbnail(self):
        """The thumbnail image's path, or ``None`` if there's none."""
        path = os.path.join(self.path, THUMBNAIL)
        return path if os.path.isfile(path) else None


# -- assets ---------------------------------------------------------------------


def is_asset(folder):
    return os.path.isfile(os.path.join(folder, ASSET_FILE))


def read_asset(folder):
    """The :class:`Asset` in ``folder``; raises ``datafile.DataFormatError``
    or ``OSError`` if its ``asset.json`` can't be read."""
    data = datafile.read(os.path.join(folder, ASSET_FILE), KIND)
    if not isinstance(data, dict):
        raise datafile.DataFormatError(f"{ASSET_FILE} in {folder} holds no asset fields.")
    folder = os.path.normpath(folder)
    return Asset(folder, os.path.basename(folder))


def create_asset(library, name):
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
    datafile.write(os.path.join(folder, ASSET_FILE), KIND, {})
    return read_asset(folder)


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


def filter_assets(assets, text=""):
    """The ``assets`` whose name contains ``text``, ignoring case."""
    text = text.strip().lower()
    return [asset for asset in assets if text in asset.name.lower()]


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


def _publish_or_raise(folder):
    path = latest_publish(folder)
    if path is None:
        raise LookupError(f"{os.path.basename(os.path.normpath(folder))} has nothing published (no .ma, .mb or .fbx in publish/).")
    return path


def import_asset(folder):
    """Import the asset's latest published file; returns the new nodes."""
    return cmds.file(_publish_or_raise(folder), i=True, returnNewNodes=True)


def reference_asset(folder):
    """Reference the asset's latest published file under a namespace named
    after the asset (Maya numbers it if it's taken); returns the file."""
    path = _publish_or_raise(folder)
    namespace = os.path.basename(os.path.normpath(folder))
    return cmds.file(path, reference=True, namespace=namespace)


def open_asset(folder):
    """Open the asset's latest published file, dropping unsaved changes:
    ask the user first."""
    path = _publish_or_raise(folder)
    cmds.file(path, open=True, force=True)
    return path


# -- thumbnails -----------------------------------------------------------------


def set_thumbnail_from_file(folder, image_path):
    """Save the image at ``image_path`` as the asset's thumbnail: a PNG
    scaled down (never up) to fit :data:`THUMBNAIL_SIZE`. Returns its path.
    The old thumbnail is kept if the image can't be read."""
    if not is_asset(folder):
        raise ValueError(f"{folder} isn't an asset (it has no {ASSET_FILE}).")
    image = om.MImage()
    try:
        image.readFromFile(image_path)
    except RuntimeError as e:
        raise ValueError(f"Can't read {os.path.basename(image_path)} as an image.") from e
    width, height = image.getSize()
    if width > THUMBNAIL_SIZE or height > THUMBNAIL_SIZE:
        image.resize(THUMBNAIL_SIZE, THUMBNAIL_SIZE, True)
    target = os.path.join(folder, THUMBNAIL)
    partial = target + ".part"
    image.writeToFile(partial, "png")
    os.replace(partial, target)
    return target


def capture_thumbnail(folder):
    """Save the active viewport at the current frame as the asset's
    thumbnail. Returns its path. Needs Maya's UI (a viewport)."""
    if not is_asset(folder):
        raise ValueError(f"{folder} isn't an asset (it has no {ASSET_FILE}).")
    handle, grab = tempfile.mkstemp(prefix="kaiju_thumbnail_", suffix=".png")
    os.close(handle)
    try:
        cmds.playblast(
            frame=[cmds.currentTime(query=True)],
            format="image",
            compression="png",
            completeFilename=grab,
            widthHeight=(THUMBNAIL_SIZE, THUMBNAIL_SIZE),
            percent=100,
            viewer=False,
            showOrnaments=False,
            offScreen=True,
            forceOverwrite=True,
        )
        return set_thumbnail_from_file(folder, grab)
    finally:
        if os.path.exists(grab):
            os.remove(grab)


# -- the library ---------------------------------------------------------------


def library():
    """The library folder in use, or ``""`` if none is set or it's gone."""
    path = settings.get(SETTINGS_KEY, "library", "")
    return path if path and os.path.isdir(path) else ""


def set_library(path):
    """Use the folder at ``path`` as the library from now on."""
    if not os.path.isdir(path):
        raise FileNotFoundError(f"The library folder {path} doesn't exist.")
    settings.set(SETTINGS_KEY, "library", os.path.normpath(path))


def create_library(parent, name):
    """Make an empty library folder ``name`` in ``parent`` and use it.
    Returns its path."""
    if not _NAME.match(name or ""):
        raise ValueError(f"Library name {name!r} can't be used: use letters, digits, _ and -.")
    if not os.path.isdir(parent):
        raise FileNotFoundError(f"The folder {parent} doesn't exist.")
    folder = os.path.normpath(os.path.join(parent, name))
    if os.path.exists(folder):
        raise ValueError(f"There's already a folder called {name} in {parent}.")
    os.makedirs(folder)
    set_library(folder)
    return folder


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


# -- the Assembler --------------------------------------------------------------


def open_in_assembler(folder):
    """Make the asset in ``folder`` current and open the Assembler on its
    build folder (made if it's missing). Returns the asset."""
    tool = registry.find("Assembler")
    if tool is None or not callable(tool.get("open")):
        raise LookupError("The Assembler isn't available, so the build can't be opened.")
    asset = set_current(folder)
    build = build_folder(asset.path)
    os.makedirs(build, exist_ok=True)
    tool["open"](build)
    return asset
