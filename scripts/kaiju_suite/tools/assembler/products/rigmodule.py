"""Rig Modules (.rig): parameters for a rig module, built by a build step.

The file holds only which module it is and its parameters (see
:mod:`kaiju_suite.rigging.spec`); the algorithm lives in
:mod:`kaiju_suite.rigging.modules`. **New** lists one entry per rig module and
writes its default parameters. The Type column shows the module's name
(e.g. ``Simple IK``) rather than "Rig Module". Double-click opens the Rig
Module Editor on the file to change them. **Run** builds the module from
them as one undo step, checking them first. **Publish** saves the
parameters as they are as the next version.
"""

from kaiju_suite import rigging
from kaiju_suite.rigging import spec
from kaiju_suite.tools.assembler import versions
from kaiju_suite.tools.assembler.products import Creator, Panel, Product, new_path

EXTENSION = ".rig"


def create_module(directory, name, module_key):
    """Create a parameter file for ``module_key`` holding its defaults."""
    path = new_path(directory, name, EXTENSION)
    return spec.write(path, module_key, rigging.get(module_key).defaults())


def _value_text(value):
    if isinstance(value, bool):
        return "on" if value else "off"
    if value == "":
        return "(none)"
    return str(value)


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
            Creator(module.name, lambda directory, name, _ext, key=module.key: create_module(directory, name, key))
            for module in rigging.all_modules()
        )

    def type_name(self, path):
        """The module's name, e.g. ``Simple IK``; ``Rig Module`` if the file
        can't be read or names a module this Kaiju Suite doesn't have."""
        try:
            return rigging.get(spec.read(path)[0]).name
        except (OSError, ValueError, LookupError):
            return self.name

    def run(self, path):
        module, params = spec.load(path)
        created = module.build(params)
        return f"Built {module.name} {params['name']}: {', '.join(created.values())}"

    def outputs(self, path):
        module, params = spec.load(path)
        return module.outputs(params)

    def node_refs(self, path):
        module, params = spec.load(path)
        return module.node_refs(params)

    def to_plan(self, path):
        key, params = spec.read(path)
        return {"module": key, "params": params}

    def plan_problems(self, item):
        key, params = item.get("module"), item.get("params", {})
        try:
            module = rigging.get(key)
        except LookupError:
            return [f"no rig module {key!r}; use one of {', '.join(m.key for m in rigging.all_modules())}"]
        if not isinstance(params, dict):
            return [f"params must be an object of parameter values, not {params!r}"]
        return module.value_problems(params)

    def from_plan(self, path, item):
        spec.write(path, item["module"], item.get("params", {}))

    def panel(self, path):
        try:
            module, params = spec.load(path)
        except (OSError, ValueError, LookupError) as e:
            return Panel([str(e)], [])
        lines = [module.name]
        lines.extend(f"{p.label}: {_value_text(params[p.key])}" for p in module.params)
        lines.append(versions.summary(path))
        return Panel(lines, [])


PRODUCT = RigModuleProduct()
