# Kaiju Suite — tool ideas

A working list of tools to add beyond the Assembler. Pick one, write a detailed plan for it, then build it.
Status is as of 2026-10-09 (after PR #25, the utility tools).

## Context
Kaiju Suite is a rigging-focused Maya module. It has the **Assembler** (a build pipeline of versioned items:
scripts, scenes, joints, meshes, skin, deltaMush, blendShapes, materials, poses, animation, control shapes,
rig modules), the **Renamer**, the Rig Module Editor, and seven rig modules (Root, Single FK, FK Chain,
Simple IK, Stretchy IK, IK/FK, Spline IK).

The Utilities tools that work: Mesh, SkinCluster, DeltaMush, Pose and ControlShape Tool.
Still empty windows: **Joint, BlendShape, Material and Animation Tool**. They already have a menu entry
and an Assembler double-click entry point, so they're the cheapest place to add value.

The ideas below are what riggers reach for daily in comparable toolkits (mGear, AdvancedSkeleton,
ngSkinTools, Red9, comet scripts).

Reusable pieces in the repo: `rig/helpers.py` (`circle`, `box`, `diamond`, `set_color`, `chain`,
`pole_position`, `kept_selection`), `core/naming.py` (`expand_pattern`, `opposite_name`),
`core/nodes.py` (`unique_name`), `core/curves.py`, `core/colors.py`, `core/selection.py`,
`core/settings.py`, `core/datafile.py`, `core/undo.py` (`@undoable`).

## The ten ideas (ranked by value ÷ effort)

1. **Control Shape Library** — **Done** in the ControlShape Tool (PR #25): presets, save your own,
   create/replace, edit shapes, mirror to opposite, color and line width.

2. **Joint Tool** (fills the empty Joint Tool) — orient a chain (aim/up axis, world up), zero joint
   orient on end joints, mirror joints with name replace (`L_`→`R_`, via `opposite_name`), insert/split N
   joints between two, toggle local-axis display, set radius. Core of every rig session.

3. **Rig Validator / Scene Cleanup** — a checklist that scans the scene and reports, with one-click Fix
   where safe: controls with non-zero transforms, duplicate short names, unknown/unused nodes, stray
   namespaces, keys on rig controls, joints with rotations instead of orient, un-normalized skin weights.
   Could later become an Assembler "Validate" item that turns a build yellow. *Partly covered:* the Mesh
   Tool already checks meshes (history, unfrozen transforms, duplicate names, ...); this one is about the rig.

4. **Skin Weights Tool** — **Mostly done** in the SkinCluster Tool (PR #25): copy skin (closest point,
   UV, topology), mirror, prune, remove unused influences. *Still open:* limit max influences, normalize,
   weight hammer on selected vertices, copy/paste a vertex's weights, add/remove influences.

5. **Mirror Tool** — **Mostly done**: the Pose Tool mirrors and flips poses, the ControlShape Tool mirrors
   shapes, and `core/naming.opposite_name` finds opposites. *Still open:* mirroring animation (keys) across
   sides, which could go in the empty Animation Tool.

6. **Offset & Snap Tool** — add zero/offset groups above selected nodes (naming via `expand_pattern`),
   match position/rotation/pivot of one node to another, place a locator or joint at the centroid of
   selected components, and freeze-safe "zero out" for controls.

7. **Attribute Manager** — add, rename, reorder, lock/hide and delete custom attributes on many nodes at
   once; add divider ("separator") attributes; one-click "lock and hide scale/visibility" presets for
   controls. Keeps the channel box clean for animators.

8. **Space Switch Builder** — on a control, add a `space` enum (world, root, chest, head...) driven by a
   parent constraint on an offset group, plus a "switch without pop" button that keeps the control in
   place when changing space. Fits naturally as a new rig module later.

9. **Corrective Shape Tool** (fills the empty BlendShape Tool) — sculpt a corrective in a posed,
   skinned mesh, invert it back to bind space, add it as a target, and drive it from a pose reader
   (angle/cone reader on a joint) via set driven keys. Higher effort, high value for creature work.

10. **Selection Sets & Quick Picker** — save, recall and mirror sets of controls (e.g. "all left arm FK"),
    select all controls under a rig, key/reset-to-bind-pose the selection. Small effort, used constantly
    by animators testing the rig.

## How any one of these gets built (same pattern for each)
- New worktree from latest `main` (per CLAUDE.md), feature branch `feature/<tool>`.
- `tools/<tool>/logic.py`: all Maya logic, no Qt, scene edits wrapped with `@undoable`, track multi-node
  renames/reparents by UUID. `widget.py`: `ToolWindow` subclass. `__init__.py`: lazy `show()` + `TOOL` dict.
  For ideas that fill an existing empty tool (2, 9, and the open parts of 5) the folder and menu entry
  already exist.
- Anything reusable across tools goes in `core/` or `rig/`, never imported tool→tool.
- TDD: write `tests/test_<tool>.py` first (logic + undo), watch it fail, implement, then run the mayapy
  suite (see CLAUDE.md).
- CHANGELOG entry under Unreleased.
- The UI can't be checked headless: list manual steps for checking the window in Maya.

## Next step
Pick which idea to build next. Recommendation: **#2 Joint Tool**. It fills an empty window, reuses
`opposite_name` and the chain helpers, and is needed in every rig. Then write a detailed implementation
plan for that one tool before any code.
