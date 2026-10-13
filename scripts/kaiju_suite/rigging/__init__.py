"""Rigging: what builds a rig, with no Qt.

- :mod:`.rig_module`: rig modules, the algorithms that build parts of a rig
  from parameters (one file each in ``rig_module/modules/``), and the pieces
  they share.
- :mod:`.guide_module`: guide modules, layouts of guides for parts of a rig
  (one file each in ``guide_module/modules/``).

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
