"""Rig Modules (.rig): parameters for a rig module, built by a build step.

The file holds only which module it is and its parameters (see
:mod:`kaiju_suite.rig.spec`); the algorithm lives in
:mod:`kaiju_suite.rig.modules`. **New** lists one entry per rig module and
writes its default parameters. The Type column shows the module's name
(e.g. ``Simple IK``) rather than "Rig Module". Double-click opens the Rig
Module Editor on the file to change them. **Run** builds the module from
them as one undo step, checking them first. **Publish** saves the
parameters as they are as the next version.
"""

from kaiju_suite import rig
from kaiju_suite.rig import spec
from kaiju_suite.tools.assembler import versions
from kaiju_suite.tools.assembler.products import Creator, Panel, Product, new_path

EXTENSION = ".rig"


def create_module(directory, name, module_key):
    """Create a parameter file for ``module_key`` holding its defaults."""
    path = new_path(directory, name, EXTENSION)
    return spec.write(path, module_key, rig.get(module_key).defaults())


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
            for module in rig.all_modules()
        )

    def type_name(self, path):
        """The module's name, e.g. ``Simple IK``; ``Rig Module`` if the file
        can't be read or names a module this Kaiju Suite doesn't have."""
        try:
            return rig.get(spec.read(path)[0]).name
        except (OSError, ValueError, LookupError):
            return self.name

    def run(self, path):
        module, params = spec.load(path)
        created = module.build(params)
        return f"Built {module.name} {params['name']}: {', '.join(created.values())}"

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
