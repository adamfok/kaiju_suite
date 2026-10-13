"""Rig Modules (.rig): parameters for a rig module, built by a build step.

The file holds only which rig module it is and its parameters (see
:mod:`kaiju_suite.rigging.rig_module.spec`); the algorithm lives in
:mod:`kaiju_suite.rigging.rig_module.modules`. **New** lists one entry per rig module and
writes its default parameters. The Type column shows the rig module's name
(e.g. ``Simple IK``) rather than "Rig Module". Double-click opens the Rig
Module Editor on the file to change them. **Run** builds the rig module from
them as one undo step, checking them first. **Publish** saves the
parameters as they are as the next version.

Right-click **Mirror** writes the item for the other side (``L_arm`` ->
``R_arm``) right after it, with its parameters mirrored (see
:meth:`RigModule.mirrored`), as that item's next version: run again, it
updates the other side's item instead of adding one. Modules that set
``mirrorable = False`` (Root) don't offer it.
"""

import os

from maya import cmds

from kaiju_suite.rigging.rig_module import all_rig_modules, get_rig_module, spec
from kaiju_suite.rigging.rig_module.rig_module import mirrored_name
from kaiju_suite.tools.assembler import logic, versions
from kaiju_suite.tools.assembler.products import Action, Creator, Panel, Product, new_path

EXTENSION = ".rig"


def create_rig_module(directory, name, rig_module_key):
    """Create a parameter file for ``module_key`` holding its defaults."""
    path = new_path(directory, name, EXTENSION)
    return spec.write(path, rig_module_key, get_rig_module(rig_module_key).defaults())


def _value_text(value):
    if isinstance(value, bool):
        return "on" if value else "off"
    if value == "":
        return "(none)"
    return str(value)


def mirror_path(path):
    """Where Mirror writes ``path``'s other side: ``R_arm.rig`` for ``L_arm.rig``,
    ``spine_mirrored.rig`` for ``spine.rig`` (and back)."""
    directory, name = os.path.split(path)
    stem, ext = os.path.splitext(name)
    return os.path.join(directory, mirrored_name(stem) + ext)


def _mirror_plan(path):
    """``(rig_module, params, unsided, problems)`` for mirroring ``path``."""
    try:
        rig_module, params = spec.load(path)
    except (OSError, ValueError, LookupError) as e:
        return None, None, [], [str(e)]
    mirrored, unsided = rig_module.mirrored(params)
    problems = []

    target = mirror_path(path)
    if os.path.exists(target):
        try:
            other = get_rig_module(spec.read(target)[0])
        except (OSError, ValueError, LookupError):
            other = None
        if other is not rig_module:
            kind = f"a {other.name} item" if other else "not a rig module this Kaiju Suite can read"
            problems.append(f"{os.path.basename(target)} is {kind}, so Mirror won't overwrite it. Rename or delete it first.")

    # The other side's joints must be there to build from (other nodes, like a
    # parent control, may come from a rig module that hasn't been built yet).
    missing = [
        mirrored[p.key]
        for p in rig_module.params
        if p.kind == "node"
        and mirrored[p.key] != params[p.key]
        and cmds.objExists(params[p.key])
        and cmds.objectType(params[p.key]) == "joint"
        and not cmds.objExists(mirrored[p.key])
    ]
    if missing:
        problems.append(f"The other side's joints aren't in the scene: {', '.join(missing)}. Mirror the skeleton first.")
    return rig_module, mirrored, unsided, problems


def mirror_problems(path):
    """Why ``path`` can't be mirrored now, as messages."""
    return _mirror_plan(path)[3]


def mirror(path):
    """Write ``path``'s other side (see :func:`mirror_path`) as that item's next
    version: a new item right after ``path``, or a new version of the one that
    is there. Returns a message."""
    rig_module, params, unsided, problems = _mirror_plan(path)
    if problems:
        raise ValueError("Can't mirror:\n" + "\n".join(f"- {p}" for p in problems))
    target = mirror_path(path)
    description = f"Mirrored from {os.path.basename(path)}"

    if os.path.exists(target):
        message = versions.export_into(target, lambda t: spec.write(t, rig_module.key, params), description)
    else:
        directory = os.path.dirname(path)
        index = logic.item_names(directory).index(os.path.basename(path)) + 1
        create = Creator(rig_module.name, lambda d, _name, _ext: spec.write(target, rig_module.key, params))
        logic.create_item(create, directory, os.path.basename(target), None, index)
        message = versions.published_message(target, versions.save_version(target, description=description))

    if unsided:
        nodes = ", ".join(params[key] for key in unsided)
        message += f". {nodes} {'has' if len(unsided) == 1 else 'have'} no side, so it points at the same nodes; edit it if needed"
    return message


class RigModuleProduct(Product):
    name = "Rig Module"
    extensions = (EXTENSION,)
    order = 140
    menu_slot = (5, 0)
    runnable = True
    versioned = True
    utility = "Rig Module Editor"

    @property
    def creators(self):
        return tuple(
            Creator(rig_module.name, lambda directory, name, _ext, key=rig_module.key: create_rig_module(directory, name, key))
            for rig_module in all_rig_modules()
        )

    def type_name(self, path):
        """The module's name, e.g. ``Simple IK``; ``Rig Module`` if the file
        can't be read or names a rig module this Kaiju Suite doesn't have."""
        try:
            return get_rig_module(spec.read(path)[0]).name
        except (OSError, ValueError, LookupError):
            return self.name

    def run(self, path):
        rig_module, params = spec.load(path)
        created = rig_module.build(params)
        return f"Built {rig_module.name} {params['name']}: {', '.join(created.values())}"

    def outputs(self, path):
        rig_module, params = spec.load(path)
        return rig_module.outputs(params)

    def node_refs(self, path):
        rig_module, params = spec.load(path)
        return rig_module.node_refs(params)

    def actions(self, path):
        try:
            rig_module = spec.load(path)[0]
        except (OSError, ValueError, LookupError):
            return []
        if not rig_module.mirrorable:
            return []
        target = os.path.basename(mirror_path(path))
        return [
            Action(
                "Mirror",
                lambda: mirror(path),
                tooltip=f"Writes {target} for the other side, with names and joints swapped, as its next version.",
                problems=lambda: mirror_problems(path),
            )
        ]

    def to_plan(self, path):
        key, params = spec.read(path)
        return {"module": key, "params": params}

    def plan_problems(self, item):
        key, params = item.get("module"), item.get("params", {})
        try:
            rig_module = get_rig_module(key)
        except LookupError:
            return [f"no rig module {key!r}; use one of {', '.join(m.key for m in all_rig_modules())}"]
        if not isinstance(params, dict):
            return [f"params must be an object of parameter values, not {params!r}"]
        return rig_module.value_problems(params)

    def from_plan(self, path, item):
        spec.write(path, item["module"], item.get("params", {}))

    def panel(self, path):
        try:
            rig_module, params = spec.load(path)
        except (OSError, ValueError, LookupError) as e:
            return Panel([str(e)], [])
        lines = [rig_module.name]
        lines.extend(f"{p.label}: {_value_text(params[p.key])}" for p in rig_module.params)
        lines.append(versions.summary(path))
        return Panel(lines, [])


PRODUCT = RigModuleProduct()
