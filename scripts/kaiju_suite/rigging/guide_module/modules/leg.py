"""Leg guide module: a biped leg with its foot.

The leg is a planar chain (:mod:`..planar_chain`), hip -> knee -> ankle,
on the plane of its up guide (like a pole vector). The foot (:mod:`..foot`)
hangs under the ankle: ankle -> ball -> toe on a plane of its own, sharing
the ankle guide, plus the heel, inner and outer pivots of the reverse
foot. The foot is part of the leg, not a guide module of its own: they
share the ankle, and the foot roll drives the leg IK, so a leg rig module
needs both.

Its layout is the leg's name, the leg's and the foot's aim and up axes
and world positions::

    {"name": "L_leg", "aim": "x", "up": "y",
     "leg": [hip, knee, ankle], "leg_up": [x, y, z],
     "foot": [ball, toe], "foot_up": [x, y, z],
     "heel": [x, y, z], "inner": [x, y, z], "outer": [x, y, z],
     "foot_aim": "x", "foot_up_axis": "y"}

Leg layouts saved before the foot had its own axes have no ``foot_aim``
and ``foot_up_axis``: their foot takes the leg's.

Its top group is the leg chain's guide group, ``<name>_guides_grp``; the
foot's is under it.
"""

from maya import cmds

from kaiju_suite.core.naming import mirrored_name
from kaiju_suite.rigging.guide_module import foot, planar_chain
from kaiju_suite.rigging.guide_module.guide_module import GuideModule, flip_x, flipped_axis, is_point

_KEYS = ("name", "aim", "up", "leg", "leg_up") + foot.KEYS
_LISTS = ("leg", "foot")
_POINTS = ("leg_up", "foot_up") + foot.PIVOTS


class LegGuideModule(GuideModule):
    key = "leg"
    name = "Leg Guide"

    def default_layout(self, name):
        """A left leg standing at X 1, facing +Z, 9 tall: the knee bent a
        little forward with the up guide in front of it, the foot flat on the
        ground with its up guide above the ball. ``name`` if it can name
        nodes, else ``leg``."""
        return {
            "name": name if planar_chain.NAME.match(name or "") else self.key,
            "aim": "x",
            "up": "y",
            "leg": [[1.0, 9.0, 0.0], [1.0, 5.0, 0.5], [1.0, 1.0, 0.0]],
            "leg_up": [1.0, 5.0, 5.0],
            "foot": [[1.0, 0.0, 1.5], [1.0, 0.0, 3.0]],
            "foot_up": [1.0, 3.0, 1.5],
            "heel": [1.0, 0.0, -0.5],
            "inner": [0.5, 0.0, 1.5],
            "outer": [1.5, 0.0, 1.5],
            "foot_aim": "x",
            "foot_up_axis": "y",
        }

    def _shape_problems(self, layout):
        """Problems with the keys and positions of ``layout``, as messages."""
        missing = [k for k in _KEYS if k not in layout]
        if missing:
            return [f"The {self.name} layout is missing {', '.join(missing)}."]
        name = layout["name"]
        lists_ok = all(isinstance(layout[k], list) and all(is_point(p) for p in layout[k]) for k in _LISTS)
        if not lists_ok or not all(is_point(layout[k]) for k in _POINTS):
            return [f"{name}: every guide must be an [x, y, z] position."]
        if len(layout["leg"]) != 3:
            return [f"{name}: leg needs 3 guides (hip, knee, ankle)."]
        if len(layout["foot"]) != 2:
            return [f"{name}: foot needs 2 guides (ball, toe)."]
        return []

    def check(self, layout):
        problems = self._shape_problems(layout)
        if problems:
            return problems
        name, aim, up = layout["name"], layout["aim"], layout["up"]
        if isinstance(name, str) and cmds.objExists(f"{name}_guides_grp"):
            return [f"Guides already in the scene: {name}. Delete them first."]
        try:
            planar_chain.check_build(name, layout["leg"], layout["leg_up"], aim, up)
        except ValueError as e:
            return [f"{name}: {e}"]
        return foot.problems(name, layout["leg"][-1], layout)

    def create(self, layout):
        name, aim, up = layout["name"], layout["aim"], layout["up"]
        group = planar_chain.build_at(name, layout["leg"], layout["leg_up"], aim, up)
        foot.build(group, name, layout)
        return group

    def layout(self, group):
        chain = planar_chain.layout(group)
        return {
            "name": chain["name"],
            "aim": chain["aim"],
            "up": chain["up"],
            "leg": chain["guides"],
            "leg_up": chain["up_guide"],
            **foot.layout(group),
        }

    def reset(self, group, layout):
        problems = self._shape_problems(layout)
        if problems:
            raise ValueError(problems[0])
        # Check both chains first: setting the leg, then failing on the foot, would change something.
        planar_chain.check_axes(layout["aim"], layout["up"])
        planar_chain.planar_positions(layout["leg"], layout["leg_up"])
        foot.check(layout, layout["leg"][-1])
        foot.pivots(group)
        group = planar_chain.set_layout(group, layout["leg"], layout["leg_up"], layout["aim"], layout["up"])
        foot.reset(group, layout)
        return group

    def fields(self, layout):
        """What the Guide Module Editor shows for ``layout``: its name, and
        Aim and Up for the leg and for the foot (no # Mid)."""
        foot_aim, foot_up = foot.axes(layout)
        return {
            "name": layout["name"],
            "axes": [
                {"part": "leg", "label": "Leg", "aim": layout["aim"], "up": layout["up"]},
                {"part": "foot", "label": "Foot", "aim": foot_aim, "up": foot_up},
            ],
        }

    def set_axes(self, group, part, aim, up):
        """Turn the ``"leg"`` or the ``"foot"`` joints."""
        if part == "foot":
            foot.set_axes(group, aim, up)
        elif part == "leg":
            planar_chain.set_axes(group, aim, up)
        else:
            raise ValueError(f"A {self.name} has no {part!r} axes: use 'leg' or 'foot'.")

    def check_extract(self, group):
        try:
            foot.pivots(group)
        except ValueError as e:
            return [str(e)]
        return planar_chain.extract_problems(group)

    def delete(self, group):
        """Extract the leg's joints, then the foot's (see
        :func:`~..planar_chain.delete_guides`). The pivots go with the guides."""
        return planar_chain.delete_guides(group)

    def describe(self, layout):
        foot_aim, foot_up = foot.axes(layout)
        return [
            f"{layout['name']}: hip, knee, ankle, ball, toe; heel, inner and outer pivots; "
            f"leg aim {layout['aim']}, up {layout['up']}; foot aim {foot_aim}, up {foot_up}"
        ]

    def mirrored(self, layout):
        """``layout`` for the other side: renamed with
        :func:`~kaiju_suite.core.naming.mirrored_name` (``L_leg`` -> ``R_leg``),
        every guide flipped across X and the leg's and foot's axes reversed, so the joints
        come out as Maya's Behavior mirror makes them, as Chain Guide's do.
        Mirroring twice gives ``layout`` back."""
        return {
            **layout,
            "name": mirrored_name(layout["name"]),
            "aim": flipped_axis(layout["aim"]),
            "up": flipped_axis(layout["up"]),
            "leg": [flip_x(p) for p in layout["leg"]],
            "leg_up": flip_x(layout["leg_up"]),
            **foot.mirrored(layout),
        }


GUIDE_MODULE = LegGuideModule()
