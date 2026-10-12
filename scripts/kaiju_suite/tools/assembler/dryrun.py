"""Dry run: check a build folder's node references before anything is built.

Goes through the items a Run would (enabled and runnable, in build order)
and reports every node an item needs (e.g. a Rig Module's parent or joints)
that is neither in the scene nor made by an earlier item. Products say what
an item needs and makes through ``Product.node_refs`` and
``Product.outputs``; items whose product can't say what it makes (Scripts,
Import Scenes, Joints, ...) are named in the message, since they might make it.
Changes nothing in the scene. No Qt here.
"""

import os

from maya import cmds

from kaiju_suite.tools.assembler import logic
from kaiju_suite.tools.assembler.products import product_for


def problems(folder):
    """Every missing node under ``folder``, as messages naming the item by
    its path in ``folder``, e.g. ``arms/L_arm.rig: Parent 'main_offset_ctrl'
    isn't in the scene, and no earlier item makes it.`` Empty if none."""
    steps = []  # (label, product, path)
    for path in logic.collect_steps(folder):
        label = os.path.relpath(path, folder).replace(os.sep, "/")
        steps.append((label, product_for(path), path))

    found = []
    outputs = []  # each step's outputs, or None if it can't say
    for label, product, path in steps:
        try:
            outputs.append(product.outputs(path))
        except (OSError, ValueError, LookupError) as e:
            found.append(f"{label}: {e}")
            outputs.append(None)

    made = {}  # name -> the step index that makes it first
    for index, made_by in enumerate(outputs):
        for name in made_by or ():
            made.setdefault(name, index)

    for index, (label, product, path) in enumerate(steps):
        try:
            refs = product.node_refs(path)
        except (OSError, ValueError, LookupError):
            continue  # already reported
        for ref_label, name in refs:
            if cmds.objExists(name) or made.get(name, index) < index:
                continue
            found.append(f"{label}: {ref_label} {name!r} {_why(name, index, steps, outputs, made)}")
    return found


def _why(name, index, steps, outputs, made):
    later = made.get(name)
    if later is not None and later > index:
        return f"is made by a later item, {steps[later][0]}; move {steps[index][0]} below it."
    unknown = [steps[i][0] for i in range(index) if outputs[i] is None]
    if not unknown:
        return "isn't in the scene, and no earlier item makes it."
    might = ", ".join(unknown)
    say = "it can't say what it makes" if len(unknown) == 1 else "they can't say what they make"
    return f"isn't in the scene, and no earlier Rig Module item makes it ({might} might: {say})."
