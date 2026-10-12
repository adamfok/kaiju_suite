"""Numbered publishes: a folder of saved versions, a build record for each,
and a pointer to the latest one. No Maya or Qt here.

A publish folder (e.g. an asset rig's ``publish/<rig>/``) looks like::

    publish/puppet/
      hero_puppet_v001.ma     the files, never overwritten
      hero_puppet_v001.json   v001's build record
      hero_puppet_v002.ma
      hero_puppet_v002.json
      latest.json             points to the latest version

:func:`publish` saves the next version of a base path (``hero_puppet.ma``
saves ``hero_puppet_v003.ma``), writes its record and points ``latest.json``
at it. Numbers run on across the folder, whatever the base name, so a rig
has one sequence. Nothing is pruned.

``latest.json`` is a pointer, not a copy: Maya can't reference a JSON file,
so tools resolve it when they open, import or reference, and scenes store
the real ``vNNN`` path. Moving a scene to a newer version is an explicit
step (the Asset Library's Update to Latest).

The record is a Kaiju data file (``publish_record``) with the fields the
publisher passes, plus ``version``, ``file``, ``date``, ``user`` and
``kaiju_version``.
"""

import datetime
import getpass
import os
import re
from dataclasses import dataclass

import kaiju_suite
from kaiju_suite.core import datafile

LATEST_FILE = "latest.json"
LATEST_KIND = "publish_latest"
RECORD_KIND = "publish_record"
RECORD_EXTENSION = ".json"

# "<stem>_v<at least 3 digits><ext>"
_VERSION = re.compile(r"^(?P<stem>.+)_v(?P<number>\d{3,})(?P<ext>\.[^.]+)$")


@dataclass(frozen=True)
class PublishVersion:
    number: int
    path: str

    @property
    def tag(self):
        return f"v{self.number:03d}"

    @property
    def folder(self):
        return os.path.dirname(self.path)

    @property
    def record_path(self):
        return record_path(self.path)

    def record(self):
        """The version's build record, or ``None`` if it has none or it can't be read."""
        try:
            fields = datafile.read(self.record_path, RECORD_KIND)
        except (OSError, ValueError):
            return None
        return fields if isinstance(fields, dict) else None


def version_path(base_path, number):
    """Where version ``number`` of ``base_path`` is saved: ``hero.ma`` -> ``hero_v003.ma``."""
    stem, ext = os.path.splitext(base_path)
    return f"{stem}_v{number:03d}{ext}"


def record_path(path):
    """The build record next to the version file ``path``."""
    return os.path.splitext(path)[0] + RECORD_EXTENSION


def _parse(name):
    match = _VERSION.match(name)
    if match is None or match["ext"].lower() == RECORD_EXTENSION:
        return None
    return int(match["number"])


def list_versions(folder):
    """The versions in ``folder``, newest first. Files with a version-like
    name but no record (copied in by hand) count too."""
    if not os.path.isdir(folder):
        return []
    found = []
    for name in os.listdir(folder):
        number = _parse(name)
        path = os.path.join(folder, name)
        if number is not None and os.path.isfile(path):
            found.append(PublishVersion(number, path))
    return sorted(found, key=lambda v: v.number, reverse=True)


def next_number(folder):
    found = list_versions(folder)
    return found[0].number + 1 if found else 1


def find(folder, number):
    """Version ``number`` in ``folder``; raises ``LookupError`` if there's none."""
    found = next((v for v in list_versions(folder) if v.number == number), None)
    if found is None:
        raise LookupError(f"{os.path.basename(os.path.normpath(folder))} has no v{number:03d}.")
    return found


def latest(folder):
    """The version ``latest.json`` in ``folder`` points to, or ``None`` if
    there's no pointer, it can't be read, or its file is gone."""
    try:
        data = datafile.read(os.path.join(folder, LATEST_FILE), LATEST_KIND)
        name = data["file"]
        number = _parse(name)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    path = os.path.join(folder, name)
    if number is None or os.path.basename(name) != name or not os.path.isfile(path):
        return None
    return PublishVersion(number, path)


def set_latest(version):
    """Point the folder's ``latest.json`` at ``version``."""
    target = os.path.join(version.folder, LATEST_FILE)
    partial = target + ".part"
    datafile.write(partial, LATEST_KIND, {"version": version.number, "file": os.path.basename(version.path)})
    os.replace(partial, target)


def version_of(path):
    """The :class:`PublishVersion` ``path`` is, if it's a version file in a
    folder that has been published to (has a ``latest.json``), else ``None``."""
    path = os.path.normpath(path)
    number = _parse(os.path.basename(path))
    if number is None or not os.path.isfile(os.path.join(os.path.dirname(path), LATEST_FILE)):
        return None
    return PublishVersion(number, path)


def publish(base_path, save_fn, fields):
    """Save the next version of ``base_path`` with ``save_fn(target)``, write
    its build record (``fields`` plus when, who and which Kaiju) and point
    ``latest.json`` at it. Returns the :class:`PublishVersion`.

    If ``save_fn`` raises, the record and pointer are left alone."""
    folder = os.path.dirname(os.path.abspath(base_path))
    os.makedirs(folder, exist_ok=True)
    number = next_number(folder)
    version = PublishVersion(number, version_path(os.path.join(folder, os.path.basename(base_path)), number))
    save_fn(version.path)
    record = {
        "version": number,
        "file": os.path.basename(version.path),
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "user": _user(),
        "kaiju_version": kaiju_suite.__version__,
        **fields,
    }
    datafile.write(version.record_path, RECORD_KIND, record)
    set_latest(version)
    return version


def _user():
    try:
        return getpass.getuser()
    except Exception:  # no user name in the environment
        return ""
