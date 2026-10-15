"""ControlShape (.ctrl): the NURBS curve shapes of controls, saved and swapped back in.

The saving and swapping are :mod:`kaiju_suite.datatypes.controlshape`,
shared with the other tools; this is the Assembler step.
"""

from kaiju_suite.datatypes import controlshape
from kaiju_suite.tools.assembler import data


class ControlShapeProduct(data.DataProduct):
    name = "ControlShape"
    utility = "ControlShape Tool"
    datatype = controlshape
    order = 120
    menu_slot = (2, 2)


PRODUCT = ControlShapeProduct()
