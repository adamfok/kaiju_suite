import json

import pytest

from kaiju_suite.core import datafile
from kaiju_suite.tools.assembler import data


def test_write_then_read_round_trips_with_a_header(tmp_path):
    path = str(tmp_path / "a.loc")
    datafile.write(path, "locators", {"names": ["a", "b"]})
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["kaiju"] == "locators" and raw["format"] == datafile.FORMAT == 1
    assert datafile.read(path, "locators") == {"names": ["a", "b"]}


def test_write_is_deterministic(tmp_path):
    a, b = str(tmp_path / "a.loc"), str(tmp_path / "b.loc")
    datafile.write(a, "locators", {"x": 1, "y": [1.5, 2]})
    datafile.write(b, "locators", {"x": 1, "y": [1.5, 2]})
    with open(a, "rb") as fa, open(b, "rb") as fb:
        assert fa.read() == fb.read()


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[1, 2]",
        json.dumps({"kaiju": "joints", "format": 1, "data": {}}),
        json.dumps({"kaiju": "locators", "format": 99, "data": {}}),
        json.dumps({"kaiju": "locators", "data": {}}),
        json.dumps({"kaiju": "locators", "format": 1}),
    ],
)
def test_read_rejects_bad_files(tmp_path, content):
    path = tmp_path / "a.loc"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(datafile.DataFormatError) as info:
        datafile.read(str(path), "locators")
    assert "a.loc" in str(info.value)


def test_data_format_error_is_a_value_error():
    assert issubclass(datafile.DataFormatError, ValueError)


def test_assembler_data_uses_the_core_file_helpers():
    assert data.read is datafile.read
    assert data.write is datafile.write
    assert data.DataFormatError is datafile.DataFormatError
    assert data.FORMAT == datafile.FORMAT
