from kaiju_suite.core.naming import expand_pattern


def test_padding_matches_hash_count():
    assert expand_pattern("arm_##_jnt", 3) == "arm_03_jnt"
    assert expand_pattern("arm_###", 12) == "arm_012"


def test_number_longer_than_padding():
    assert expand_pattern("leg_#", 10) == "leg_10"


def test_no_hash_appends_number():
    assert expand_pattern("spine", 2) == "spine2"
