"""Kaiju data files: JSON with a header naming what the file holds::

    {"kaiju": "joints", "format": 1, "data": {...}}

Shared by the Assembler's rig-data products and by rig module parameter
files. No Qt here.
"""

import json
import os

# The file format this code writes; files with a newer one are refused.
FORMAT = 1


class DataFormatError(ValueError):
    """A data file that isn't valid, or isn't the kind expected."""


def write(path, kind, payload):
    """Write ``payload`` to ``path`` as a ``kind`` data file.

    The output is deterministic (no timestamps), so publishing unchanged
    content gives the same bytes and adds no new version.
    """
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"kaiju": kind, "format": FORMAT, "data": payload}, f, indent=1)
        f.write("\n")
    return path


def read(path, kind):
    """The payload of the ``kind`` data file at ``path``.

    Raises :class:`DataFormatError` if it isn't JSON, holds another kind,
    or was written in a newer format.
    """
    name = os.path.basename(path)
    try:
        with open(path, encoding="utf-8") as f:
            content = json.load(f)
    except (ValueError, UnicodeDecodeError) as e:
        raise DataFormatError(f"{name} is not a Kaiju data file: {e}") from e
    if not isinstance(content, dict) or "kaiju" not in content:
        raise DataFormatError(f"{name} is not a Kaiju data file.")
    if content["kaiju"] != kind:
        raise DataFormatError(f"{name} holds {content['kaiju']!r} data, not {kind!r}.")
    file_format = content.get("format")
    if not isinstance(file_format, int):
        raise DataFormatError(f"{name} has no format number.")
    if file_format > FORMAT:
        raise DataFormatError(f"{name} uses format {file_format}; this Kaiju Suite reads up to {FORMAT}. Update it.")
    if "data" not in content:
        raise DataFormatError(f"{name} has no data.")
    return content["data"]
