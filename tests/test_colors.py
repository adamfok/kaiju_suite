import pytest

from kaiju_suite.core import colors


def test_colors_are_maya_index_colors_with_their_rgb():
    assert list(colors.COLORS) == list(range(32))
    assert colors.color_rgb(13) == pytest.approx((1.0, 0.0, 0.0))
    assert colors.color_rgb(17) == pytest.approx((1.0, 1.0, 0.0))
    assert len(colors.color_rgb(0)) == 3
