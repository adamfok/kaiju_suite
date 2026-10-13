"""The rig module base class, and :class:`Param`, which describes one parameter.

A rig module lists its parameters, so parameter files can be filled with
defaults and the Rig Module Editor can build its form from them. It checks
parameters in :meth:`RigModule.problems` and builds in
:meth:`RigModule.create`. :meth:`RigModule.outputs` names what a build
would make, and :meth:`RigModule.node_refs` the scene nodes it needs, so a
build can be checked before anything is built. No Qt here.
"""

from dataclasses import dataclass

from kaiju_suite.core.naming import MIRRORED_SUFFIX, mirrored_name, opposite_name  # noqa: F401 (re-exported)
from kaiju_suite.core.undo import undo_chunk

# What a parameter holds. "node" is a scene node's name; editors offer to
# pick it from the selection. "color" is a Maya index color, 0 to 31 (the
# Drawing Overrides palette); 0 means Maya's default color.
KINDS = ("string", "node", "float", "bool", "choice", "color")
COLORS = range(32)

@dataclass(frozen=True)
class Param:
    key: str
    label: str
    kind: str
    default: object
    choices: tuple = ()  # the allowed values of a "choice"
    required: bool = False  # "string" and "node" only: may not be blank
    tooltip: str = ""

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"Unknown parameter kind {self.kind!r}; use one of {', '.join(KINDS)}.")


class ParamError(ValueError):
    """Parameters a rig module can't build from."""


class RigModule:
    """Subclass, set ``key`` (saved in parameter files), ``name`` and
    ``params``, and implement :meth:`check`, :meth:`create` and :meth:`names`."""

    key = ""
    name = ""
    params = ()
    mirrorable = True  # Assembler items get a right-click Mirror (see :meth:`mirrored`)

    def defaults(self):
        return {p.key: p.default for p in self.params}

    def complete(self, params):
        """``params`` with missing ones set to their defaults. Unknown ones are
        kept, so a file written by a newer module loses nothing."""
        merged = self.defaults()
        merged.update(params)
        return merged

    def problems(self, params):
        """Why ``params`` can't be built, as messages; empty if they can."""
        params = self.complete(params)
        found = []
        for param in self.params:
            found.extend(_value_problems(param, params[param.key]))
        if not found:
            found.extend(self.check(params))
        return found

    def value_problems(self, params):
        """Problems with the values in ``params`` alone, without the scene:
        unknown keys and wrong types. Missing ones aren't checked, since they
        default (and :meth:`problems` checks required ones before a build)."""
        known = {p.key: p for p in self.params}
        found = [f"{self.name} has no parameter {key!r}." for key in params if key not in known]
        for key, value in params.items():
            if key in known:
                found.extend(_value_problems(known[key], value))
        return found

    def outputs(self, params):
        """The names of every transform (groups, controls, joints, handles,
        constraints, ...) a build from ``params`` would make, without changing
        the scene. Names that depend on a joint chain are only listed if the
        chain is in the scene."""
        return self.names(self.complete(params))

    def node_refs(self, params):
        """``[(label, name), ...]``: the scene nodes a build from ``params``
        needs, from its filled-in "node" parameters."""
        params = self.complete(params)
        refs = []
        for param in self.params:
            value = params[param.key]
            if param.kind == "node" and isinstance(value, str) and value.strip():
                refs.append((param.label, value.strip()))
        return refs

    def mirrored(self, params):
        """``(params, unsided)``: ``params`` for the same module on the other
        side, and the keys of the node parameters left as they were.

        Every text and node parameter gets its side swapped. ``name`` always
        changes (see :func:`mirrored_name`), so the two sides' nodes never
        clash; other ones with no side stay, so the copy points at the same
        nodes until edited. Nothing else changes: the modules line controls
        up with the joints, so a behavior-mirrored skeleton gives
        behavior-mirrored controls.
        """
        params = self.complete(params)
        result, unsided = dict(params), []
        for param in self.params:
            value = params[param.key]
            if param.kind not in ("string", "node") or not isinstance(value, str):
                continue
            if param.key == "name":
                result["name"] = mirrored_name(value.strip())
                continue
            opposite = opposite_name(value)
            if opposite is not None:
                result[param.key] = opposite
            elif param.kind == "node" and value.strip():
                unsided.append(param.key)
        return result, unsided

    def build(self, params):
        """Check ``params``, then build as one undo step. Raises
        :class:`ParamError` listing the problems before changing anything."""
        params = self.complete(params)
        problems = self.problems(params)
        if problems:
            raise ParamError(f"Can't build {self.name}:\n" + "\n".join(f"- {p}" for p in problems))
        with undo_chunk(f"Kaiju {self.name}"):
            return self.create(params)

    # -- for subclasses ------------------------------------------------------

    def check(self, params):
        """Module-specific problems, as messages. Called only once every
        value has the right type, with complete ``params``."""
        return []

    def create(self, params):
        """Build in the scene from checked, complete ``params``."""
        raise NotImplementedError

    def names(self, params):
        """:meth:`outputs` for complete ``params``; must match what
        :meth:`create` makes. May read the scene, never change it."""
        raise NotImplementedError


def _value_problems(param, value):
    if param.kind in ("string", "node"):
        if not isinstance(value, str):
            return [f"{param.label} must be text, not {value!r}."]
        if param.required and not value.strip():
            return [f"{param.label} is required."]
    elif param.kind == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return [f"{param.label} must be a number, not {value!r}."]
    elif param.kind == "bool":
        if not isinstance(value, bool):
            return [f"{param.label} must be on or off, not {value!r}."]
    elif param.kind == "choice":
        if value not in param.choices:
            return [f"{param.label} must be one of {', '.join(map(str, param.choices))}, not {value!r}."]
    elif param.kind == "color":
        if isinstance(value, bool) or not isinstance(value, int) or value not in COLORS:
            return [f"{param.label} must be a Maya index color, 0 to 31, not {value!r}."]
    return []
