"""Guide layouts: where one chain's guides are, saved as data and built
again as live guides (:mod:`kaiju_suite.core.guides`).

A file holds one chain: its name, its aim and up axes, the world position of
every guide (start, middles, end, as placed, before they're projected onto
the chain's plane) and of its up guide. Applying builds the guides and a
joint chain that follows them live; it never changes guides that are
already in the scene, and stops if the chain's names are taken.
"""

from maya import cmds

from kaiju_suite.core import guides
from kaiju_suite.core.naming import mirrored_name
from kaiju_suite.core.selection import short_name

KIND = "guides"
EXTENSION = ".guide"
_NOTHING = "Nothing selected. Select guides, a guide group or a joint they drive."


def gather(nodes):
    if not nodes:
        raise ValueError(_NOTHING)
    return guides.layout(guides.find_group(nodes))


def _summary(payload):
    count = len(payload["guides"])
    return f"{payload['name']}: {count} guide{'s' if count != 1 else ''}, aim {payload['aim']}, up {payload['up']}"


def apply(payload, info=None):
    name = payload["name"]
    if cmds.objExists(f"{name}_guides_grp"):
        raise RuntimeError(f"Guides already in the scene: {name}. Delete them first.")
    args = (name, payload["guides"], payload["up_guide"], payload["aim"], payload["up"])
    try:
        guides.check_build(*args)
    except ValueError as e:
        raise RuntimeError(f"{name}: {e}") from None
    guides.build_at(*args)
    return f"Built guides for {_summary(payload)}"


def selection_problems(selection):
    if not selection:
        return [_NOTHING]
    problems = []
    for node in selection:
        try:
            guides.guide_group(node)
        except ValueError:
            problems.append(f"{short_name(node)} isn't a guide, a guide group or a joint built from guides.")
    if problems:
        return problems
    try:
        guides.find_group(selection)
    except ValueError as e:
        return [str(e)]
    return []


def describe(payload):
    return [_summary(payload)]


def nodes(payload):
    return [f"{payload['name']}_guides_grp"]


def fields(payload):
    """What the Guide Tool's window shows for ``payload``: ``{"name",
    "count"`` (middle guides) ``, "aim", "up"}``."""
    return {
        "name": payload["name"],
        "count": len(payload["guides"]) - 2,
        "aim": payload["aim"],
        "up": payload["up"],
    }


def _flipped(axis):
    return axis[1:] if axis.startswith("-") else f"-{axis}"


def _flip_x(point):
    # + 0.0 keeps 0 from turning into -0.0.
    return [-point[0] + 0.0, point[1], point[2]]


def mirrored(payload):
    """``payload`` for the other side: the chain renamed with
    :func:`~kaiju_suite.core.naming.mirrored_name` (``L_arm`` -> ``R_arm``,
    ``tail`` -> ``tail_mirrored``), its guides flipped across X (the YZ
    plane) and its aim and up axes reversed. Built, its joints come out as
    Maya's Behavior mirror makes them, so the same rotations move both
    sides in mirror image. Mirroring twice gives ``payload`` back."""
    return {
        **payload,
        "name": mirrored_name(payload["name"]),
        "aim": _flipped(payload["aim"]),
        "up": _flipped(payload["up"]),
        "guides": [_flip_x(p) for p in payload["guides"]],
        "up_guide": _flip_x(payload["up_guide"]),
    }
