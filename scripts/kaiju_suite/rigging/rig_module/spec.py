"""Rig module parameter files: which module, and its parameters. Nothing else.

    {"kaiju": "rigModule", "format": 1, "data": {"module": "simple_ik", "params": {...}}}
"""

import os

from kaiju_suite.rigging.rig_module import get_rig_module
from kaiju_suite.core import datafile

KIND = "rigModule"


def write(path, rig_module_key, params):
    """Write a parameter file for the rig module keyed ``module_key``."""
    return datafile.write(path, KIND, {"module": rig_module_key, "params": params})


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
    its parameters completed with that rig module's defaults. Raises
    :class:`LookupError` for a rig module this Kaiju Suite doesn't have."""
    key, params = read(path)
    rig_module = get_rig_module(key)
    return rig_module, rig_module.complete(params)
