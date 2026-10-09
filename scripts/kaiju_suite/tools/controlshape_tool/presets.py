"""Built-in control shapes, as curve records (see :mod:`kaiju_suite.core.curves`).

Each preset is a list of records, one per curve shape, about the origin
and about one unit in size. Flat shapes lie in the XZ plane, facing +Y;
arrows point along +Z. No Maya calls here.
"""

import math

# Maya's own radius-1 circle: 8 CVs on a periodic cubic.
_C = 0.783612
_R = 1.108194
_CIRCLE = [(_C, -_C), (0, -_R), (-_C, -_C), (-_R, 0), (-_C, _C), (0, _R), (_C, _C), (_R, 0)]


def _linear(points):
    return {"degree": 1, "form": 0, "knots": list(range(len(points))), "cvs": [list(map(float, p)) for p in points]}


def _periodic(points, degree=3):
    """A closed smooth curve through (near) ``points``; the first ``degree``
    CVs repeat at the end, as Maya stores them."""
    count = len(points)
    cvs = [list(map(float, p)) for p in points + points[:degree]]
    return {"degree": degree, "form": 2, "knots": list(range(-(degree - 1), count + degree)), "cvs": cvs}


def _circle(plane="xz", radius=1.0, offset=0.0):
    """A circle in ``plane`` ("xz", "xy" or "yz"), moved ``offset`` along
    the third axis."""
    points = []
    for a, b in _CIRCLE:
        a, b = a * radius, b * radius
        points.append({"xz": (a, offset, b), "xy": (a, b, offset), "yz": (offset, a, b)}[plane])
    return _periodic(points)


def _closed(points):
    return _linear(points + points[:1])


def _star(tips=5, outer=1.0, inner=0.4):
    points = []
    for i in range(tips * 2):
        angle = math.pi * i / tips
        radius = outer if i % 2 == 0 else inner
        points.append((radius * math.sin(angle), 0, radius * math.cos(angle)))
    return _closed(points)


def _arc(points=9):
    """Half a circle on +Z, closed by its diameter."""
    arc = [(math.cos(math.pi * i / (points - 1)), 0, math.sin(math.pi * i / (points - 1))) for i in range(points)]
    return _closed(arc)


_W = 0.33  # half the width of arrow shafts and cross arms

BUILT_IN = {
    "circle": [_circle()],
    "square": [_closed([(-1, 0, -1), (1, 0, -1), (1, 0, 1), (-1, 0, 1)])],
    "triangle": [_closed([(0, 0, 1), (0.866, 0, -0.5), (-0.866, 0, -0.5)])],
    "half_circle": [_arc()],
    "star": [_star()],
    "cross": [
        _closed([
            (-_W, 0, -1), (_W, 0, -1), (_W, 0, -_W), (1, 0, -_W), (1, 0, _W), (_W, 0, _W),
            (_W, 0, 1), (-_W, 0, 1), (-_W, 0, _W), (-1, 0, _W), (-1, 0, -_W), (-_W, 0, -_W),
        ])
    ],
    "arrow": [_closed([(-_W, 0, -1), (_W, 0, -1), (_W, 0, 0), (0.66, 0, 0), (0, 0, 1), (-0.66, 0, 0), (-_W, 0, 0)])],
    "double_arrow": [
        _closed([
            (0, 0, -1), (0.66, 0, -0.33), (_W, 0, -0.33), (_W, 0, 0.33), (0.66, 0, 0.33),
            (0, 0, 1), (-0.66, 0, 0.33), (-_W, 0, 0.33), (-_W, 0, -0.33), (-0.66, 0, -0.33),
        ])
    ],
    "four_arrows": [
        _closed([
            (0, 0, 1), (0.4, 0, 0.6), (0.15, 0, 0.6), (0.15, 0, 0.15), (0.6, 0, 0.15), (0.6, 0, 0.4),
            (1, 0, 0), (0.6, 0, -0.4), (0.6, 0, -0.15), (0.15, 0, -0.15), (0.15, 0, -0.6), (0.4, 0, -0.6),
            (0, 0, -1), (-0.4, 0, -0.6), (-0.15, 0, -0.6), (-0.15, 0, -0.15), (-0.6, 0, -0.15), (-0.6, 0, -0.4),
            (-1, 0, 0), (-0.6, 0, 0.4), (-0.6, 0, 0.15), (-0.15, 0, 0.15), (-0.15, 0, 0.6), (-0.4, 0, 0.6),
        ])
    ],
    "cube": [
        _linear([
            (-1, 1, 1), (1, 1, 1), (1, 1, -1), (-1, 1, -1), (-1, 1, 1),
            (-1, -1, 1), (1, -1, 1), (1, 1, 1), (1, -1, 1), (1, -1, -1),
            (1, 1, -1), (1, -1, -1), (-1, -1, -1), (-1, 1, -1), (-1, -1, -1), (-1, -1, 1),
        ])
    ],
    "sphere": [_circle("xz"), _circle("xy"), _circle("yz")],
    "cylinder": [
        _circle("xz", offset=0.5),
        _circle("xz", offset=-0.5),
        *(_linear([(x, 0.5, z), (x, -0.5, z)]) for x, z in ((1, 0), (-1, 0), (0, 1), (0, -1))),
    ],
    "diamond": [
        _linear([(0, 1, 0), (1, 0, 0), (0, -1, 0), (-1, 0, 0), (0, 1, 0), (0, 0, 1), (0, -1, 0), (0, 0, -1), (0, 1, 0)]),
        _closed([(1, 0, 0), (0, 0, 1), (-1, 0, 0), (0, 0, -1)]),
    ],
    "pyramid": [
        _linear([(-1, 0, -1), (1, 0, -1), (1, 0, 1), (-1, 0, 1), (-1, 0, -1), (0, 1.4, 0), (1, 0, -1)]),
        _linear([(1, 0, 1), (0, 1.4, 0), (-1, 0, 1)]),
    ],
    "pin": [_linear([(0, 0, 0), (0, 0.7, 0)]), _closed([(-0.2, 0.7, 0), (0, 0.9, 0), (0.2, 0.7, 0), (0, 0.5, 0)])],
    "locator": [_linear([(-1, 0, 0), (1, 0, 0)]), _linear([(0, -1, 0), (0, 1, 0)]), _linear([(0, 0, -1), (0, 0, 1)])],
}  # fmt: skip


# -- previews ---------------------------------------------------------------


def _point_on(record, knots, t):
    """The point at parameter ``t`` of ``record``'s curve (de Boor)."""
    degree, cvs = record["degree"], record["cvs"]
    span = degree
    while span < len(cvs) - 1 and knots[span + 1] <= t:
        span += 1
    points = [list(cvs[span - degree + j]) for j in range(degree + 1)]
    for r in range(1, degree + 1):
        for j in range(degree, r - 1, -1):
            low, high = knots[span - degree + j], knots[span + 1 + j - r]
            alpha = (t - low) / (high - low) if high != low else 0.0
            points[j] = [(1 - alpha) * a + alpha * b for a, b in zip(points[j - 1], points[j])]
    return points[degree]


def outline(records, samples=12):
    """Each record's curve as a list of points, ``samples`` per span, to
    draw a preview (a linear curve is just its CVs)."""
    lines = []
    for record in records:
        if record["degree"] == 1:
            lines.append([list(p) for p in record["cvs"]])
            continue
        # Maya leaves out the first and last knots; they're never used here.
        knots = [record["knots"][0], *record["knots"], record["knots"][-1]]
        start, end = knots[record["degree"]], knots[len(record["cvs"])]
        steps = samples * (len(record["cvs"]) - record["degree"])
        lines.append([_point_on(record, knots, start + (end - start) * i / steps) for i in range(steps + 1)])
    return lines
