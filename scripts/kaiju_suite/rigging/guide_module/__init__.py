"""Guide modules: layouts of guides for parts of a rig, built with joints
that follow them live.

A guide module is any file in :mod:`.modules` that defines
``GUIDE_MODULE``, an instance of a :class:`.guide_module.GuideModule`
subclass. Adding one means adding a file there; the Assembler's Guide
items find it by its ``key``. Guide files are :mod:`.spec`, and
:mod:`.planar_chain` builds the planar chains guide modules are made of.

Like the rest of :mod:`kaiju_suite.rigging`, this imports only
:mod:`kaiju_suite.core`: never ``ui``, ``tools`` or ``datatypes``, and no Qt.
"""

from maya import cmds

from kaiju_suite.core.selection import short_name
from kaiju_suite.core.undo import undo_chunk
from kaiju_suite.rigging import find_instances


def discover():
    """Import every guide module file and return their guide modules, by name."""
    from kaiju_suite.rigging.guide_module import modules
    from kaiju_suite.rigging.guide_module.guide_module import GuideModule

    return find_instances(modules, "GUIDE_MODULE", GuideModule, "guide module")


_cache = None


def all_guide_modules():
    """Discovered guide modules, cached after the first call."""
    global _cache
    if _cache is None:
        _cache = discover()
    return _cache


def get_guide_module(key):
    """The guide module whose key is ``key``; raises :class:`LookupError` if none."""
    for guide_module in all_guide_modules():
        if guide_module.key == key:
            return guide_module
    known = ", ".join(m.key for m in all_guide_modules()) or "none"
    raise LookupError(f"Unknown guide module {key!r} (known: {known}).")


def delete_all_guides():
    """Extract the joints of every guide module in the scene (see
    :meth:`.guide_module.GuideModule.extract`), as one undo step. Checks
    them all first and raises :class:`.guide_module.GuideError`, changing
    nothing, if any can't be extracted. Returns ``{guides name: joints}``,
    empty with no guides."""
    from kaiju_suite.rigging.guide_module.guide_module import TAG, GuideError

    found, problems = [], []
    for group in cmds.ls(f"*.{TAG}", objectsOnly=True, long=True, recursive=True) or []:
        try:
            guide_module = get_guide_module(cmds.getAttr(f"{group}.{TAG}"))
        except LookupError as e:
            problems.append(f"{short_name(group)}: {e}")
            continue
        problems += [f"{short_name(group)}: {p}" for p in guide_module.check_extract(group)]
        found.append((cmds.ls(group, uuid=True)[0], guide_module))
    if problems:
        raise GuideError("Can't turn the guides into joints:\n" + "\n".join(f"- {p}" for p in problems))
    extracted = {}
    with undo_chunk("Kaiju Guides to Joints"):
        for uuid, guide_module in found:
            group = cmds.ls(uuid, long=True)[0]
            name = guide_module.layout(group)["name"]
            extracted[name] = guide_module.extract(group)
    return extracted
