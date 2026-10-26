# Kaiju Suite — Assembler ideas

A working list of new Assembler item types ("products") and improvements to the Assembler itself. Pick one,
write a detailed plan for it, then build it. Status is as of 2026-10-09 (after PR #26). For tools outside
the Assembler, see [tool-ideas.md](tool-ideas.md).

## Context
The Assembler builds a rig from an ordered tree of versioned items. It has 14 item types today: Script,
Scene, Folder, Separator, Mesh, Joints, ControlShape, SkinCluster, DeltaMush, BlendShapes, Material (not in
the New menu), Pose, Animation and Rig Module (7 modules: Root, Single FK, FK Chain, Simple IK, Stretchy IK,
IK/FK, Spline IK).

Compared with mGear's loop (build guide → build rig → save skin, blendshapes, control shapes → delete →
tweak → rebuild) and other JSON-based rig builders (Rigamajig2, maya-pulse), a rig built with today's
items still needs hand-written Scripts for constraints, driven keys, custom attributes, non-skin deformers
and the final save. The ideas below close that gap.

Reusable pieces: `tools/assembler/data.py` (`DataProduct`: `gather` / `apply` / `selection_problems` /
`describe`, `skip_missing`), `tools/assembler/runlog.py` (`info`, `warning`), `products/deltamush.py`
(`_geometry_index`, sparse per-vertex weights), `products/animation.py` (key and tangent read/write),
`products/material.py` (a node network saved as mayaAscii text), `core/selection.short_name`.

## The ten products (ranked by value ÷ effort)
Every one except Output is a `DataProduct`: Publish saves from the selection, Run applies it back by
node name.

1. **Set Driven Keys** (`.sdk`) — saves driven key curves (`animCurveU*`): driver and driven attributes,
   keys, tangents, infinity. Run rebuilds them by node and attribute name. Animation leaves driven keys out
   on purpose; correctives, finger curls and foot rolls all need them. Reuses Animation's key code.
2. **Constraints** (`.cnst`) — parent, point, orient, scale, aim and pole vector constraints: targets,
   weights, offsets, aim/up vectors, interp type. Run recreates them by name, replacing a constraint of the
   same name. Every build needs a script for these today.
3. **Attributes** (`.attr`) — custom attributes (type, min/max, default, enum names, keyable/channel box)
   plus lock/hide state of standard channels. Run adds missing ones, updates existing ones and applies
   lock/hide. The final "lock and hide" pass of every rig. Shares logic with the Attribute Manager idea
   (tool-ideas #7); put that logic in `core/` so both can use it.
4. **Deformers** (`.dfm`) — cluster, softMod, wire, lattice/ffd and nonLinear (bend, twist, squash...):
   settings, members, painted weights. Run rebuilds them by name on meshes found by name. Covers what
   SkinCluster, DeltaMush and BlendShapes don't (mGear's "deformer weight map").
5. **Wrap** (`.wrap`) — wrap and proximityWrap: driver meshes and settings. Run rebinds the driven meshes.
   Clothes, eyebrows and props riding on the body.
6. **Connections** (`.conn`) — utility node networks (multiplyDivide, plusMinusAverage, condition,
   blendColors, remapValue, ...) and direct connections between the selected nodes. Run recreates the nodes
   and reconnects them. Custom links between rig parts without a Script. Can follow Material's approach.
7. **Curves** (`.crv`) — NURBS curves that aren't controls: degree, knots, CVs, parent, transform. Run
   creates new curves, as Mesh and Joints do. Spline IK takes a curve and wire deformers need one;
   ControlShape only replaces shapes on existing controls.
8. **Pose Correctives** (`.psd`) — poseInterpolator nodes: driver joint, poses, twist/swing settings, and
   which BlendShapes targets they drive. Run rebuilds and reconnects them. Completes the corrective
   workflow; pairs with the Corrective Shape Tool idea (tool-ideas #9).
9. **Sets & Layers** (`.sets`) — object sets (animator control sets, export sets) and display layers:
   members by name, display type, visibility. Run recreates them and adds members. Pairs with the
   Selection Sets idea (tool-ideas #10).
10. **Output** (`.out`) — a plain `Product`, runnable: where to save and in what format (.ma, .mb, FBX),
    plus optional cleanup (delete unused nodes, hide joints). Run saves or exports the built rig, usually as
    the last step, so Run All ends with a deliverable file.

### Runners-up
- **Check** (`.chk`) — a runnable step that changes nothing and only logs `runlog.warning`s (naming,
  unfrozen transforms, leftover history, unknown nodes), so the step turns yellow and the build goes on.
  This is the Assembler side of the Rig Validator idea (tool-ideas #3); share the checks via `core/`.
- **Space Switch** — better as a new Rig Module than a product (tool-ideas #8).

## Improvements to the Assembler itself (ranked)
1. **Rebuild** — new scene, then Run All; plus right-click "Run up to here" and "Run from here". Rigging
   is "change, rebuild, test" and none of these exist yet (`logic.run_steps` / `run_folder` only).
2. **Survive topology changes** — SkinCluster, DeltaMush and BlendShapes stop when a vertex count differs.
   Add a fallback that matches by closest point or UV, as mGear does (needs point positions saved at
   publish). The SkinCluster Tool's `copy_skin` (closest point / UV / topology) already does the matching;
   move that part into `core/` so the Assembler can use it (tools never import each other).
3. **Update from scene** — re-publish an item from the node names already in its file, without selecting
   anything. Most re-publishes are "same meshes, new weights".
4. **Portable paths** — Scene and Output store paths relative to the build folder (or a variable such as
   `$ASSET`), so a build folder works on another machine.
5. **Headless build** — build a folder from mayapy with no UI. The logic is already Qt-free, so this is
   cheap; it allows batch rebuilds and automatic rig checks.
6. **Build report** — after Run All, one window with each step's status and time and a link to its log
   (per-step logs already exist).
7. **Compare versions** — for data items, show what changed between two versions (nodes added/removed,
   which weights changed).
8. **Small fixes** — put Material back in the New menu; save normals and vertex colors in Mesh. (The empty
   Joint, BlendShape, Material and Animation Tool windows are covered in tool-ideas.md.)

## How any one of these gets built (same pattern for each)
- New worktree from latest `main` (per CLAUDE.md), branch `feature/<product>`.
- TDD: write `tests/test_assembler_<product>.py` first, in the style of `tests/test_assembler_deltamush.py`:
  publish → new scene → apply gives the same result; missing nodes are skipped with a warning; ambiguous
  names or changed vertex counts raise before changing anything; one undo reverts a Run. Watch it fail,
  implement, run the mayapy suite.
- `tools/assembler/products/<product>.py`, no Qt, ending with `PRODUCT = ...`; set `menu_slot` to sit with
  related items in the New menu.
- CHANGELOG entry under Unreleased; add the product to the README's product list.
- The New menu and Info window can't be checked headless: list manual steps for checking them in Maya.

## Sources
- [mGear: Skin and Weights](https://mgear4.readthedocs.io/en/stable/skinningUserDocumentation.html) —
  skin packs, position-based matching on topology change, deformer weight maps
- [mGear: rigging workflow](https://mgear4.readthedocs.io/en/latest/official-unofficial-workflow.html) —
  the build / save / delete / rebuild loop
- [maya-pulse: modules](https://maya-pulse.readthedocs.io/en/latest/core_modules/module.html) — a rig as an
  ordered list of build steps
- [Rigamajig2](https://www.therookies.co/entries/22667) — rig data saved as JSON and rebuilt by a builder

## Next step
Pick which idea to build next. Recommendation: **product #1, Set Driven Keys**. It's the biggest gap, every
rig uses driven keys, and it reuses most of `products/animation.py`. Then write a detailed implementation
plan for it before any code.
