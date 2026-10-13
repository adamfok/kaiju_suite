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


def find_instances(package, attr, base, what):
    """Import every file in ``package`` and return the ``base`` instances
    they define as ``attr``, sorted by name. A file that fails to import is
    logged and skipped; of two sharing a ``key``, the first by name wins
    (``what`` names them in the log, e.g. "rig module")."""
    found = []
    for info in pkgutil.iter_modules(package.__path__):
        module_name = f"{package.__name__}.{info.name}"
        try:
            imported = importlib.import_module(module_name)
        except Exception:
            log.exception("Failed to import %s %s", what, module_name)
            continue
        instance = getattr(imported, attr, None)
        if isinstance(instance, base):
            found.append(instance)
    found.sort(key=lambda m: m.name)

    keys = {}
    for instance in found:
        if instance.key in keys:
            log.warning("%s and %s share the key %r; %s wins", keys[instance.key].name, instance.name, instance.key, keys[instance.key].name)
        else:
            keys[instance.key] = instance
    return found


def discover():
    """Import every rig module file and return their rig modules, by name."""
    from kaiju_suite.rigging import rig_modules
    from kaiju_suite.rigging.rig_module import RigModule

    return find_instances(rig_modules, "RIG_MODULE", RigModule, "rig module")


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
