"""Compare two payloads of a data item: lines saying what changed.

:func:`structural` is the summary every :class:`~.data.DataProduct` gets by
default: a walk over the two JSON payloads naming added, removed and changed
keys. Lists of records are matched by their ``name`` (or ``mesh``, ``node``)
rather than position, and lists of numbers are summed up as how many values
changed and by how much at most, so a mesh's points make one line, not one
per point. Products with a better summary override ``DataProduct.compare``
using the helpers here (:func:`match`, :func:`finish`, :func:`num`).

No Qt and no scene needed: only the payloads.
"""

import math
import numbers

# Lines shown before the rest are counted as "... and N more changes".
MAX_LINES = 30
NO_CHANGES = "No changes."
# Record fields that name a record, tried in order, for matching lists of them.
IDENTITY_KEYS = ("name", "mesh", "node")


def num(value):
    """A number for a summary line: ``1.0`` → ``1``, ``0.25`` → ``0.25``."""
    return f"{value:.6g}"


def finish(lines):
    """``lines`` ready to show: :data:`NO_CHANGES` if empty, cut to
    :data:`MAX_LINES` with a count of the rest."""
    lines = list(lines)
    if not lines:
        return [NO_CHANGES]
    if len(lines) > MAX_LINES:
        rest = len(lines) - MAX_LINES
        lines = lines[:MAX_LINES] + [f"... and {rest} more change{'s' if rest != 1 else ''}"]
    return lines


def structural(old, new):
    """What changed from payload ``old`` to ``new``, as lines (see the module doc)."""
    return finish(changes(old, new))


def changes(old, new, path=""):
    """The raw lines of :func:`structural`, uncut, empty if nothing changed.
    ``path`` prefixes each line, e.g. ``"body"`` → ``body.envelope: 1 → 0``."""
    lines = []
    _diff(old, new, path, lines)
    return lines


def match(old_records, new_records, key):
    """Match two lists of records by ``key`` (a field name or a function of a
    record). Returns ``(added, removed, common)``: names only in ``new``,
    names only in ``old``, and ``(name, old record, new record)`` for the rest,
    in ``new``'s order."""
    key_of = key if callable(key) else (lambda record: record[key])
    old_by = {key_of(r): r for r in old_records}
    new_by = {key_of(r): r for r in new_records}
    added = [k for k in new_by if k not in old_by]
    removed = [k for k in old_by if k not in new_by]
    common = [(k, old_by[k], new_by[k]) for k in new_by if k in old_by]
    return added, removed, common


def numeric_change(old, new):
    """``(changed, largest)`` between two equally long lists of numbers: how
    many differ and the largest difference."""
    deltas = [abs(a - b) for a, b in zip(old, new) if a != b]
    return len(deltas), max(deltas, default=0.0)


# -- the walk -----------------------------------------------------------------


def _join(path, key):
    return f"{path}.{key}" if path else str(key)


def _is_number(value):
    return isinstance(value, numbers.Real) and not isinstance(value, bool)


def _flat_numbers(value):
    """All the numbers in ``value`` (a number or nested lists of them), or
    ``None`` if it holds anything else."""
    if _is_number(value):
        return [value]
    if not isinstance(value, list):
        return None
    found = []
    for item in value:
        flat = _flat_numbers(item)
        if flat is None:
            return None
        found.extend(flat)
    return found


def _identity_key(old, new):
    """The field that names every record in both lists, uniquely, or ``None``."""
    records = old + new
    if not records or not all(isinstance(r, dict) for r in records):
        return None
    for key in IDENTITY_KEYS:
        try:
            names = [[r[key] for r in old], [r[key] for r in new]]
            if all(len(set(group)) == len(group) for group in names):
                return key
        except (KeyError, TypeError):  # missing, or not hashable
            continue
    return None


def _short(value):
    text = repr(value)
    return text if len(text) <= 40 else text[:37] + "..."


def _diff(old, new, path, lines):
    if old == new and type(old) is type(new):
        return
    if isinstance(old, dict) and isinstance(new, dict):
        for key in old:
            if key not in new:
                lines.append(f"Removed {_join(path, key)}")
            else:
                _diff(old[key], new[key], _join(path, key), lines)
        lines.extend(f"Added {_join(path, key)}" for key in new if key not in old)
    elif isinstance(old, list) and isinstance(new, list):
        _diff_lists(old, new, path, lines)
    elif _is_number(old) and _is_number(new):
        if old != new:
            lines.append(f"{path or 'value'}: {num(old)} → {num(new)}")
    else:
        lines.append(f"{path or 'value'}: {_short(old)} → {_short(new)}")


def _diff_lists(old, new, path, lines):
    label = path or "value"
    key = _identity_key(old, new)
    if key is not None:
        added, removed, common = match(old, new, key)
        if added:
            lines.append(f"{label}: added {', '.join(map(str, added))}")
        if removed:
            lines.append(f"{label}: removed {', '.join(map(str, removed))}")
        for name, a, b in common:
            _diff(a, b, f"{path}[{name}]", lines)
        return
    if len(old) != len(new):
        lines.append(f"{label}: {len(old)} → {len(new)} entries")
        return
    old_numbers, new_numbers = _flat_numbers(old), _flat_numbers(new)
    if old_numbers is not None and new_numbers is not None and len(old_numbers) == len(new_numbers):
        changed, largest = numeric_change(old_numbers, new_numbers)
        if changed:
            noun = "value" if len(old_numbers) == 1 else "values"
            lines.append(f"{label}: {changed} of {len(old_numbers)} {noun} changed (largest change {num(largest)})")
        return
    for i, (a, b) in enumerate(zip(old, new)):
        _diff(a, b, f"{path}[{i}]", lines)


def distance(a, b):
    """The distance between two points (lists of numbers)."""
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))
