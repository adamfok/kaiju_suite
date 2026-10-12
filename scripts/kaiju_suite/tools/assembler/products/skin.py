"""SkinCluster (.skin): skin weights saved as data and bound back by name.

The saving and binding are :mod:`kaiju_suite.datatypes.skin`, shared with
the SkinCluster Tool's Export/Import Weights; this is the Assembler step.
"""

from kaiju_suite.datatypes import skin
from kaiju_suite.tools.assembler import data


class SkinProduct(data.DataProduct):
    name = "SkinCluster"
    utility = "SkinCluster Tool"
    datatype = skin
    order = 60
    menu_slot = (3, 0)


PRODUCT = SkinProduct()
