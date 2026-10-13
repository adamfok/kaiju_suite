"""Rig modules: the algorithms that build parts of a rig from parameters.

A rig module is any file in :mod:`kaiju_suite.rigging.rig_modules` that
defines ``RIG_MODULE``, an instance of a
:class:`~kaiju_suite.rigging.rig_module.RigModule` subclass. Adding one means
adding a file there; the Assembler's Rig Module items and the Rig Module
Editor find it by its ``key``.

This package imports only :mod:`kaiju_suite.core`: never ``ui`` or
``tools``, and no Qt.
"""

import importlib
import pkgutil

from kaiju_suite.core.log import get_logger

log = get_logger(__name__)


def discover():
    """Import every rig module file and return their rig modules, by name."""
    from kaiju_suite.rigging import rig_modules
    from kaiju_suite.rigging.rig_module import RigModule

    found = []
    for info in pkgutil.iter_modules(rig_modules.__path__):
        module_name = f"{rig_modules.__name__}.{info.name}"
        try:
            imported = importlib.import_module(module_name)
        except Exception:
            log.exception("Failed to import rig module %s", module_name)
            continue
        rig_module = getattr(imported, "RIG_MODULE", None)
        if isinstance(rig_module, RigModule):
            found.append(rig_module)
    found.sort(key=lambda m: m.name)

    keys = {}
    for rig_module in found:
        if rig_module.key in keys:
            log.warning("%s and %s share the key %r; %s wins", keys[rig_module.key].name, rig_module.name, rig_module.key, keys[rig_module.key].name)
        else:
            keys[rig_module.key] = rig_module
    return found


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
