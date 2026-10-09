import json
import os

import pytest

from kaiju_suite import rig
from kaiju_suite.core import datafile
from kaiju_suite.rig import spec
from kaiju_suite.rig.module import Param, RigModule


class _Box(RigModule):
    key = "box"
    name = "Box Module"
    params = (
        Param("name", "Name", "string", "box", required=True),
        Param("size", "Size", "float", 1.0),
        Param("side", "Side", "choice", "L", choices=("L", "R")),
        Param("target", "Target", "node", ""),
    )


# -- the registry -----------------------------------------------------------


def test_simple_ik_is_discovered():
    assert rig.get("simple_ik").name == "Simple IK"
    assert "simple_ik" in [module.key for module in rig.all_modules()]


def test_get_rejects_an_unknown_module():
    with pytest.raises(LookupError) as info:
        rig.get("nope")
    assert "nope" in str(info.value)


def test_rig_package_imports_no_qt_tools_or_ui():
    root = os.path.dirname(rig.__file__)
    for folder, _dirs, files in os.walk(root):
        for file_name in files:
            if not file_name.endswith(".py"):
                continue
            with open(os.path.join(folder, file_name), encoding="utf-8") as f:
                source = f.read()
            for banned in ("PySide", "kaiju_suite.tools", "kaiju_suite.ui"):
                assert banned not in source, f"{file_name} mentions {banned}"


# -- the module base class -------------------------------------------------


def test_defaults_come_from_the_params():
    assert _Box().defaults() == {"name": "box", "size": 1.0, "side": "L", "target": ""}


def test_complete_fills_missing_params_and_keeps_unknown_ones():
    assert _Box().complete({"size": 2.0, "extra": 1}) == {
        "name": "box",
        "size": 2.0,
        "side": "L",
        "target": "",
        "extra": 1,
    }


def test_problems_report_required_and_bad_choices():
    problems = _Box().problems({"name": " ", "side": "X"})

    assert any("Name" in p for p in problems)
    assert any("Side" in p and "X" in p for p in problems)


def test_problems_report_a_number_that_is_not_one():
    assert any("Size" in p for p in _Box().problems({"size": "big"}))


def test_build_refuses_params_with_problems(new_scene):
    with pytest.raises(ValueError) as info:
        _Box().build({"name": ""})
    assert "Name" in str(info.value)


# -- parameter files --------------------------------------------------------


def test_spec_round_trips(tmp_path):
    path = str(tmp_path / "L_arm.rig")
    spec.write(path, "simple_ik", {"name": "L_arm"})

    assert spec.read(path) == ("simple_ik", {"name": "L_arm"})
    assert datafile.read(path, spec.KIND) == {"module": "simple_ik", "params": {"name": "L_arm"}}


def test_load_completes_the_params_with_defaults(tmp_path):
    path = str(tmp_path / "L_arm.rig")
    spec.write(path, "simple_ik", {"name": "L_arm"})

    module, params = spec.load(path)

    assert module is rig.get("simple_ik")
    assert params["name"] == "L_arm"
    assert params["pole_distance"] == 5.0


@pytest.mark.parametrize(
    "payload",
    [[1], {"params": {}}, {"module": 3, "params": {}}, {"module": "simple_ik", "params": []}],
)
def test_read_rejects_a_malformed_spec(tmp_path, payload):
    path = tmp_path / "bad.rig"
    path.write_text(json.dumps({"kaiju": spec.KIND, "format": 1, "data": payload}), encoding="utf-8")

    with pytest.raises(datafile.DataFormatError) as info:
        spec.read(str(path))
    assert "bad.rig" in str(info.value)


def test_load_rejects_an_unknown_module(tmp_path):
    path = str(tmp_path / "x.rig")
    spec.write(path, "nope", {})

    with pytest.raises(LookupError):
        spec.load(path)
