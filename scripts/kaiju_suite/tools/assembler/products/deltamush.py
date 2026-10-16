"""DeltaMush (.dmsh): deltaMush deformers saved as data and rebuilt on their meshes.

The saving and rebuilding are :mod:`kaiju_suite.datatypes.deltamush`,
shared with Kaiju Builder's DeltaMush items; this is the Assembler step.
"""

from kaiju_suite.datatypes import deltamush
from kaiju_suite.datatypes.deltamush import _geometry_index, _mesh_transforms, _shape  # noqa: F401 (products/wrap.py uses them)
from kaiju_suite.tools.assembler import data


class DeltaMushProduct(data.DataProduct):
    name = "DeltaMush"
    utility = "DeltaMush Tool"
    datatype = deltamush
    order = 70
    menu_slot = (3, 1)


PRODUCT = DeltaMushProduct()
