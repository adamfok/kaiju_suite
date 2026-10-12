"""Republish on a folder: publish every item under it again from the scene
objects named in its file (see ``Product.republish``), then publish the
folder, so its version records the new item versions.

Items that can't be republished now (objects missing from the scene, or
matching several nodes) are skipped; :func:`problems` lists them first so
the user can cancel. No Qt here.
"""

import os

from kaiju_suite.datatypes import plural
from kaiju_suite.tools.assembler import versions
from kaiju_suite.tools.assembler.products import product_for


def _rel(folder, path):
    return os.path.relpath(path, folder).replace(os.sep, "/")


def targets(folder):
    """The items under ``folder`` (subfolders too) to republish: published
    items whose product can republish them. Others are skipped."""
    found = []
    for _, path in versions.walk(folder):
        if not os.path.isfile(path):
            continue
        product = product_for(path)
        if product.republishable(path) and versions.list_versions(path):
            found.append(path)
    return found


def can_republish(folder):
    """Whether ``folder`` holds anything to republish."""
    return bool(targets(folder))


def problems(folder):
    """``(relative path, messages)`` for each target that can't be republished now."""
    found = []
    for path in targets(folder):
        messages = product_for(path).republish_problems(path)
        if messages:
            found.append((_rel(folder, path), messages))
    return found


def problem_lines(grouped):
    """:func:`problems` as text lines: each item, then its messages indented."""
    lines = []
    for rel, messages in grouped:
        lines.append(rel)
        lines.extend(f"    {m}" for m in messages)
    return lines


def republish_folder(folder):
    """Republish every target under ``folder`` that has no problems, skip the
    rest, then publish ``folder``. Content that hasn't changed adds no
    version. Returns a message. Raises, changing nothing, if there's nothing
    to republish or every target has problems.

    Run it inside ``versions.describing`` to describe every version it saves.
    """
    name = os.path.basename(folder)
    paths = targets(folder)
    if not paths:
        raise RuntimeError(f"Nothing to republish in {name}: no published items that can be republished.")
    blocked = dict(problems(folder))
    ready = [p for p in paths if _rel(folder, p) not in blocked]
    if not ready:
        raise RuntimeError(f"Can't republish anything in {name}.\n" + "\n".join(problem_lines(blocked.items())))

    changed, unchanged, failed = 0, 0, []
    for path in ready:
        before = len(versions.list_versions(path))
        try:
            product_for(path).republish(path)
        except Exception as e:
            failed.append(f"{_rel(folder, path)} ({e})")
            continue
        if len(versions.list_versions(path)) > before:
            changed += 1
        else:
            unchanged += 1

    message = f"Republished {plural(changed + unchanged, 'item')} in {name}: {changed} changed, {unchanged} unchanged."
    if blocked:
        message += f" Skipped {len(blocked)} with missing objects: {', '.join(blocked)}."
    if failed:
        message += f" Failed: {', '.join(failed)}."
    try:
        message += " " + versions.publish(folder)
    except ValueError as e:
        message += f" Didn't publish {name}: {e}"
    return message
