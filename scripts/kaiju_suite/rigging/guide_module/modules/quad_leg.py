"""Quad Leg guide module: a four-legged animal's leg with its foot.

It's a Leg Guide (:mod:`.leg`) with one more joint in the leg: hip ->
stifle -> hock -> fetlock on the plane of its up guide, and the shared foot
(:mod:`..foot`) under the fetlock, fetlock -> hoof -> toe on a plane of its
own, with the heel, inner and outer pivots. Its layout has the Leg Guide's
keys, with four ``leg`` guides; ``foot`` is ``[hoof, toe]``::

    {"name": "L_hind", "aim": "x", "up": "y",
     "leg": [hip, stifle, hock, fetlock], "leg_up": [x, y, z],
     "foot": [hoof, toe], "foot_up": [x, y, z],
     "heel": [x, y, z], "inner": [x, y, z], "outer": [x, y, z],
     "foot_aim": "x", "foot_up_axis": "y"}
"""

from kaiju_suite.rigging.guide_module import foot, planar_chain
from kaiju_suite.rigging.guide_module.modules.leg import LegGuideModule


class QuadLegGuideModule(LegGuideModule):
    key = "quad_leg"
    name = "Quad Leg Guide"
    leg_guides = ("hip", "stifle", "hock", "fetlock")
    foot_guides = ("hoof", "toe")

    def default_layout(self, name):
        """A left hind leg standing at X 1, facing +Z, 10 tall: the stifle
        forward, the hock back, the up guide in front, and the hoof under the
        fetlock with its up guide above it. ``name`` if it can name nodes,
        else ``quad_leg``."""
        return {
            "name": name if planar_chain.NAME.match(name or "") else self.key,
            "aim": "x",
            "up": "y",
            "leg": [[1.0, 10.0, 0.0], [1.0, 7.0, 1.0], [1.0, 4.0, -1.0], [1.0, 1.0, -0.5]],
            "leg_up": [1.0, 6.0, 5.0],
            "foot": [[1.0, 0.0, 0.0], [1.0, 0.0, 1.0]],
            "foot_up": [1.0, 3.0, 0.5],
            "heel": [1.0, 0.0, -0.5],
            "inner": [0.6, 0.0, 0.5],
            "outer": [1.4, 0.0, 0.5],
            "foot_aim": "x",
            "foot_up_axis": "y",
        }


GUIDE_MODULE = QuadLegGuideModule()
