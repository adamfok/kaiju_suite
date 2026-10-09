"""The rig module base class, and :class:`Param`, which describes one parameter.

A rig module lists its parameters, so parameter files can be filled with
defaults and the Rig Module Editor can build its form from them. It checks
parameters in :meth:`RigModule.problems` and builds in
:meth:`RigModule.create`. No Qt here.
"""

from dataclasses import dataclass

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
    ``params``, and implement :meth:`check` and :meth:`create`."""

    key = ""
    name = ""
    params = ()

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
