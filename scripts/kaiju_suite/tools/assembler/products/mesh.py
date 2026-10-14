"""Mesh (.mesh): polygon meshes saved as data and rebuilt as new meshes.

The saving and rebuilding are :mod:`kaiju_suite.datatypes.mesh`, shared
with the other tools; this is the Assembler step.
"""

from kaiju_suite.datatypes import mesh
from kaiju_suite.tools.assembler import data


class MeshProduct(data.DataProduct):
    name = "Mesh"
    utility = "Mesh Tool"
    datatype = mesh
    order = 50
    menu_slot = (2, 0)


PRODUCT = MeshProduct()
