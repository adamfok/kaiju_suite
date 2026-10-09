"""Run logs: what each build step did, its warnings and errors, saved per item."""

import os

import pytest
from maya import cmds

from kaiju_suite.tools.assembler import logic, runlog, versions
from kaiju_suite.tools.assembler.products import pose


def _script(folder, name, code):
    path = os.path.join(str(folder), name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    return path


def _statuses(paths):
    seen = []
    logic.run_steps(paths, on_status=lambda path, status: seen.append((os.path.basename(path), status)))
    return seen


# -- capture ----------------------------------------------------------------


def test_capture_records_warnings_and_info():
    with runlog.capture() as run:
        runlog.info("did a thing")
        runlog.warning("skipped a thing")
    assert run.entries == [(runlog.INFO, "did a thing"), (runlog.WARNING, "skipped a thing")]
    assert run.warnings == ["skipped a thing"]


def test_outside_capture_nothing_is_recorded():
    runlog.info("nobody listening")
    runlog.warning("nobody listening")
    with runlog.capture() as run:
        pass
    assert run.entries == []


def test_capture_records_maya_output_and_prints():
    with runlog.capture() as run:
        print("hello from python")
        cmds.warning("careful")
        from maya import mel

        mel.eval('print "hello from mel\\n"; warning "mel careful";')
    assert (runlog.INFO, "hello from python") in run.entries
    assert (runlog.WARNING, "careful") in run.entries
    assert (runlog.INFO, "hello from mel") in run.entries
    assert any(level == runlog.WARNING and "mel careful" in text for level, text in run.entries)


def test_warning_is_recorded_once():
    with runlog.capture() as run:
        runlog.warning("only once")
    assert run.entries == [(runlog.WARNING, "only once")]


# -- files --------------------------------------------------------------------


def test_save_and_read_round_trip(tmp_path):
    item = _script(tmp_path, "a.py", "")
    run = runlog.RunLog()
    run.info("line one")
    run.warning("two\nlines")
    run.error("boom")
    runlog.save(item, run, logic.ERROR, "Script")

    assert runlog.exists(item)
    assert runlog.log_path(item) == os.path.join(str(tmp_path), ".logs", "a.py.log")
    lines = runlog.read(item)
    body = [(level, text) for level, text in lines if level is not None]
    assert body == [
        (runlog.INFO, "INFO    line one"),
        (runlog.WARNING, "WARNING two"),
        (runlog.WARNING, "        lines"),
        (runlog.ERROR, "ERROR   boom"),
    ]
    header = [text for level, text in lines if level is None]
    assert "Script: a.py" in header
    assert "Status: error" in header


def test_no_log_until_run(tmp_path):
    item = _script(tmp_path, "a.py", "")
    assert not runlog.exists(item)
    assert runlog.read(item) == []


# -- builds -------------------------------------------------------------------


def test_run_saves_a_log_for_each_step(new_scene, tmp_path):
    a = _script(tmp_path, "a.py", "print('making a box')\nfrom maya import cmds\ncmds.polyCube(name='box')\n")
    b = _script(tmp_path, "b.py", "")
    assert _statuses([a, b]) == [
        ("a.py", logic.RUNNING),
        ("a.py", logic.SUCCESS),
        ("b.py", logic.RUNNING),
        ("b.py", logic.SUCCESS),
    ]
    text = "\n".join(line for _, line in runlog.read(a))
    assert "INFO    making a box" in text
    assert "Status: success" in text
    assert runlog.exists(b)


def test_a_warning_sets_warning_status_and_the_build_goes_on(new_scene, tmp_path):
    a = _script(tmp_path, "a.py", "from maya import cmds\ncmds.warning('looks odd')\n")
    b = _script(tmp_path, "b.py", "from maya import cmds\ncmds.polyCube(name='box')\n")
    assert _statuses([a, b]) == [
        ("a.py", logic.RUNNING),
        ("a.py", logic.WARNING),
        ("b.py", logic.RUNNING),
        ("b.py", logic.SUCCESS),
    ]
    assert cmds.objExists("box")
    lines = runlog.read(a)
    assert (runlog.WARNING, "WARNING looks odd") in lines
    assert (None, "Status: warning") in lines


def test_a_failure_logs_the_error_and_traceback(new_scene, tmp_path):
    a = _script(tmp_path, "a.py", "print('before')\nraise ValueError('bad rig')\n")
    seen = []
    with pytest.raises(logic.StepError):
        logic.run_steps([a], on_status=lambda path, status: seen.append(status))
    assert seen == [logic.RUNNING, logic.ERROR]
    lines = runlog.read(a)
    text = "\n".join(line for _, line in lines)
    assert "INFO    before" in text
    assert "ValueError: bad rig" in text
    assert "Traceback" in text
    assert (None, "Status: error") in lines
    assert any(level == runlog.ERROR for level, _ in lines)


def test_product_message_is_logged(new_scene, tmp_path):
    node = cmds.createNode("transform", name="ctrl")
    path = pose.PRODUCT.create(str(tmp_path), "rest")
    cmds.select(node)
    versions.publish_action(path).fn()
    logic.run_steps([path])
    text = "\n".join(line for _, line in runlog.read(path))
    assert "INFO    Set 10 attributes on 1 node" in text


def test_missing_node_in_pose_warns_and_build_goes_on(new_scene, tmp_path):
    ctrl = cmds.createNode("transform", name="ctrl")
    other = cmds.createNode("transform", name="other")
    path = pose.PRODUCT.create(str(tmp_path), "rest")
    cmds.select(ctrl, other)
    versions.publish_action(path).fn()
    cmds.delete(other)
    after = _script(tmp_path, "after.py", "")
    statuses = _statuses([path, after])
    assert statuses[1] == ("rest.pose", logic.WARNING)
    assert statuses[3] == ("after.py", logic.SUCCESS)
    assert (runlog.WARNING, "WARNING Skipped missing nodes: other") in runlog.read(path)


# -- the log follows its item -------------------------------------------------


def _logged_item(tmp_path, name="a.py"):
    item = _script(tmp_path, name, "")
    logic.run_steps([item])
    assert runlog.exists(item)
    return item


def test_rename_keeps_the_log(new_scene, tmp_path):
    item = _logged_item(tmp_path)
    new = logic.rename_path(item, "b")
    assert runlog.exists(new)
    assert not runlog.exists(item)


def test_move_keeps_the_log(new_scene, tmp_path):
    item = _logged_item(tmp_path)
    sub = tmp_path / "sub"
    sub.mkdir()
    new = logic.move_path(item, str(sub))
    assert runlog.exists(new)
    assert not runlog.exists(item)
    assert not os.path.exists(os.path.join(str(tmp_path), runlog.LOG_DIR))


def test_delete_removes_the_log(new_scene, tmp_path):
    item = _logged_item(tmp_path)
    logic.delete_path(item)
    assert not os.path.exists(runlog.log_path(item))
    assert not os.path.exists(os.path.join(str(tmp_path), runlog.LOG_DIR))


def test_logs_folder_is_hidden_from_the_tree(new_scene, tmp_path):
    _logged_item(tmp_path)
    assert [e.name for e in logic.scan(str(tmp_path))] == ["a.py"]
