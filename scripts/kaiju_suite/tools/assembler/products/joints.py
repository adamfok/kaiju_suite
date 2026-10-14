"""Joints (.jnt): a skeleton saved as data and rebuilt as new joints.

The saving and rebuilding are :mod:`kaiju_suite.datatypes.joints`, shared
with the other tools; this is the Assembler step.
"""

from kaiju_suite.datatypes import joints
from kaiju_suite.tools.assembler import data


class JointsProduct(data.DataProduct):
    name = "Joints"
    utility = "Joint Tool"
    datatype = joints
    order = 40
    menu_slot = (2, 1)


PRODUCT = JointsProduct()
