"""Curves (.crv): NURBS curves that aren't controls, saved as data and rebuilt
as new curves (guide curves for Spline IK, wire deformer curves, ...).

The saving and rebuilding are :mod:`kaiju_suite.datatypes.curves`, shared
with the other tools; this is the Assembler step. It keeps the ``.crv``
extension its items always had (Builder's NurbsCurve items use the
datatype's ``.curve``; the contents are the same).
"""

from kaiju_suite.datatypes import curves
from kaiju_suite.tools.assembler import data


class CurvesProduct(data.DataProduct):
    name = "Curves"
    datatype = curves
    extension = ".crv"
    order = 55
    menu_slot = (2, 3)


PRODUCT = CurvesProduct()
