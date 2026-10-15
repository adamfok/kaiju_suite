"""Pose (.pose): attribute values saved from the selection and set back.

The saving and setting back are :mod:`kaiju_suite.datatypes.pose`, shared
with the other tools; this is the Assembler step.
"""

from kaiju_suite.datatypes import pose
from kaiju_suite.tools.assembler import data


class PoseProduct(data.DataProduct):
    name = "Pose"
    utility = "Pose Tool"
    datatype = pose
    order = 100
    menu_slot = (4, 0)


PRODUCT = PoseProduct()
