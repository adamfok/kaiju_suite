"""Build plans: a whole Assembler tree as one JSON, exported and imported."""

import json
import os

import pytest

from kaiju_suite.core.datafile import DataFormatError
from kaiju_suite.rig import spec
from kaiju_suite.tools.assembler import logic, plan, versions
from kaiju_suite.tools.assembler.products import is_empty


def _write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return str(path)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


ARM_PARAMS = {"name": "L_arm", "start_joint": "L_shoulder_jnt", "end_joint": "L_wrist_jnt"}


@pytest.fixture
def build(tmp_path):
    """A build: a script, a scene, a disabled folder holding a rig module and a mesh, a separator."""
    root = tmp_path / "build"
    _write(root / "setup.py", "print('hi')\n")
    _write(root / "base.scene", json.dumps({"path": "D:/chars/hero.ma"}))
    os.makedirs(root / "arms")
    spec.write(str(root / "arms" / "L_arm.rig"), "simple_ik", ARM_PARAMS)
    _write(root / "arms" / "body.mesh", '{"kaiju": "mesh", "format": 1, "data": {"meshes": []}}')
    _write(root / "---.sep")
    logic.set_enabled(str(root / "arms"), False)
    # Custom order: the folder last.
    logic.place([str(root / "arms")], str(root), None)
    return str(root)


EXPECTED = {
    "items": [
        {"name": "---.sep"},
        {"name": "base.scene", "path": "D:/chars/hero.ma"},
        {"name": "setup.py", "content": "print('hi')\n"},
        {
            "name": "arms",
            "enabled": False,
            "items": [
                {"name": "body.mesh"},
                {"name": "L_arm.rig", "module": "simple_ik", "params": ARM_PARAMS},
            ],
        },
    ]
}


# -- export -------------------------------------------------------------------


def test_export_describes_the_whole_tree(build):
    assert plan.export_plan(build) == EXPECTED


def test_export_leaves_out_history_and_logs(build):
    versions.save_version(os.path.join(build, "setup.py"))
    assert plan.export_plan(build) == EXPECTED


def test_export_of_an_unreadable_rig_module_names_it(build):
    _write(os.path.join(build, "arms", "L_arm.rig"), "not json")
    with pytest.raises(ValueError, match="L_arm.rig"):
        plan.export_plan(build)


def test_export_can_include_the_folder_itself(build):
    arms = os.path.join(build, "arms")
    assert plan.export_plan(arms, include_folder=True) == {"items": [EXPECTED["items"][-1]]}


def test_a_folder_exported_with_itself_is_imported_as_that_folder(build, tmp_path):
    target = str(tmp_path / "target")
    os.makedirs(target)
    path = plan.save_plan(os.path.join(build, "arms"), str(tmp_path / "arms.json"), include_folder=True)
    created = plan.import_plan(plan.load_plan(path), target)
    assert created == [os.path.join(target, "arms")]
    assert [e.name for e in logic.scan(created[0])] == ["body.mesh", "L_arm.rig"]
    assert not logic.is_enabled(created[0])


# -- import -------------------------------------------------------------------


def test_import_recreates_the_tree(build, tmp_path):
    target = str(tmp_path / "copy")
    os.makedirs(target)
    created = plan.import_plan(EXPECTED, target)

    assert created == [os.path.join(target, i["name"]) for i in EXPECTED["items"]]
    assert plan.export_plan(target) == EXPECTED
    assert not logic.is_enabled(os.path.join(target, "arms"))
    assert spec.read(os.path.join(target, "arms", "L_arm.rig")) == ("simple_ik", ARM_PARAMS)
    assert _read(os.path.join(target, "setup.py")) == "print('hi')\n"
    assert is_empty(os.path.join(target, "arms", "body.mesh"))
    assert is_empty(os.path.join(target, "---.sep"))


def test_import_keeps_the_plans_order(tmp_path):
    items = [{"name": "b.py", "content": ""}, {"name": "a.py", "content": ""}]
    plan.import_plan({"items": items}, str(tmp_path))
    assert [e.name for e in logic.scan(str(tmp_path))] == ["b.py", "a.py"]


def test_import_adds_after_what_is_there(tmp_path):
    _write(tmp_path / "z.py")
    _write(tmp_path / "a.py")
    plan.import_plan({"items": [{"name": "new.py", "content": ""}]}, str(tmp_path))
    assert [e.name for e in logic.scan(str(tmp_path))] == ["a.py", "z.py", "new.py"]


def test_imported_items_have_no_versions(build, tmp_path):
    versions.save_version(os.path.join(build, "setup.py"))
    plan.import_plan(plan.export_plan(build), str(tmp_path))
    assert versions.list_versions(str(tmp_path / "setup.py")) == []


def test_rig_module_params_may_be_partial(tmp_path):
    item = {"name": "arm.rig", "module": "simple_ik", "params": {"name": "R_arm"}}
    plan.import_plan({"items": [item]}, str(tmp_path))
    assert spec.read(str(tmp_path / "arm.rig")) == ("simple_ik", {"name": "R_arm"})


def test_import_renames_items_whose_name_is_taken(tmp_path):
    _write(tmp_path / "setup.py", "old\n")
    _write(tmp_path / "setup_copy.py", "older\n")
    items = [{"name": "new.py", "content": ""}, {"name": "setup.py", "content": "new\n"}]
    created = plan.import_plan({"items": items}, str(tmp_path))
    assert created == [str(tmp_path / "new.py"), str(tmp_path / "setup_copy2.py")]
    assert _read(tmp_path / "setup.py") == "old\n"
    assert _read(tmp_path / "setup_copy2.py") == "new\n"
    assert [e.name for e in logic.scan(str(tmp_path))][-2:] == ["new.py", "setup_copy2.py"]


def test_import_renames_a_folder_whose_name_is_taken(build, tmp_path):
    target = str(tmp_path / "target")
    os.makedirs(os.path.join(target, "Arms"))
    exported = plan.export_plan(os.path.join(build, "arms"), include_folder=True)
    created = plan.import_plan(exported, target)
    assert created == [os.path.join(target, "arms_copy")]
    assert [e.name for e in logic.scan(created[0])] == ["body.mesh", "L_arm.rig"]
    assert not logic.is_enabled(created[0])


def test_import_needs_an_existing_folder(tmp_path):
    with pytest.raises(FileNotFoundError):
        plan.import_plan({"items": []}, str(tmp_path / "gone"))


# -- checking a plan ----------------------------------------------------------


def test_a_good_plan_has_no_problems():
    assert plan.plan_problems(EXPECTED) == []


@pytest.mark.parametrize(
    "item, expected",
    [
        ({"name": "notes.txt"}, "notes.txt: no item type uses .txt"),
        ({"name": "a/b.py", "content": ""}, "a/b.py: names can't contain"),
        ({"name": ".hidden.py", "content": ""}, ".hidden.py: names can't start with"),
        ({"name": "", "content": ""}, "every item needs a name"),
        ({"name": "x.py", "content": 3}, "x.py: content must be text"),
        ({"name": "x.scene", "path": 3}, "x.scene: path must be text"),
        ({"name": "x.rig", "module": "nope", "params": {}}, "x.rig: no rig module 'nope'"),
        ({"name": "x.rig", "module": "simple_ik", "params": []}, "x.rig: params must be"),
        ({"name": "x.rig", "module": "simple_ik", "params": {"color": "red"}}, "x.rig: Color must be"),
        ({"name": "x.rig", "module": "simple_ik", "params": {"startJoint": "a"}}, "x.rig: Simple IK has no parameter 'startJoint'"),
        ({"name": "grp", "items": "x"}, "grp: items must be a list"),
        ({"name": "x.py", "content": "", "enabled": "no"}, "x.py: enabled must be true or false"),
        ("x.py", "every item must be an object"),
    ],
)
def test_plan_problems_name_the_item(item, expected):
    problems = plan.plan_problems({"items": [item]})
    assert any(expected in p for p in problems), problems


def test_plan_problems_report_nested_paths_and_every_problem():
    bad = {
        "items": [
            {"name": "a.py", "content": ""},
            {"name": "A.py", "content": ""},
            {"name": "grp", "items": [{"name": "x.rig", "module": "nope", "params": {}}]},
        ]
    }
    problems = plan.plan_problems(bad)
    assert any("A.py: more than one item named" in p for p in problems)
    assert any("grp/x.rig: no rig module" in p for p in problems)


def test_plan_problems_need_an_items_list():
    assert plan.plan_problems({}) == ["The plan needs an items list."]
    assert plan.plan_problems([]) == ["The plan needs an items list."]


def test_import_of_a_bad_plan_lists_its_problems_and_writes_nothing(tmp_path):
    bad = {"items": [{"name": "ok.py", "content": ""}, {"name": "notes.txt"}]}
    with pytest.raises(ValueError, match="notes.txt"):
        plan.import_plan(bad, str(tmp_path))
    assert os.listdir(tmp_path) == []


# -- plan files ---------------------------------------------------------------


def test_save_and_load_a_plan_file(build, tmp_path):
    path = str(tmp_path / "biped.plan.json")
    plan.save_plan(build, path)
    with open(path, encoding="utf-8") as f:
        assert json.load(f)["kaiju"] == "buildPlan"
    assert plan.load_plan(path) == EXPECTED


def test_load_accepts_a_bare_plan(tmp_path):
    """What an AI pastes may lack the Kaiju header."""
    path = _write(tmp_path / "p.json", json.dumps(EXPECTED))
    assert plan.load_plan(path) == EXPECTED


def test_parse_plan_text(tmp_path):
    assert plan.parse_plan(json.dumps(EXPECTED)) == EXPECTED
    with pytest.raises(DataFormatError):
        plan.parse_plan("not json")
    with pytest.raises(DataFormatError):
        plan.parse_plan(json.dumps({"kaiju": "mesh", "format": 1, "data": {}}))
