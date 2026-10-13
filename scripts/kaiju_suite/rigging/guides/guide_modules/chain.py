"""Chain guide module: one planar chain (:mod:`..planar_chain`), as the
Guide Tool builds it.

Its layout is the chain's name, its aim and up axes, and the world
position of every guide (start, middles, end, as placed, before they're
projected onto the chain's plane) and of its up guide::

    {"name": "L_arm", "aim": "x", "up": "y",
     "guides": [[0, 0, 0], [5, 0, 0], [10, 0, 0]], "up_guide": [5, 5, 0]}
"""

from maya import cmds

from kaiju_suite.core.naming import mirrored_name
from kaiju_suite.rigging.guides import planar_chain
from kaiju_suite.rigging.guides.guide_module import GuideModule

_KEYS = ("name", "aim", "up", "guides", "up_guide")


def _is_point(value):
    return (
        isinstance(value, (list, tuple))
        and len(value) == 3
        and all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in value)
    )


def _flipped(axis):
    return axis[1:] if axis.startswith("-") else f"-{axis}"


def _flip_x(point):
    # + 0.0 keeps 0 from turning into -0.0.
    return [-point[0] + 0.0, point[1], point[2]]


class ChainGuideModule(GuideModule):
    key = "chain"
    name = "Chain Guide"

    def default_layout(self, name):
        """A straight chain along X from the origin, 10 long, with one middle
        guide and the up guide above it. ``name`` if it can name nodes, else
        ``chain``."""
        return {
            "name": name if planar_chain.NAME.match(name or "") else self.key,
            "aim": "x",
            "up": "y",
            "guides": [[0.0, 0.0, 0.0], [5.0, 0.0, 0.0], [10.0, 0.0, 0.0]],
            "up_guide": [5.0, 5.0, 0.0],
        }

    def check(self, layout):
        missing = [k for k in _KEYS if k not in layout]
        if missing:
            return [f"The {self.name} layout is missing {', '.join(missing)}."]
        name = layout["name"]
        points = layout["guides"]
        if not isinstance(points, list) or not all(_is_point(p) for p in points) or not _is_point(layout["up_guide"]):
            return [f"{name}: guides and up_guide must be [x, y, z] positions."]
        if isinstance(name, str) and cmds.objExists(f"{name}_guides_grp"):
            return [f"Guides already in the scene: {name}. Delete them first."]
        try:
            planar_chain.check_build(name, points, layout["up_guide"], layout["aim"], layout["up"])
        except ValueError as e:
            return [f"{name}: {e}"]
        return []

    def create(self, layout):
        return planar_chain.build_at(
            layout["name"], layout["guides"], layout["up_guide"], layout["aim"], layout["up"]
        )

    def layout(self, group):
        return planar_chain.layout(group)

    def describe(self, layout):
        count = len(layout["guides"])
        return [f"{layout['name']}: {count} guide{'s' if count != 1 else ''}, aim {layout['aim']}, up {layout['up']}"]

    def fields(self, layout):
        """What the Guide Tool's window shows for ``layout``: ``{"name",
        "count"`` (middle guides) ``, "aim", "up"}``."""
        return {
            "name": layout["name"],
            "count": len(layout["guides"]) - 2,
            "aim": layout["aim"],
            "up": layout["up"],
        }

    def mirrored(self, layout):
        """``layout`` for the other side: the chain renamed with
        :func:`~kaiju_suite.core.naming.mirrored_name` (``L_arm`` -> ``R_arm``,
        ``tail`` -> ``tail_mirrored``), its guides flipped across X (the YZ
        plane) and its aim and up axes reversed. Built, its joints come out as
        Maya's Behavior mirror makes them, so the same rotations move both
        sides in mirror image. Mirroring twice gives ``layout`` back."""
        return {
            **layout,
            "name": mirrored_name(layout["name"]),
            "aim": _flipped(layout["aim"]),
            "up": _flipped(layout["up"]),
            "guides": [_flip_x(p) for p in layout["guides"]],
            "up_guide": _flip_x(layout["up_guide"]),
        }


GUIDE_MODULE = ChainGuideModule()
