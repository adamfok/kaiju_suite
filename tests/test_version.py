"""The version: kept in scripts/kaiju_suite/__init__.py, copied into kaiju_suite.mod
and given a section in CHANGELOG.md."""

import os
import re

import kaiju_suite

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def test_the_mod_file_has_the_same_version_on_every_line():
    lines = [line.split() for line in _read("kaiju_suite.mod").splitlines() if line.startswith("+")]

    assert lines
    assert {line[3] for line in lines} == {kaiju_suite.__version__}


def test_the_changelog_has_a_section_for_this_version():
    assert re.search(rf"^## {re.escape(kaiju_suite.__version__)}\b", _read("CHANGELOG.md"), re.M)
