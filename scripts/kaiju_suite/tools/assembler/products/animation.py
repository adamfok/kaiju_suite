"""Animation (.anim): keyframes saved as data and put back on the same attributes.

The saving and applying are :mod:`kaiju_suite.datatypes.animation`, shared
with the other tools; this is the Assembler step.
"""

from kaiju_suite.datatypes import animation
from kaiju_suite.tools.assembler import data


class AnimationProduct(data.DataProduct):
    name = "Animation"
    utility = "Animation Tool"
    datatype = animation
    order = 110
    menu_slot = (4, 1)


PRODUCT = AnimationProduct()
