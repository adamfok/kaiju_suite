"""dev/use-worktree.ps1: points <parent>/kaiju_suite-dev at a git worktree.

Each test builds a throwaway repo with a worktree and runs the real script
against it, so nothing outside tmp_path is touched.
"""

import os
import shutil
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "dev", "use-worktree.ps1")


def git(*args, cwd):
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args],
        cwd=cwd, check=True, capture_output=True,
    )


@pytest.fixture
def repo(tmp_path):
    main = tmp_path / "repo"
    main.mkdir()
    git("init", "-q", "-b", "main", cwd=main)
    (main / "dev").mkdir()
    shutil.copy(SCRIPT, main / "dev")
    (main / "marker.txt").write_text("main")
    git("add", ".", cwd=main)
    git("commit", "-q", "-m", "init", cwd=main)
    git("worktree", "add", "-q", "-b", "feature/x", str(tmp_path / "wt-x"), cwd=main)
    (tmp_path / "wt-x" / "marker.txt").write_text("feature")
    return tmp_path


def run(repo, *args, answer=""):
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(repo / "repo" / "dev" / "use-worktree.ps1"), *args],
        capture_output=True, text=True, input=answer + "\n",
    )


def target(link):
    return os.path.normcase(os.path.realpath(link))


def same(a, b):
    return target(a) == os.path.normcase(os.path.realpath(b))


def test_links_branch_worktree(repo):
    result = run(repo, "feature/x")
    assert result.returncode == 0, result.stderr
    link = repo / "kaiju_suite-dev"
    assert same(link, repo / "wt-x")
    assert (link / "marker.txt").read_text() == "feature"


def test_main_links_main_checkout(repo):
    result = run(repo, "main")
    assert result.returncode == 0, result.stderr
    assert same(repo / "kaiju_suite-dev", repo / "repo")


def test_no_branch_lists_worktrees_and_links_the_picked_one(repo):
    result = run(repo, answer="2")
    assert result.returncode == 0, result.stderr
    assert "1  main" in result.stdout
    assert "2  feature/x" in result.stdout
    assert same(repo / "kaiju_suite-dev", repo / "wt-x")


def test_list_marks_the_linked_worktree(repo):
    assert run(repo, "feature/x").returncode == 0
    result = run(repo)
    lines = result.stdout.splitlines()
    assert any("feature/x" in line and "*" in line for line in lines)
    assert not any("1  main" in line and "*" in line for line in lines)


def test_empty_answer_changes_nothing(repo):
    assert run(repo, "feature/x").returncode == 0
    result = run(repo, answer="")
    assert result.returncode == 0, result.stderr
    assert same(repo / "kaiju_suite-dev", repo / "wt-x")


def test_bad_number_fails_and_changes_nothing(repo):
    assert run(repo, "feature/x").returncode == 0
    result = run(repo, answer="9")
    assert result.returncode != 0
    assert same(repo / "kaiju_suite-dev", repo / "wt-x")


def test_switching_keeps_the_old_worktrees_files(repo):
    assert run(repo, "feature/x").returncode == 0
    result = run(repo, "main")
    assert result.returncode == 0, result.stderr
    assert same(repo / "kaiju_suite-dev", repo / "repo")
    assert (repo / "wt-x" / "marker.txt").read_text() == "feature"


def test_plain_folder_is_renamed_not_deleted(repo):
    old = repo / "kaiju_suite-dev"
    old.mkdir()
    (old / "copied.txt").write_text("old copy")
    result = run(repo, "feature/x")
    assert result.returncode == 0, result.stderr
    backups = [p for p in repo.iterdir() if p.name.startswith("kaiju_suite-dev.old-")]
    assert len(backups) == 1
    assert (backups[0] / "copied.txt").read_text() == "old copy"
    assert same(repo / "kaiju_suite-dev", repo / "wt-x")


def test_unknown_branch_fails_and_changes_nothing(repo):
    assert run(repo, "feature/x").returncode == 0
    result = run(repo, "feature/missing")
    assert result.returncode != 0
    assert "feature/missing" in result.stderr
    assert same(repo / "kaiju_suite-dev", repo / "wt-x")


def test_show_reports_the_linked_worktree(repo):
    assert run(repo, "feature/x").returncode == 0
    result = run(repo, "-Show")
    assert result.returncode == 0, result.stderr
    assert "wt-x" in result.stdout
