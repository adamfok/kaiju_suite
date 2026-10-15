"""Version history for Kaiju Scripter items, kept next to them.

An item's versions live in ``<folder>/.scripter/versions/<item name>/``
as ``v001<ext>``, ``v002<ext>``... The item itself keeps its name and is
always the working copy; Publish copies it in as the next version and
Restore copies a version back over it. Beside the versions, ``base`` holds
the number of the version the item was last published as or restored
from (so the tree can show ``v002*`` once it's edited), and
``descriptions.json`` what each version changed, as ``{"3": "Fixed the knee"}``.

Scripts and data items (Joints, Skin, Mesh, NurbsCurve, Animation) are versioned. No Qt here.
"""

import filecmp
import json
import os
import re
import shutil
from dataclasses import dataclass

# Everything Kaiju Scripter keeps in a folder goes in here (``logic`` uses it too).
HIDDEN_DIR = ".scripter"
VERSIONS_DIR = "versions"
BASE_FILE = "base"
DESCRIPTIONS_FILE = "descriptions.json"
# Scripts, and Joints, Skin, Mesh, NurbsCurve, Animation and Pose items (see .items).
VERSIONED_EXTENSIONS = (".py", ".jnt", ".skin", ".mesh", ".curve", ".anim", ".pose")

NO_DESCRIPTION = "(no description)"

_VERSION_RE = re.compile(r"^v(\d+)$")


@dataclass
class Version:
    number: int
    path: str
    mtime: float
    description: str


def is_versioned(path):
    return os.path.isfile(path) and os.path.splitext(path)[1].lower() in VERSIONED_EXTENSIONS


def history_dir(path):
    directory, name = os.path.split(os.path.normpath(path))
    return os.path.join(directory, HIDDEN_DIR, VERSIONS_DIR, name)


def _descriptions(history):
    try:
        with open(os.path.join(history, DESCRIPTIONS_FILE), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def list_versions(path):
    """Every version of ``path``, oldest first."""
    history = history_dir(path)
    if not os.path.isdir(history):
        return []
    descriptions = _descriptions(history)
    found = []
    for name in os.listdir(history):
        stem, _ext = os.path.splitext(name)
        match = _VERSION_RE.match(stem)
        if not match:
            continue
        number = int(match.group(1))
        version_path = os.path.join(history, name)
        description = descriptions.get(str(number)) or NO_DESCRIPTION
        found.append(Version(number, version_path, os.path.getmtime(version_path), description))
    return sorted(found, key=lambda v: v.number)


def count(path):
    return len(list_versions(path))


def _base(path, found):
    """The version ``path`` was last published as or restored from."""
    try:
        with open(os.path.join(history_dir(path), BASE_FILE), encoding="utf-8") as f:
            number = int(f.read().strip())
        return next(v for v in found if v.number == number)
    except (OSError, ValueError, StopIteration):
        return found[-1]


def _set_base(path, number):
    with open(os.path.join(history_dir(path), BASE_FILE), "w", encoding="utf-8") as f:
        f.write(str(number))


def _modified(path, base):
    return not filecmp.cmp(path, base.path, shallow=False)


def label(path):
    """The Version column: ``v002``, ``v002*`` when edited since, or blank
    when never published."""
    found = list_versions(path)
    if not found:
        return ""
    base = _base(path, found)
    return f"v{base.number:03d}" + ("*" if _modified(path, base) else "")


def _save(path, description):
    """Copy ``path`` in as its next version and return the number."""
    found = list_versions(path)
    number = found[-1].number + 1 if found else 1
    history = history_dir(path)
    os.makedirs(history, exist_ok=True)
    shutil.copy2(path, os.path.join(history, f"v{number:03d}{os.path.splitext(path)[1]}"))
    descriptions = _descriptions(history)
    if description:
        descriptions[str(number)] = description
        with open(os.path.join(history, DESCRIPTIONS_FILE), "w", encoding="utf-8") as f:
            json.dump(descriptions, f, indent=2)
    return number


def publish(path, description=""):
    """Save ``path`` as its next version, described as ``description``.
    Returns the version number. Raises if nothing changed since its version."""
    if not is_versioned(path):
        raise ValueError(f"Not something Kaiju Scripter versions: {os.path.basename(path)}")
    found = list_versions(path)
    if found:
        base = _base(path, found)
        if not _modified(path, base):
            raise ValueError(f"No changes to publish since v{base.number:03d}.")
    number = _save(path, description.strip())
    _set_base(path, number)
    return number


def unchanged_since(path, content=None):
    """The number of the version ``path`` is at, if publishing now would only
    save it again (``path`` as it is, or ``content`` bytes in its place);
    otherwise ``None``. Check it before asking for a description."""
    found = list_versions(path)
    if not found:
        return None
    base = _base(path, found)
    if content is None:
        return None if _modified(path, base) else base.number
    with open(base.path, "rb") as f:
        return base.number if f.read() == content else None


def has_unpublished(path):
    """Whether ``path`` was edited since the version it's at."""
    found = list_versions(path)
    return bool(found) and _modified(path, _base(path, found))


def is_latest(path):
    """Whether ``path`` is at (or based on) its newest version; true when it
    has none."""
    found = list_versions(path)
    return not found or _base(path, found).number == found[-1].number


def restore(path, number):
    """Put version ``number`` back as ``path``. Unpublished edits are lost:
    the caller asks first (see :func:`has_unpublished`)."""
    found = list_versions(path)
    version = next((v for v in found if v.number == number), None)
    if version is None:
        raise ValueError(f"{os.path.basename(path)} has no version {number}.")
    shutil.copy2(version.path, path)
    _set_base(path, number)


def move_history(src, dst):
    """Move ``src``'s history to go with it to ``dst``."""
    old, new = history_dir(src), history_dir(dst)
    if not os.path.isdir(old) or old == new:
        return
    if os.path.isdir(new):
        shutil.rmtree(new)
    os.makedirs(os.path.dirname(new), exist_ok=True)
    shutil.move(old, new)


def copy_history(src, dst):
    """Give ``dst`` a copy of ``src``'s history, replacing any it had."""
    old, new = history_dir(src), history_dir(dst)
    if not os.path.isdir(old) or old == new:
        return
    if os.path.isdir(new):
        shutil.rmtree(new)
    shutil.copytree(old, new)


def delete_history(path):
    history = history_dir(path)
    if os.path.isdir(history):
        shutil.rmtree(history)
