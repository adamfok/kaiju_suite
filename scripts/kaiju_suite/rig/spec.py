"""Rig module parameter files: which module, and its parameters. Nothing else.

    {"kaiju": "rigModule", "format": 1, "data": {"module": "simple_ik", "params": {...}}}
"""

import os

from kaiju_suite import rig
from kaiju_suite.core import datafile

KIND = "rigModule"


def write(path, module_key, params):
    """Write a parameter file for the module keyed ``module_key``."""
    return datafile.write(path, KIND, {"module": module_key, "params": params})


def read(path):
    """``(module_key, params)`` as saved in ``path``.

    Raises :class:`~kaiju_suite.core.datafile.DataFormatError` if it isn't a
    rig module file.
    """
    payload = datafile.read(path, KIND)
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("module"), str)
        or not isinstance(payload.get("params"), dict)
    ):
        name = os.path.basename(path)
        raise datafile.DataFormatError(f"{name} is not a rig module file: it needs a module and its parameters.")
    return payload["module"], payload["params"]


def load(path):
    """``(module, params)`` for ``path``: the :class:`RigModule` it names, and
    its parameters completed with that module's defaults. Raises
    :class:`LookupError` for a module this Kaiju Suite doesn't have."""
    key, params = read(path)
    module = rig.get(key)
    return module, module.complete(params)
