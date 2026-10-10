"""Build report: each step's status, time taken and log, after a run."""

import os

import pytest

from kaiju_suite.tools.assembler import logic, report, runlog


def _script(folder, name, code):
    path = os.path.join(str(folder), name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    return path


def _run(paths):
    recorder = report.Recorder(paths)
    try:
        logic.run_steps(paths, on_status=recorder)
    except logic.StepError:
        pass
    return recorder.results


def test_statuses_times_and_logs(tmp_path, new_scene):
    ok = _script(tmp_path, "a_ok.py", "import time\ntime.sleep(0.05)\n")
    warned = _script(tmp_path, "b_warn.py", "from maya import cmds\ncmds.warning('careful')\n")
    failed = _script(tmp_path, "c_fail.py", "raise RuntimeError('boom')\n")
    after = _script(tmp_path, "d_after.py", "x = 1\n")

    results = _run([ok, warned, failed, after])

    assert [r.name for r in results] == ["a_ok.py", "b_warn.py", "c_fail.py", "d_after.py"]
    assert [r.status for r in results] == [report.OK, report.WARNING, report.ERROR, report.SKIPPED]
    assert results[0].seconds >= 0.05
    assert all(r.seconds is not None and r.seconds >= 0 for r in results[:3])
    assert results[3].seconds is None
    for r in results[:3]:
        assert r.log_path == runlog.log_path(r.path)
        assert r.has_log
    assert not results[3].has_log


def test_all_ok(tmp_path, new_scene):
    paths = [_script(tmp_path, f"s{i}.py", "x = 1\n") for i in range(3)]
    results = _run(paths)
    assert [r.status for r in results] == [report.OK] * 3
    assert report.total_seconds(results) == pytest.approx(sum(r.seconds for r in results))


def test_recorder_forwards_statuses(tmp_path, new_scene):
    path = _script(tmp_path, "s.py", "x = 1\n")
    seen = []
    recorder = report.Recorder([path], forward=lambda p, s: seen.append(s))
    logic.run_steps([path], on_status=recorder)
    assert seen == [logic.RUNNING, logic.SUCCESS]


def test_not_finished_step_is_error():
    """A step that started but never reported back (an unexpected crash) is an error."""
    recorder = report.Recorder(["/x/a.py", "/x/b.py"])
    recorder("/x/a.py", logic.RUNNING)
    results = recorder.results
    assert [r.status for r in results] == [report.ERROR, report.SKIPPED]


def test_counts_and_summary(tmp_path, new_scene):
    ok = _script(tmp_path, "a_ok.py", "x = 1\n")
    failed = _script(tmp_path, "b_fail.py", "raise RuntimeError('boom')\n")
    after = _script(tmp_path, "c_after.py", "x = 1\n")
    results = _run([ok, failed, after])

    assert report.counts(results) == {report.OK: 1, report.WARNING: 0, report.ERROR: 1, report.SKIPPED: 1}
    text = report.summary(results)
    lines = text.splitlines()
    assert any("a_ok.py" in line and "OK" in line and "s" in line for line in lines)
    assert any("b_fail.py" in line and "Error" in line for line in lines)
    assert any("c_after.py" in line and "Skipped" in line and "-" in line for line in lines)
    assert "1 OK, 0 Warning, 1 Error, 1 Skipped" in text
    assert "Total:" in text


def test_summary_of_nothing():
    assert "No steps" in report.summary([])


def test_format_seconds():
    assert report.format_seconds(None) == "-"
    assert report.format_seconds(0.123) == "0.12s"
    assert report.format_seconds(75.5) == "1m 15.5s"
