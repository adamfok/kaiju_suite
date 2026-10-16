"""Guide module files (kaiju_suite.rigging.guide_module.spec), without the
Assembler. The Assembler's Guide product (tests/test_assembler_guides.py)
goes through this module. One file holds one guide module's layout."""

import pytest
from maya import cmds

from kaiju_suite.core import datafile
from kaiju_suite.rigging.guide_module import planar_chain, spec

ONE_GUIDE = "Select guides of one guide module, not arm_guides_grp, leg_guides_grp."
ARM = {
    "name": "arm",
    "aim": "-x",
    "up": "z",
    "guides": [[0.0, 0.0, 0.0], [3.0, 1.0, 2.0], [6.0, 0.0, 0.0], [9.0, 0.0, 0.0]],
    "up_guide": [4.0, 5.0, 0.0],
}


def _pos(node):
    return [round(v, 5) for v in cmds.xform(node, query=True, worldSpace=True, translation=True)]


def _arm():
    group = planar_chain.build_guides("arm", 2, start=(0, 0, 0), end=(9, 0, 0), aim="-x", up="z")
    cmds.xform(planar_chain.guides(group)["chain"][1], worldSpace=True, translation=(3, 1, 2))
    cmds.xform(planar_chain.guides(group)["up"], worldSpace=True, translation=(4, 5, 0))
    return group


def _leg():
    return planar_chain.build_guides("leg", 0, start=(0, 0, 0), end=(0, -8, 0))


def test_kind_and_extension():
    assert spec.KIND == "guideModule"
    assert spec.EXTENSION == ".guide"


# -- files ----------------------------------------------------------------------


def test_write_then_read_and_load(tmp_path):
    path = str(tmp_path / "arm.guide")
    spec.write(path, "chain", ARM)
    assert datafile.read(path, spec.KIND) == {"guide_module": "chain", "layout": ARM}
    assert spec.read(path) == ("chain", ARM)
    guide_module, layout = spec.load(path)
    assert guide_module.key == "chain" and layout == ARM


@pytest.mark.parametrize("data", [[1], {"layout": {}}, {"guide_module": 3, "layout": {}}, {"guide_module": "chain", "layout": []}])
def test_read_rejects_a_file_that_isnt_a_guide_module(tmp_path, data):
    path = str(tmp_path / "odd.guide")
    datafile.write(path, spec.KIND, data)
    with pytest.raises(datafile.DataFormatError, match="odd.guide is not a guide module file"):
        spec.read(path)


def test_load_rejects_an_unknown_guide_module(tmp_path):
    path = str(tmp_path / "odd.guide")
    spec.write(path, "nope", {})
    with pytest.raises(LookupError, match="Unknown guide module 'nope'"):
        spec.load(path)


# -- the Assembler's datatype interface ---------------------------------------


def test_gather_saves_the_chain_from_any_of_its_nodes(new_scene):
    arm = _arm()
    picked = [planar_chain.joints(arm)[0], planar_chain.guides(arm)["up"], arm]
    assert spec.gather(cmds.ls(picked, long=True)) == {"guide_module": "chain", "layout": ARM}


def test_gather_refuses_two_guide_modules(new_scene):
    arm, leg = _arm(), _leg()
    with pytest.raises(ValueError, match="one guide module"):
        spec.gather([arm, leg])


def test_gather_then_apply_rebuilds_the_guides(new_scene):
    group = _arm()
    before = [_pos(g) for g in planar_chain.guides(group)["chain"]]
    payload = spec.gather([group])

    cmds.file(new=True, force=True)
    lines = []
    message = spec.apply(payload, info=lines.append)
    assert message == "Built Chain Guide arm: 4 guides, aim -x, up z"
    assert lines == []
    rebuilt = planar_chain.guides("arm_guides_grp")
    assert [_pos(g) for g in rebuilt["chain"]] == before
    assert _pos(rebuilt["up"]) == [4.0, 5.0, 0.0]
    # Run leaves the guides live: the joints still follow them.
    assert len(planar_chain.joints("arm_guides_grp")) == 4
    assert cmds.getAttr("arm_01_jnt.tx", lock=True)


def test_apply_tags_the_group_with_its_guide_module(new_scene):
    spec.apply({"guide_module": "chain", "layout": ARM})
    assert cmds.getAttr("arm_guides_grp.kaijuGuideModule") == "chain"


def test_apply_stops_before_changing_anything_if_the_guides_exist(new_scene):
    payload = spec.gather([_arm()])
    with pytest.raises(RuntimeError, match="Guides already in the scene: arm"):
        spec.apply(payload)
    assert cmds.ls("arm_guides_grp*") == ["arm_guides_grp"]


def test_apply_stops_if_other_nodes_use_its_names(new_scene):
    cmds.createNode("transform", name="arm_03_jnt")
    with pytest.raises(RuntimeError, match="arm_03_jnt"):
        spec.apply({"guide_module": "chain", "layout": ARM})
    assert not cmds.objExists("arm_guides_grp")


def test_apply_stops_on_guides_that_cant_be_built(new_scene):
    payload = spec.gather([_leg()])
    cmds.file(new=True, force=True)
    payload["layout"]["up_guide"] = [0, -20, 0]  # in line with the leg
    with pytest.raises(RuntimeError, match="leg: .*in line"):
        spec.apply(payload)
    assert cmds.ls(type="joint") == []


def test_apply_stops_on_an_unknown_guide_module(new_scene):
    with pytest.raises(RuntimeError, match="Unknown guide module 'nope'"):
        spec.apply({"guide_module": "nope", "layout": {}})


def test_apply_does_not_warn(new_scene, monkeypatch):
    warnings = []
    monkeypatch.setattr(cmds, "warning", warnings.append)
    spec.apply({"guide_module": "chain", "layout": ARM})
    assert warnings == []


def test_selection_problems(new_scene):
    assert spec.selection_problems([]) == ["Nothing selected. Select guides, a guide group or a joint they drive."]
    stray = cmds.createNode("transform", name="stray")
    arm, leg = _arm(), _leg()
    assert spec.selection_problems(cmds.ls([arm, stray], long=True)) == [
        "stray isn't a guide, a guide group or a joint built from guides."
    ]
    assert spec.selection_problems([arm, planar_chain.guides(leg)["up"]]) == [ONE_GUIDE]
    assert spec.selection_problems([arm, planar_chain.joints(arm)[1]]) == []


def test_gather_raises_on_a_node_that_isnt_a_guide(new_scene):
    with pytest.raises(ValueError, match="isn't a guide"):
        spec.gather(cmds.ls(cmds.createNode("transform", name="stray"), long=True))


def test_describe_and_nodes(new_scene):
    payload = spec.gather([_arm()])
    assert spec.describe(payload) == ["Chain Guide", "arm: 4 guides, aim -x, up z"]
    assert spec.nodes(payload) == ["arm_guides_grp"]
    assert spec.gather(cmds.ls(spec.nodes(payload), long=True)) == payload


def test_mirrored_hands_the_layout_to_its_guide_module():
    payload = {"guide_module": "chain", "layout": dict(ARM, name="L_arm")}
    mirrored = spec.mirrored(payload)
    assert mirrored["guide_module"] == "chain"
    assert mirrored["layout"]["name"] == "R_arm"
    assert spec.mirrored(mirrored) == payload
