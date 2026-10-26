"""dev/hooks/pre-push: refuses pushes to main and runs the test suite before any other push.

Each test builds a throwaway clone of a bare repo with the real hook turned on,
and a fake mayapy that records how it was called, so nothing outside tmp_path is touched.
"""

import os
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "dev", "hooks", "pre-push")


def git(*args, cwd, check=True, env=None):
    return subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args],
        cwd=cwd, check=check, capture_output=True, text=True, env=env,
    )


def without_mayapy_on_path():
    """The environment with every folder holding a mayapy taken off PATH."""
    folders = os.environ["PATH"].split(os.pathsep)
    kept = [f for f in folders if not shutil.which("mayapy", path=f)]
    return dict(os.environ, PATH=os.pathsep.join(kept))


def fake_mayapy(tmp_path, exit_code):
    """A stand-in for mayapy that writes its arguments to calls.txt, the GIT_DIR it
    sees to git_dir.txt, and exits with ``exit_code``."""
    path = tmp_path / "fake-mayapy"
    calls = (tmp_path / "calls.txt").as_posix()
    git_dir = (tmp_path / "git_dir.txt").as_posix()
    path.write_text(
        f'#!/bin/sh\necho "$@" >> "{calls}"\necho "${{GIT_DIR-unset}}" > "{git_dir}"\nexit {exit_code}\n',
        newline="\n",
    )
    return path


@pytest.fixture
def clone(tmp_path):
    origin = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    work = tmp_path / "work"
    git("clone", "-q", str(origin), str(work), cwd=tmp_path)
    git("checkout", "-q", "-b", "main", cwd=work)
    (work / "dev" / "hooks").mkdir(parents=True)
    shutil.copy(HOOK, work / "dev" / "hooks")
    (work / "marker.txt").write_text("one")
    git("add", ".", cwd=work)
    git("commit", "-q", "-m", "init", cwd=work)
    git("push", "-q", "origin", "main", cwd=work)  # before the hook is on
    git("config", "core.hooksPath", "dev/hooks", cwd=work)
    (work / "marker.txt").write_text("two")
    git("commit", "-q", "-am", "change", cwd=work)
    return work


def remote_heads(clone):
    return git("ls-remote", "--heads", "origin", cwd=clone).stdout


def calls(tmp_path):
    path = tmp_path / "calls.txt"
    return path.read_text().splitlines() if path.exists() else []


def test_a_push_to_main_is_refused(clone, tmp_path):
    git("config", "kaiju.mayapy", fake_mayapy(tmp_path, 0).as_posix(), cwd=clone)
    before = remote_heads(clone)

    result = git("push", "origin", "main", cwd=clone, check=False)

    assert result.returncode != 0
    assert "pull request" in result.stderr
    assert remote_heads(clone) == before
    assert calls(tmp_path) == []


def test_a_push_to_main_under_another_local_name_is_refused(clone, tmp_path):
    git("config", "kaiju.mayapy", fake_mayapy(tmp_path, 0).as_posix(), cwd=clone)

    result = git("push", "origin", "HEAD:main", cwd=clone, check=False)

    assert result.returncode != 0
    assert "pull request" in result.stderr


def test_a_branch_push_runs_the_suite_and_goes_through_when_it_passes(clone, tmp_path):
    git("config", "kaiju.mayapy", fake_mayapy(tmp_path, 0).as_posix(), cwd=clone)
    git("checkout", "-q", "-b", "feature/x", cwd=clone)

    result = git("push", "origin", "feature/x", cwd=clone, check=False)

    assert result.returncode == 0, result.stderr
    assert "refs/heads/feature/x" in remote_heads(clone)
    assert calls(tmp_path) == ["-m pytest tests -q -p no:cacheprovider"]


def test_the_suite_runs_without_the_hooks_git_dir(clone, tmp_path):
    # Git sets GIT_DIR for hooks run in a linked worktree; tests that run git in
    # their own repos must not inherit it.
    git("config", "kaiju.mayapy", fake_mayapy(tmp_path, 0).as_posix(), cwd=clone)
    worktree = tmp_path / "wt-x"
    git("worktree", "add", "-q", "-b", "feature/x", str(worktree), cwd=clone)

    git("push", "origin", "feature/x", cwd=worktree)

    assert (tmp_path / "git_dir.txt").read_text().strip() == "unset"


def test_a_branch_push_is_refused_when_the_suite_fails(clone, tmp_path):
    git("config", "kaiju.mayapy", fake_mayapy(tmp_path, 1).as_posix(), cwd=clone)
    git("checkout", "-q", "-b", "feature/x", cwd=clone)

    result = git("push", "origin", "feature/x", cwd=clone, check=False)

    assert result.returncode != 0
    assert "tests failed" in result.stderr
    assert "feature/x" not in remote_heads(clone)


def test_a_branch_push_is_refused_when_mayapy_is_not_set(clone):
    git("checkout", "-q", "-b", "feature/x", cwd=clone)

    result = git("push", "origin", "feature/x", cwd=clone, check=False, env=without_mayapy_on_path())

    assert result.returncode != 0
    assert "git config kaiju.mayapy" in result.stderr
    assert "feature/x" not in remote_heads(clone)
