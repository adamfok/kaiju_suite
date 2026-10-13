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
