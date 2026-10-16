"""What the release download holds: .gitattributes marks developer files
export-ignore, so GitHub's source zip (git archive) has only what Maya needs."""

import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SHIPPED = [
    "kaiju_suite.mod",
    "README.md",
    "CHANGELOG.md",
    "scripts/kaiju_suite/__init__.py",
    "plug-ins/kaiju_suite_plugin.py",
    "install/drag_and_drop.py",
    "icons/qc_fix.svg",
]
LEFT_OUT = [
    "tests/test_release_archive.py",
    "dev/use-worktree.ps1",
    "docs/tool-ideas.md",
    "CLAUDE.md",
    ".gitignore",
    ".gitattributes",
]

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def _export_ignored(path):
    out = subprocess.run(
        ["git", "check-attr", "export-ignore", "--", path], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return out.strip().endswith(": set")


@pytest.mark.parametrize("path", SHIPPED)
def test_what_maya_needs_is_in_the_download(path):
    assert os.path.exists(os.path.join(ROOT, path))
    assert not _export_ignored(path)


@pytest.mark.parametrize("path", LEFT_OUT)
def test_developer_files_are_left_out_of_the_download(path):
    assert _export_ignored(path)
