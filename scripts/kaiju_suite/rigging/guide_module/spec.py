"""Guide module files (``.guide``): which guide module, and its layout.

    {"kaiju": "guideModule", "format": 1, "data": {"guide_module": "chain", "layout": {...}}}

Guide modules own their file format here, as rig modules do in
:mod:`kaiju_suite.rigging.rig_module.spec`, rather than in :mod:`kaiju_suite.datatypes`.
The functions below the file ones are the datatype interface the
Assembler's Guide items use (``gather``, ``apply``, ``selection_problems``,
``describe``, ``nodes``): the payload is the file's ``data``.
"""

import os

from maya import cmds

from kaiju_suite.core import datafile
from kaiju_suite.core.selection import short_name
from kaiju_suite.rigging.guide_module import get_guide_module, planar_chain
from kaiju_suite.rigging.guide_module.guide_module import tagged_key

KIND = "guideModule"
EXTENSION = ".guide"
# Chains built before guide modules carry no tag: an untagged planar chain is a Chain guide module.
_PLANAR = "chain"
_NOTHING = "Nothing selected. Select guides, a guide group or a joint they drive."


# -- files ----------------------------------------------------------------------


def write(path, guide_module_key, layout):
    """Write a guide file for the guide module keyed ``guide_module_key``."""
    return datafile.write(path, KIND, {"guide_module": guide_module_key, "layout": layout})


def read(path):
    """``(guide_module_key, layout)`` as saved in ``path``.

    Raises :class:`~kaiju_suite.core.datafile.DataFormatError` if it isn't a
    guide module file.
    """
    payload = datafile.read(path, KIND)
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("guide_module"), str)
        or not isinstance(payload.get("layout"), dict)
    ):
        name = os.path.basename(path)
        raise datafile.DataFormatError(f"{name} is not a guide module file: it needs a guide module and its layout.")
    return payload["guide_module"], payload["layout"]


def load(path):
    """``(guide_module, layout)`` for the file at ``path``. Raises
    :class:`LookupError` for a guide module this Kaiju Suite doesn't have."""
    key, layout = read(path)
    return get_guide_module(key), layout


# -- finding guides in the scene ------------------------------------------------


def _with_parents(node):
    return [node] + (cmds.listRelatives(node, allParents=True, fullPath=True) or [])


def _top_group(node):
    """``(guide_module_key, top group)`` of the guide module ``node``
    belongs to: the outermost tagged group above it (or above the planar
    chain it's part of), else the untagged planar chain itself."""
    found = cmds.ls(node, long=True) if node else []
    if not found:
        raise ValueError(f"{node!r} isn't in the scene.")
    candidates = _with_parents(found[0])
    try:
        chain = planar_chain.guide_group(found[0])
    except ValueError:
        chain = None
    if chain:
        candidates += _with_parents(chain)
    tagged = [c for c in cmds.ls(candidates, long=True) if tagged_key(c)]
    if tagged:
        top = min(tagged, key=lambda c: c.count("|"))
        return tagged_key(top), top
    if chain:
        return _PLANAR, chain
    raise ValueError(f"{short_name(found[0])} isn't a guide, a guide group or a joint built from guides.")


def find_group(nodes):
    """``(guide_module, top group)`` of the one guide module ``nodes`` (e.g.
    the selection) belong to. Raises ``ValueError`` naming the problem."""
    if not nodes:
        raise ValueError(_NOTHING)
    found = list(dict.fromkeys(_top_group(node) for node in nodes))
    if len(found) > 1:
        raise ValueError(f"Select guides of one guide module, not {', '.join(short_name(g) for _, g in found)}.")
    key, group = found[0]
    try:
        return get_guide_module(key), group
    except LookupError as e:
        raise ValueError(f"{short_name(group)}: {e}") from None


# -- the Assembler's datatype interface ---------------------------------------


def _unpack(payload):
    """``(guide_module, layout)`` from a payload; raises ``LookupError``."""
    return get_guide_module(payload["guide_module"]), payload["layout"]


def gather(nodes):
    guide_module, group = find_group(nodes)
    return {"guide_module": guide_module.key, "layout": guide_module.layout(group)}


def apply(payload, info=None):
    """Build the guides in ``payload``. Raises ``RuntimeError``, changing
    nothing, if its guide module is unknown or can't build it here (e.g.
    the guides are already in the scene)."""
    try:
        guide_module, layout = _unpack(payload)
    except LookupError as e:
        raise RuntimeError(str(e.args[0] if e.args else e)) from None
    problems = guide_module.problems(layout)
    if problems:
        raise RuntimeError("\n".join(problems))
    guide_module.build(layout)
    return f"Built {guide_module.name} {'; '.join(guide_module.describe(layout))}"


def selection_problems(selection):
    if not selection:
        return [_NOTHING]
    problems = []
    for node in selection:
        try:
            _top_group(node)
        except ValueError as e:
            problems.append(str(e))
    if problems:
        return problems
    try:
        find_group(selection)
    except ValueError as e:
        return [str(e)]
    return []


def describe(payload):
    try:
        guide_module, layout = _unpack(payload)
    except LookupError as e:
        return [str(e.args[0] if e.args else e)]
    return [guide_module.name] + guide_module.describe(layout)


def nodes(payload):
    guide_module, layout = _unpack(payload)
    return guide_module.nodes(layout)


def mirrored(payload):
    """``payload`` for the other side (see :meth:`GuideModule.mirrored`)."""
    guide_module, layout = _unpack(payload)
    return {"guide_module": guide_module.key, "layout": guide_module.mirrored(layout)}
