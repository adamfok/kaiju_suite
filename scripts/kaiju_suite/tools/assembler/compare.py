"""Compare two payloads of a data item, for the side-by-side compare window.

:func:`tree` walks both payloads together into :class:`Row` s, one tree per
side, matched the same way: keys by name, lists of records by their ``name``
(or ``mesh``, ``node``), lists of names by value, other lists by position.
Long lists of numbers fold into one row saying how many entries changed and
by how much at most, so a mesh's points make one row, not one per point.
Products tidy a payload first with ``DataProduct.compare_view``.

No Qt and no scene needed: only the payloads.
"""

import numbers
from dataclasses import dataclass, field

NO_CHANGES = "No changes."
# Record fields that name a record, tried in order, for matching lists of them.
IDENTITY_KEYS = ("name", "mesh", "node")


def num(value):
    """A number for a value column: ``1.0`` → ``1``, ``0.25`` → ``0.25``."""
    return f"{value:.6g}"


def _is_number(value):
    return isinstance(value, numbers.Real) and not isinstance(value, bool)


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


# -- the side-by-side tree ----------------------------------------------------

SAME, CHANGED, ADDED, REMOVED = "same", "changed", "added", "removed"
# Number lists up to this long show their values; longer ones fold to a count.
SHORT_LIST = 4
_MISSING = object()


@dataclass
class Row:
    """One row of both trees. ``old`` and ``new`` are the value column on
    each side, ``None`` where that side has nothing here (a blank row keeps
    the trees lined up)."""

    label: str
    old: object
    new: object
    status: str
    children: list = field(default_factory=list)


@dataclass
class Diff:
    """Both trees of the compare window: titles over each, and the rows."""

    old_title: str
    new_title: str
    rows: list


def tree(old, new):
    """The rows comparing payload ``old`` with ``new``: their keys, records
    matched by name (see :data:`IDENTITY_KEYS`), names matched by value, and
    long lists of numbers folded into one row saying how many changed."""
    if isinstance(old, dict) and isinstance(new, dict):
        return _dict_rows(old, new)
    return [_row("value", old, new)]


def has_changes(rows):
    return any(row.status != SAME for row in rows)


def _kind(value):
    if isinstance(value, dict):
        return "dict"
    return "list" if isinstance(value, list) else "value"


def _row(label, old, new, skip=None):
    present = [v for v in (old, new) if v is not _MISSING]
    kinds = {_kind(v) for v in present}
    children = []
    if kinds == {"dict"}:
        children = _dict_rows(*(v if v is not _MISSING else {} for v in (old, new)), skip=skip)
    elif kinds == {"list"}:
        if all(0 < len(v) <= SHORT_LIST and all(map(_is_number, v)) for v in present):
            return _leaf(label, *(_numbers_text(v) for v in (old, new)), old, new)
        if all(_is_numeric_list(v) for v in present):
            return _folded(label, old, new)
        children = _list_rows(*(v if v is not _MISSING else [] for v in (old, new)))
    else:
        return _leaf(label, *(_text(v) for v in (old, new)), old, new)
    # Order doesn't count: matched rows say what changed.
    status = _presence(old, new) or (CHANGED if has_changes(children) else SAME)
    return Row(label, _text(old), _text(new), status, children)


def _presence(old, new):
    if old is _MISSING:
        return ADDED
    if new is _MISSING:
        return REMOVED
    return None


def _leaf(label, old_text, new_text, old, new):
    same = old == new and _kind(old) == _kind(new) and isinstance(old, bool) == isinstance(new, bool)
    return Row(label, old_text, new_text, _presence(old, new) or (SAME if same else CHANGED))


def _dict_rows(old, new, skip=None):
    keys = [k for k in old if k != skip] + [k for k in new if k not in old and k != skip]
    return [_row(str(k), old.get(k, _MISSING), new.get(k, _MISSING)) for k in keys]


def _list_rows(old, new):
    key = _identity_key(old, new)
    if key is not None:
        old_by, new_by = {r[key]: r for r in old}, {r[key]: r for r in new}
        names = list(old_by) + [n for n in new_by if n not in old_by]
        return [_row(str(n), old_by.get(n, _MISSING), new_by.get(n, _MISSING), skip=key) for n in names]
    if _is_name_list(old) and _is_name_list(new):
        names = old + [n for n in new if n not in old]
        return [_leaf(_text(n), *("" if n in side else None for side in (old, new)),
                      *(n if n in side else _MISSING for side in (old, new))) for n in names]
    return [
        _row(f"[{i}]", old[i] if i < len(old) else _MISSING, new[i] if i < len(new) else _MISSING)
        for i in range(max(len(old), len(new)))
    ]


def _is_name_list(values):
    """A list of distinct names (or other plain values) to match by value."""
    plain = all(isinstance(v, (str, numbers.Real)) or v is None for v in values)
    return plain and len(set(values)) == len(values)


def _is_numeric_list(value):
    """A list whose entries are numbers, or lists or dicts holding only numbers."""
    return all(_entry_numbers(v) is not None for v in value)


def _entry_numbers(value):
    """``{position: number}`` for one entry of a number list, or ``None`` if
    it holds anything but numbers. Dicts are keyed by their keys, so a key
    one side lacks is a 0 there."""
    if _is_number(value):
        return {(): value}
    if isinstance(value, (list, dict)):
        found = {}
        for key, item in value.items() if isinstance(value, dict) else enumerate(value):
            inner = _entry_numbers(item)
            if inner is None:
                return None
            found.update({(key, *k): v for k, v in inner.items()})
        return found
    return None


def _folded(label, old, new):
    texts = [None if v is _MISSING else _items(len(v)) for v in (old, new)]
    status = _presence(old, new)
    if status is None:
        status = SAME if old == new else CHANGED
        if status == CHANGED and len(old) == len(new):
            deltas = []
            for a, b in zip(old, new):
                a, b = _entry_numbers(a), _entry_numbers(b)
                delta = max((abs(a.get(k, 0) - b.get(k, 0)) for k in set(a) | set(b)), default=0)
                if delta:
                    deltas.append(delta)
            if deltas:
                texts[1] += f" ({len(deltas)} changed, largest change {num(max(deltas))})"
            else:
                status = SAME  # only ints turned floats, or zero weights added
    return Row(label, texts[0], texts[1], status)


def _items(count):
    return f"{count} item{'s' if count != 1 else ''}"


def _numbers_text(value):
    return None if value is _MISSING else ", ".join(num(v) for v in value)


def _text(value):
    """What the value column shows for ``value``."""
    if value is _MISSING:
        return None
    if isinstance(value, dict):
        return ""
    if isinstance(value, list):
        return _items(len(value))
    if _is_number(value):
        return num(value)
    text = str(value)
    return text if len(text) <= 60 else text[:57] + "..."
