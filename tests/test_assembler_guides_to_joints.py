import os

import pytest
from maya import cmds

from kaiju_suite.rigging.guide_module import all_guide_modules, get_guide_module, planar_chain
from kaiju_suite.tools.assembler import logic, products, runlog
from kaiju_suite.tools.assembler.products import guides_to_joints

POSITIONS = [[0, 0, 0], [3, 1, 0.5], [6, -1, 0], [10, 0, 0]]
UP = [5, 6, 0]


def _chain(name, positions=POSITIONS, up=UP):
    layout = {"name": name, "aim": "x", "up": "y", "guides": positions, "up_guide": up}
    return get_guide_module("chain").build(layout)


def _leg():
    return _chain("leg", [[0, 0, 0], [0, -4, 0], [0, -8, 0]], [0, -4, 5])


def _log(path):
    return "\n".join(line for _level, line in runlog.read(path))


def _item(tmp_path, name="Guides to Joints"):
    return guides_to_joints.create_guides_to_joints(str(tmp_path), name)


def test_new_item_is_an_empty_file(tmp_path):
    path = _item(tmp_path, "extract")
    assert path == str(tmp_path / f"extract{guides_to_joints.EXTENSION}")
    assert os.path.getsize(path) == 0
    assert products.product_for(path) is guides_to_joints.PRODUCT
    with pytest.raises(FileExistsError):
        _item(tmp_path, "extract")


def test_new_menu_entry_is_named_guides_to_joints():
    (creator,) = guides_to_joints.PRODUCT.creators
    assert creator.label == "Guides to Joints"
    assert creator.fixed_name is None


def test_is_run_but_not_versioned(tmp_path):
    product = guides_to_joints.PRODUCT
    assert product.name == "Guides to Joints"
    assert product.runnable
    assert product.can_disable
    assert not product.versioned
    _item(tmp_path)
    (entry,) = logic.scan(str(tmp_path))
    assert entry.version_label is None
    assert entry.type_label == "Guides to Joints"


def test_new_menu_puts_it_between_guides_and_joints():
    labels = [None if entry is None else entry[1].label for entry in products.new_menu()]
    at = labels.index("Guides to Joints")
    assert labels[at + 1] == "Joints"
    assert labels[at - 1] == all_guide_modules()[-1].name


def test_run_extracts_every_chains_joints(new_scene, tmp_path):
    _chain("arm")
    _leg()
    path = _item(tmp_path)

    logic.run_steps([path])

    assert not cmds.objExists("arm_guides_grp")
    assert not cmds.objExists("leg_guides_grp")
    assert cmds.objExists("arm_01_jnt") and cmds.objExists("leg_01_jnt")
    log = _log(path)
    assert "arm" in log and "leg" in log


def test_run_is_one_undo_step(new_scene, tmp_path):
    _chain("arm")
    path = _item(tmp_path)
    cmds.undoInfo(state=True)
    cmds.flushUndo()

    logic.run_steps([path])
    assert not cmds.objExists("arm_guides_grp")
    cmds.undo()

    assert cmds.objExists("arm_guides_grp")
    assert len(planar_chain.joints("arm_guides_grp")) == 4


def test_run_with_no_guides_warns(new_scene, tmp_path):
    path = _item(tmp_path)
    statuses = []

    logic.run_steps([path], on_status=lambda p, s: statuses.append(s))

    assert statuses[-1] == logic.WARNING
    assert "No guides" in _log(path)


def test_run_with_a_broken_chain_fails_and_changes_nothing(new_scene, tmp_path):
    arm = _chain("arm")
    _leg()
    cmds.delete(planar_chain.guides(arm)["up"])
    path = _item(tmp_path)

    with pytest.raises(logic.StepError):
        logic.run_steps([path])

    assert cmds.objExists("leg_guides_grp")


def test_run_succeeds_without_warnings(new_scene, tmp_path):
    _chain("arm")
    _leg()
    path = _item(tmp_path)
    statuses = []

    logic.run_steps([path], on_status=lambda p, s: statuses.append(s))

    assert statuses[-1] == logic.SUCCESS, _log(path)
