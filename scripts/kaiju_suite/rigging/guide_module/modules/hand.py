"""Hand guide module: a wrist with one finger chain per finger.

The wrist is a planar chain (:mod:`..planar_chain`) from the wrist guide
to the palm guide, with no joint on the palm guide: it only aims the wrist
joint, and the hand's up guide turns it. Each finger is a planar chain of
its own, knuckle to tip, on the plane of its own up guide, with all its
joints parented under the wrist joint. With a thumb, the first finger is
the thumb, one middle joint shorter than the others. One aim and one up
axis turn every joint of the hand.

The hand is separate from the arm: an arm is a Chain Guide plus a Hand
Guide, joined at the wrist by name.

Its layout is the hand's name, its axes, whether the first finger is a
thumb, and world positions; each finger keeps its own guides, so fingers
can have different numbers of joints::

    {"name": "L_hand", "aim": "x", "up": "y",
     "wrist": [x, y, z], "palm": [x, y, z], "hand_up": [x, y, z],
     "thumb": True,
     "fingers": [{"guides": [knuckle, middles..., tip], "up_guide": [x, y, z]}, ...]}

Its top group is the wrist chain's guide group, ``<name>_guides_grp``;
the fingers' (``<name>_thumb_guides_grp``, ``<name>_index_guides_grp``...)
are under it.
"""

from maya import cmds
from maya.api import OpenMaya as om

from kaiju_suite.core.naming import mirrored_name
from kaiju_suite.rigging.guide_module import planar_chain
from kaiju_suite.rigging.guide_module.guide_module import GuideModule, flip_x, flipped_axis, is_point, tag

_KEYS = ("name", "aim", "up", "wrist", "palm", "hand_up", "thumb", "fingers")
_POINTS = ("wrist", "palm", "hand_up")
_NAMED = ("index", "middle", "ring", "pinky")
# On the hand's top group: message links to the finger chains' groups, in
# order, and whether the first is a thumb.
_FINGERS = "handFingers"
_THUMB = "handThumb"
# The default hand: a left hand at the end of a default Chain Guide (X 10),
# pointing +X with the palm down and the thumb forward (+Z).
_WRIST, _PALM, _HAND_UP = [10.0, 0.0, 0.0], [11.5, 0.0, 0.0], [10.75, 1.5, 0.0]
_DEFAULT_THUMB = ([10.6, -0.2, 0.7], [11.8, -0.6, 1.3], [11.2, 0.6, 1.3])  # knuckle, tip, up guide
_SPREAD = 0.6  # the outer fingers' knuckles are this far either side of the middle


def finger_names(count, thumb):
    """The names of ``count`` fingers, the first a thumb if ``thumb``:
    thumb, index, middle, ring, pinky, then finger_05, finger_06..."""
    named = [_NAMED[i] if i < len(_NAMED) else f"finger_{i + 1:02d}" for i in range(count - bool(thumb))]
    return (["thumb"] if thumb else []) + named


def _rounded(point):
    # + 0.0 turns -0.0 into 0.0.
    return [round(c, 6) + 0.0 for c in point]


def _line(start, end, middles):
    """``start``, ``middles`` points evenly between, and ``end``."""
    start, end = om.MVector(start), om.MVector(end)
    return [_rounded(start + (end - start) * (i / (middles + 1))) for i in range(middles + 2)]


def _non_thumb(layout):
    return layout["fingers"][1:] if layout["thumb"] else layout["fingers"]


def _middles(finger):
    return len(finger["guides"]) - 2


def _default_fingers(count, middles, thumb):
    fingers = []
    if thumb:
        knuckle, tip, up = _DEFAULT_THUMB
        fingers.append({"guides": _line(knuckle, tip, middles - 1), "up_guide": list(up)})
    others = count - bool(thumb)
    for i in range(others):
        z = _SPREAD - 2 * _SPREAD * i / (others - 1) if others > 1 else 0.0
        fingers.append({"guides": _line([11.5, 0.0, z], [13.1, 0.0, z], middles), "up_guide": _rounded([12.3, 1.0, z])})
    return fingers


def _finger_groups(group):
    """The finger chains' guide groups under the hand's top ``group``, in order."""
    found = []
    for index in cmds.getAttr(f"{group}.{_FINGERS}", multiIndices=True) or []:
        source = cmds.listConnections(f"{group}.{_FINGERS}[{index}]", source=True, destination=False)
        if source:
            found.append(cmds.ls(source[0], long=True)[0])
    return found


class HandGuideModule(GuideModule):
    key = "hand"
    name = "Hand Guide"

    def default_layout(self, name):
        """A left hand at X 10 (the end of a default Chain Guide), pointing
        +X with the palm down: a thumb forward and angled down, and four
        fingers side by side, each with 2 middle joints (the thumb 1).
        ``name`` if it can name nodes, else ``hand``."""
        return {
            "name": name if planar_chain.NAME.match(name or "") else self.key,
            "aim": "x",
            "up": "y",
            "wrist": list(_WRIST),
            "palm": list(_PALM),
            "hand_up": list(_HAND_UP),
            "thumb": True,
            "fingers": _default_fingers(5, 2, True),
        }

    # -- checking -------------------------------------------------------------

    def _shape_problems(self, layout):
        """Problems with the keys and positions of ``layout``, as messages."""
        missing = [k for k in _KEYS if k not in layout]
        if missing:
            return [f"The {self.name} layout is missing {', '.join(missing)}."]
        name, fingers = layout["name"], layout["fingers"]
        if not isinstance(layout["thumb"], bool):
            return [f"{name}: thumb must be true or false."]
        if not isinstance(fingers, list) or not fingers:
            return [f"{name}: a hand needs 1 finger or more."]
        if not all(isinstance(f, dict) and "guides" in f and "up_guide" in f for f in fingers):
            return [f"{name}: every finger needs guides and an up_guide."]
        points = [layout[k] for k in _POINTS] + [f["up_guide"] for f in fingers]
        if not all(isinstance(f["guides"], list) and all(is_point(p) for p in f["guides"]) for f in fingers) or not all(
            is_point(p) for p in points
        ):
            return [f"{name}: every guide must be an [x, y, z] position."]
        for finger_name, finger in zip(finger_names(len(fingers), layout["thumb"]), fingers):
            if len(finger["guides"]) < 2:
                return [f"{name} {finger_name}: a finger needs 2 guides or more."]
        return []

    def _chain_problems(self, layout, owned=()):
        """Why the wrist and finger chains of ``layout`` (its shape checked)
        can't be built in the current scene, the names ``owned`` nodes use
        counting as free."""
        name, aim, up = layout["name"], layout["aim"], layout["up"]
        try:
            planar_chain.check_build(
                name, [layout["wrist"], layout["palm"]], layout["hand_up"], aim, up, end_joint=False, owned=owned
            )
        except ValueError as e:
            return [f"{name}: {e}"]
        for finger_name, finger in zip(finger_names(len(layout["fingers"]), layout["thumb"]), layout["fingers"]):
            try:
                planar_chain.check_build(
                    f"{name}_{finger_name}", finger["guides"], finger["up_guide"], aim, up, owned=owned
                )
            except ValueError as e:
                return [f"{name} {finger_name}: {e}"]
        return []

    def check(self, layout):
        problems = self._shape_problems(layout)
        if problems:
            return problems
        name = layout["name"]
        if isinstance(name, str) and cmds.objExists(f"{name}_guides_grp"):
            return [f"Guides already in the scene: {name}. Delete them first."]
        return self._chain_problems(layout)

    # -- building and reading back ----------------------------------------------

    def create(self, layout):
        name, aim, up = layout["name"], layout["aim"], layout["up"]
        group = planar_chain.build_at(
            name, [layout["wrist"], layout["palm"]], layout["hand_up"], aim, up, end_joint=False
        )
        cmds.addAttr(group, longName=_THUMB, attributeType="bool")
        cmds.setAttr(f"{group}.{_THUMB}", layout["thumb"])
        cmds.addAttr(group, longName=_FINGERS, attributeType="message", multi=True)
        wrist = planar_chain.joints(group)[0]
        for i, (finger_name, finger) in enumerate(zip(finger_names(len(layout["fingers"]), layout["thumb"]), layout["fingers"])):
            finger_group = planar_chain.build_at(
                f"{name}_{finger_name}", finger["guides"], finger["up_guide"], aim, up, parent=wrist, share_start=False
            )
            cmds.connectAttr(f"{finger_group}.message", f"{group}.{_FINGERS}[{i}]")
        cmds.select(clear=True)
        return group

    def layout(self, group):
        group = planar_chain.guide_group(group)
        chain = planar_chain.layout(group)
        fingers = [planar_chain.layout(g) for g in _finger_groups(group)]
        return {
            "name": chain["name"],
            "aim": chain["aim"],
            "up": chain["up"],
            "wrist": chain["guides"][0],
            "palm": chain["guides"][-1],
            "hand_up": chain["up_guide"],
            "thumb": bool(cmds.getAttr(f"{group}.{_THUMB}")),
            "fingers": [{"guides": f["guides"], "up_guide": f["up_guide"]} for f in fingers],
        }

    def reset(self, group, layout):
        """Put the guides back as ``layout`` has them. With the same fingers
        and joint counts the guides just move and the joints stay; otherwise
        the hand is built again, with new joints."""
        problems = self._shape_problems(layout)
        if problems:
            raise ValueError(problems[0])
        group = planar_chain.guide_group(group)
        current = self.layout(group)
        same = current["thumb"] == layout["thumb"] and [len(f["guides"]) for f in current["fingers"]] == [
            len(f["guides"]) for f in layout["fingers"]
        ]
        if not same:
            problems = self._chain_problems(layout, owned=planar_chain.owned_nodes(group))
            if problems:
                raise ValueError(problems[0])
            planar_chain.remove(group)
            group = self.create(layout)
            tag(group, self.key)
            return group
        # Check every chain first: moving some, then failing on one, would change something.
        aim, up = layout["aim"], layout["up"]
        planar_chain.check_axes(aim, up)
        planar_chain.planar_positions([layout["wrist"], layout["palm"]], layout["hand_up"])
        for finger in layout["fingers"]:
            planar_chain.planar_positions(finger["guides"], finger["up_guide"])
        group = planar_chain.set_layout(group, [layout["wrist"], layout["palm"]], layout["hand_up"], aim, up)
        for finger_group, finger in zip(_finger_groups(group), layout["fingers"]):
            planar_chain.set_layout(finger_group, finger["guides"], finger["up_guide"], aim, up)
        return group

    # -- the number of fingers and middle joints ----------------------------------

    def reshaped(self, layout, fingers=None, count=None, thumb=None):
        """``layout`` with ``fingers`` fingers, ``count`` middle joints per
        finger (the thumb one fewer) and the first finger a ``thumb`` or not;
        what isn't given stays. Extra fingers go from the end; new ones copy
        the last finger, as far past it as it is past the one before (away
        from the thumb). A finger whose number of middle joints changes gets
        its middle guides again, evenly between its knuckle and its tip.
        Raises ``ValueError`` for a shape it can't make."""
        shown = self.fields(layout)
        fingers = shown["fingers"] if fingers is None else fingers
        middles = shown["count"] if count is None else count
        has_thumb = layout["thumb"] if thumb is None else thumb
        if fingers < 1:
            raise ValueError("A hand needs 1 finger or more.")
        if middles < 0:
            raise ValueError("The number of middle joints must be 0 or more.")
        if has_thumb and middles < 1:
            raise ValueError("The thumb needs 1 middle joint fewer than the fingers: with a thumb, # Mid must be 1 or more.")

        kept = [dict(f) for f in layout["fingers"][:fingers]]
        retarget = set(range(len(kept))) if count is not None else set()
        if has_thumb != layout["thumb"]:
            retarget.add(0)
        while len(kept) < fingers:
            retarget.add(len(kept))
            kept.append(self._next_finger(layout, kept, has_thumb))
        for i in sorted(retarget):
            target = middles - 1 if has_thumb and i == 0 else middles
            if _middles(kept[i]) != target:
                kept[i] = dict(kept[i], guides=_line(kept[i]["guides"][0], kept[i]["guides"][-1], target))
        return dict(layout, thumb=has_thumb, fingers=kept)

    def _next_finger(self, layout, fingers, has_thumb):
        """A finger past the last of ``fingers``."""
        others = fingers[1:] if has_thumb else fingers
        last = fingers[-1]
        knuckle = om.MVector(last["guides"][0])
        if len(others) >= 2:
            step = knuckle - om.MVector(others[-2]["guides"][0])
        else:
            wrist = om.MVector(layout["wrist"])
            normal = (om.MVector(layout["palm"]) - wrist) ^ (om.MVector(layout["hand_up"]) - wrist)
            normal.normalize()
            side = -1.0  # a hand's fingers go away from its thumb
            if has_thumb and others:
                side = 1.0 if (knuckle - om.MVector(fingers[0]["guides"][0])) * normal > 0 else -1.0
            step = normal * side * ((om.MVector(layout["palm"]) - wrist).length() * 0.5)
        return {
            "guides": [_rounded(om.MVector(p) + step) for p in last["guides"]],
            "up_guide": _rounded(om.MVector(last["up_guide"]) + step),
        }

    def reshape(self, group, fingers=None, count=None, thumb=None):
        """Build the hand under ``group`` again with :meth:`reshaped`'s
        shape, its guides kept where they are now, as one undo step. Returns
        the new top group. Raises ``ValueError`` (changing nothing) for a
        shape it can't make."""
        layout = self.reshaped(self.layout(group), fingers=fingers, count=count, thumb=thumb)
        return self.restore(group, layout)

    # -- the editor, extracting, describing, mirroring -----------------------------

    def fields(self, layout):
        """What the Guide Module Editor shows for ``layout``: its name, # Fingers,
        # Mid (the last finger's middle joints; with only a thumb, one more
        than its own), Thumb, and one Aim and Up for the whole hand."""
        others = _non_thumb(layout)
        count = _middles(others[-1]) if others else _middles(layout["fingers"][0]) + 1
        return {
            "name": layout["name"],
            "fingers": len(layout["fingers"]),
            "count": count,
            "thumb": layout["thumb"],
            "axes": [{"part": "hand", "label": "", "aim": layout["aim"], "up": layout["up"]}],
        }

    def set_axes(self, group, part, aim, up):
        """Turn the wrist and every finger's joints."""
        if part != "hand":
            raise ValueError(f"A {self.name} has no {part!r} axes: use 'hand'.")
        planar_chain.check_axes(aim, up)
        group = planar_chain.guide_group(group)
        for chain in [group] + _finger_groups(group):
            planar_chain.set_axes(chain, aim, up)

    def check_extract(self, group):
        return planar_chain.extract_problems(group)

    def delete(self, group):
        """Extract the fingers' joints, then the wrist (see
        :func:`~..planar_chain.delete_guides`); the fingers stay under the wrist."""
        return planar_chain.delete_guides(group)

    def describe(self, layout):
        fingers = ", ".join(finger_names(len(layout["fingers"]), layout["thumb"]))
        return [f"{layout['name']}: wrist; {fingers}; aim {layout['aim']}, up {layout['up']}"]

    def mirrored(self, layout):
        """``layout`` for the other side: renamed with
        :func:`~kaiju_suite.core.naming.mirrored_name` (``L_hand`` -> ``R_hand``),
        every guide flipped across X and the axes reversed, so the joints
        come out as Maya's Behavior mirror makes them, as Chain Guide's do.
        Mirroring twice gives ``layout`` back."""
        return {
            **layout,
            "name": mirrored_name(layout["name"]),
            "aim": flipped_axis(layout["aim"]),
            "up": flipped_axis(layout["up"]),
            **{k: flip_x(layout[k]) for k in _POINTS},
            "fingers": [
                {"guides": [flip_x(p) for p in f["guides"]], "up_guide": flip_x(f["up_guide"])} for f in layout["fingers"]
            ],
        }


GUIDE_MODULE = HandGuideModule()
