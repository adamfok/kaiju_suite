"""Rig modules: the algorithms that build parts of a rig from parameters.

A rig module is any module in :mod:`kaiju_suite.rig.modules` that defines
``MODULE``, an instance of a :class:`~kaiju_suite.rig.module.RigModule`
subclass. Adding one means adding a file there; the Assembler's Rig Module
items and the Rig Module Editor find it by its ``key``.

This package imports only :mod:`kaiju_suite.core`: never ``ui`` or
``tools``, and no Qt.
"""

import importlib
import pkgutil

from kaiju_suite.core.log import get_logger

log = get_logger(__name__)


def discover():
    """Import every rig module and return their modules, by name."""
    from kaiju_suite.rig import modules
    from kaiju_suite.rig.module import RigModule

    found = []
    for info in pkgutil.iter_modules(modules.__path__):
        module_name = f"{modules.__name__}.{info.name}"
        try:
            imported = importlib.import_module(module_name)
        except Exception:
            log.exception("Failed to import rig module %s", module_name)
            continue
        module = getattr(imported, "MODULE", None)
        if isinstance(module, RigModule):
            found.append(module)
    found.sort(key=lambda m: m.name)

    keys = {}
    for module in found:
        if module.key in keys:
            log.warning("%s and %s share the key %r; %s wins", keys[module.key].name, module.name, module.key, keys[module.key].name)
        else:
            keys[module.key] = module
    return found


_cache = None


def all_modules():
    """Discovered rig modules, cached after the first call."""
    global _cache
    if _cache is None:
        _cache = discover()
    return _cache


def get(key):
    """The rig module whose key is ``key``; raises :class:`LookupError` if none."""
    for module in all_modules():
        if module.key == key:
            return module
    known = ", ".join(m.key for m in all_modules()) or "none"
    raise LookupError(f"Unknown rig module {key!r} (known: {known}).")
