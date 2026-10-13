"""Rig modules: the algorithms that build parts of a rig from parameters.

A rig module is any file in :mod:`.modules` that defines ``RIG_MODULE``, an
instance of a :class:`.rig_module.RigModule` subclass. Adding one means
adding a file there; the Assembler's Rig Module items and the Rig Module
Editor find it by its ``key``. Parameter files are :mod:`.spec`.

The pieces rig modules share are here too: :mod:`.helpers` (checks, groups,
control curves), :mod:`.controls` (what makes a node a rig control), and
:mod:`.space_switch` and :mod:`.ik_fk_match` (switching without a pop, which
the animation tools use as well).

Like the rest of :mod:`kaiju_suite.rigging`, this imports only
:mod:`kaiju_suite.core`: never ``ui`` or ``tools``, and no Qt.
"""

from kaiju_suite.rigging import find_instances


def discover():
    """Import every rig module file and return their rig modules, by name."""
    from kaiju_suite.rigging.rig_module import modules
    from kaiju_suite.rigging.rig_module.rig_module import RigModule

    return find_instances(modules, "RIG_MODULE", RigModule, "rig module")


_cache = None


def all_rig_modules():
    """Discovered rig modules, cached after the first call."""
    global _cache
    if _cache is None:
        _cache = discover()
    return _cache


def get_rig_module(key):
    """The rig module whose key is ``key``; raises :class:`LookupError` if none."""
    for rig_module in all_rig_modules():
        if rig_module.key == key:
            return rig_module
    known = ", ".join(m.key for m in all_rig_modules()) or "none"
    raise LookupError(f"Unknown rig module {key!r} (known: {known}).")
