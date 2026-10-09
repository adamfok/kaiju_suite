import pytest

from kaiju_suite.core.naming import expand_pattern, opposite_name


def test_padding_matches_hash_count():
    assert expand_pattern("arm_##_jnt", 3) == "arm_03_jnt"
    assert expand_pattern("arm_###", 12) == "arm_012"


def test_number_longer_than_padding():
    assert expand_pattern("leg_#", 10) == "leg_10"


def test_no_hash_appends_number():
    assert expand_pattern("spine", 2) == "spine2"


@pytest.mark.parametrize(
    "name, opposite",
    [
        ("L_arm_ctrl", "R_arm_ctrl"),
        ("R_arm_ctrl", "L_arm_ctrl"),
        ("arm_L_ctrl", "arm_R_ctrl"),
        ("arm_ctrl_R", "arm_ctrl_L"),
        ("l_hand", "r_hand"),
        ("left_eye", "right_eye"),
        ("eye_right", "eye_left"),
        ("leftEye", "rightEye"),
        ("eyeLeft", "eyeRight"),
        ("Right_brow", "Left_brow"),
        ("rig:L_foot", "rig:R_foot"),
        ("|grp|L_arm|L_hand", "|grp|R_arm|R_hand"),
    ],
)
def test_opposite_name_swaps_the_side(name, opposite):
    assert opposite_name(name) == opposite


@pytest.mark.parametrize("name", ["spine_ctrl", "Leg_ctrl", "LEG", "clavicle", "lid_upper", "root_LR", "Rleg"])
def test_opposite_name_is_none_without_a_side(name):
    assert opposite_name(name) is None
