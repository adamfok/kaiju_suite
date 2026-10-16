"""BlendShapes (.bshp): blendShape nodes saved as data and rebuilt by name.

The saving and rebuilding are :mod:`kaiju_suite.datatypes.blendshape`,
shared with Kaiju Builder's BlendShapes items; this is the Assembler step.
"""

from kaiju_suite.datatypes import blendshape
from kaiju_suite.tools.assembler import data


class BlendShapeProduct(data.DataProduct):
    name = "BlendShapes"
    utility = "BlendShape Tool"
    datatype = blendshape
    order = 80
    menu_slot = (3, 2)


PRODUCT = BlendShapeProduct()
