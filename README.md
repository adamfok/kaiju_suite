# Kaiju Suite

A collection of Maya tools, shipped as one Maya module. Requires Maya 2025 or later.

## Install
Drag `install/drag_and_drop.py` into a Maya viewport. A **Kaiju** menu appears in the main menu bar, and the plug-in loads automatically from then on.

## Layout
```
kaiju_suite.mod          module definition
plug-ins/                thin plug-in: builds and removes the menu
scripts/kaiju_suite/
  core/                  shared internal API (no Qt, never imports tools)
  datatypes/             rig data saved to files and applied back (joints, mesh, pose, skin, ...); imports only core, no Qt
  ui/                    menu builder and ToolWindow base class
  registry.py            discovers tools
  tools/<tool>/          one folder per tool
icons/
tests/
install/
dev/                     developer scripts, not loaded by Maya
```
Imports only flow one way: `tools` → `ui` → `core` and `tools` → `datatypes` → `core`. Tools never import each other.

## Adding a tool
1. Create `scripts/kaiju_suite/tools/<my_tool>/`.
2. Put the Maya logic in `logic.py`. Don't import Qt there; wrap edits with `@undoable` from `core.undo`.
3. Put the UI in `widget.py`, as a subclass of `ui.base_window.ToolWindow`.
4. In `__init__.py`, define a `show()` that imports the widget lazily, then a `TOOL` dict:
   ```python
   TOOL = {"name": "My Tool", "category": "Utility Tools", "launch": show}
   ```
5. Click **Kaiju → Reload Kaiju Suite**. The tool shows up under its category, or directly in the Kaiju menu if it has none (`category` is optional). Add `"menu": False` to keep a tool out of the menu, e.g. one that's only opened from another tool; `registry.find(name)` still finds it. Add `"startup": fn` to run something once when the plug-in loads.

See `tools/outliner_tool/` for a working example. Ideas for tools to build next are in [docs/tool-ideas.md](docs/tool-ideas.md).

Shared helpers live in `core/` so tools can use them without importing each other: `core.curves` (NURBS curve shapes as data, and rebuilt from it), `core.matching` (vertex matching by closest point, UV or topology), `core.nodes.unique_name`, `core.naming.opposite_name` (`L_arm` ↔ `R_arm`), `core.checks` (scene checks for naming, unfrozen transforms, leftover history and unknown nodes, each returning problem messages; the same functions take a datatype's own checks, e.g. `datatypes.skin.CHECKS`), `core.keys` (animation and driven key curves read and written as data), `core.deformers` (a mesh's index in a deformer, the vertices it deforms and its weights) and `core.paths` (file paths stored relative to a folder or `$ASSET`: `paths.to_portable(path, root)` gives the text to store, `paths.resolve(stored, root)` turns it back into a path).

## Kaiju Builder
Kaiju's build tool (`tools/builder/`, **Kaiju ▸ Builder**): pick a folder and it shows its items as a tree, in the order you drag them into. Each folder keeps its order and disabled items in a hidden `.builder/order.json`. (Builder used to be called Kaiju Scripter: a folder's old `.scripter` folder is renamed to `.builder` when Builder first shows it, and `logic.migrate_settings` moves the old settings over.) The item kinds are in `items.py`:

- **Script** (`.py`): runs in `__main__` like the Script Editor, with `__file__` set. Double-click edits it in the Script Editor.
- **Folder**, **Separator** (`.sep`, a divider) and **Breakpoint** (`.brk`, pauses a run; right-click it ▸ **Continue** runs the rest, reading the files again).
- **Joints** (`.jnt`), **Skin** (`.skin`), **Mesh** (`.mesh`) and **DeltaMush** (`.dmsh`): data published from the selection through `datatypes/`, and rebuilt or applied back when run. **New** needs a valid selection and publishes v001 straight away; **Publish...** captures the selection again as the next version; for a kind whose datatype has `CHECKS` (Skin, Joints, Mesh and DeltaMush; a check with `publish=False` only runs in its tool) it runs them first (`items.publish_qc`) and, if any find problems, asks with a **Publish Anyway** dialog. Double-click a Skin, Joints, Mesh or DeltaMush item to select its objects and open the SkinCluster Tool, Joint Tool, Mesh Tool or DeltaMush Tool (`items.TOOLS` maps a kind to its tool; `items.open_in_tool`); right-click any of them ▸ **Info...**, to see what's in it.
- **NurbsCurve** (`.curve`): NURBS curves that aren't controls (Spline IK curves, wire curves...), through `datatypes/curves.py`, and rebuilt as new curves when run, as Joints are. Versioned, with QC before Publish; double-click selects its curves and opens the **Curve Tool** (`tools/curve_tool/`: a QC tab on the selected curves, and a Utilities tab, empty for now).
- **Pose** (`.pose`): the values of the selected nodes' keyable, unlocked attributes (`datatypes/pose.py`), published, versioned and checked before Publish like the items above, and set back with `setAttr` (no keys) when run. Double-click selects its nodes and opens the Pose Tool, whose QC tab runs `datatypes.pose.CHECKS`.
- **ControlShape** (`.ctrl`): the curve shapes of the selected controls, through `datatypes/controlshape.py`, swapped back in when run. Works like the Joints, Skin and Mesh items: versioned, its `CHECKS` run before Publish, and double-click selects its controls and opens the ControlShape Tool.
- **BlendShapes** (`.bshp`): a data item like those, through `datatypes/blendshape.py`. It saves every blendShape on the selected meshes, not pose readers or target drivers. Double-click selects its meshes and opens the BlendShape Tool; Publish runs its `CHECKS` (No blendShape, Above skin, Empty targets, Duplicate names) first.
- **ProximityWrap** (`.pwrap`): the proximityWraps on the selected meshes (classic wraps are left out), through `datatypes/proximity_wrap.py`; it works like the items above, with QC checks, and double-click opens the ProximityWrap Tool.
- **NurbsSurface** (`.surface`): NURBS surfaces (ribbons, sliding surfaces...) saved by `datatypes/nurbs_surface.py` and rebuilt as **new** surfaces when run, never editing existing ones: name, parent name, local transform and each surface shape's degree, form and knots in U and V, object-space CVs and display overrides (rational CV weights and trim curves aren't saved). A taken name gets the next free one; the parent is found by name, otherwise the world, and a parent name matching several nodes stops the run before anything is created. Publish runs its `CHECKS` (Duplicate name, Rational CVs, Trimmed, Construction history) first; double-click selects its surfaces and opens the **Surface Tool** (`tools/surface_tool/`, **Kaiju ▸ Utility Tools**), which has a QC tab and a Utilities tab (empty for now).
- **Loft** (`.loft`): lofted NURBS surfaces (a ribbon lofted between curves...) saved by `datatypes/loft.py` with their loft node's settings and input curves, in order and by name, and rebuilt with **live history** when run: the surface follows its curves. If the surface is already in the scene it keeps its node and connections (follicles, constraints, skin) and only its history is replaced; otherwise it's created under its saved parent. A loft whose curves are missing is skipped with a warning. Only lofts from NURBS curves (not isoparms) can be published. Versioned, with QC before Publish (Not a loft, Unsupported inputs, Duplicate names, Flipped curves); double-click selects its surfaces and opens the **Loft Tool** (`tools/loft_tool/`, **Kaiju ▸ Utility Tools**), which has a QC tab and a Utilities tab (empty for now). Run Loft items after the NurbsCurve items that create their curves.
- **Import File** (`.import`) and **Export File** (`.export`): hold one path, as `{"path": ...}`, relative to the item's folder when the file is inside it (`core/paths.py`). Import File imports any file Maya can import (`.ma`, `.mb`, `.fbx`, `.obj`, `.abc`...) into the root namespace; Export File exports the selection to `.ma`, `.mb`, `.fbx` or `.obj`, overwriting the file, and fails if nothing is selected. Double-click picks another file. Not versioned.
- **Selection** (`.sel`): a list of entries, as `{"entries": [{"type", "value"}...]}`: selected objects (`selected`, a list of shortest unique names or components), a name pattern (`pattern`, Maya `ls` wildcards, several separated by spaces, with an optional `node_type` from `items.NODE_TYPES`; `*` or none is any node, and Geo/Nurbs Curve/Nurbs Surface/Locator find transforms with that shape) or a selection set (`set`, nested sets expanded). Patterns and sets are looked up on every run; intermediate objects are left out. Running it replaces the selection with everything they find, in entry order without repeats, and fails naming any object, pattern or set it can't find. Double-click opens a non-modal editor for the entries with a preview. Not versioned.
- **Animation** (`.anim`): keys published from the selection through `datatypes/animation.py`, versioned and applied back when run, like Joints, Skin and Mesh. **Publish...** runs its `CHECKS` first (Not animated, Unsaved animation, Duplicate names); double-click selects its nodes and opens the Animation Tool.

**Run** (right-click) runs the selected items and folders in tree order as one undo step (Maya can't undo an Import File: it flushes the undo queue on import): a folder runs its enabled items, a selected item runs even if disabled, and the run stops at the first failure. Scripts and the Joints, Skin, Mesh and DeltaMush items are versioned: **Publish...** copies the item into `.builder/versions/<name>/v001...` with a description, and **Versions...** restores one (asking first if that loses unpublished edits); renaming, moving and deleting take the history along, and **Copy**/**Paste** copies it. The logic is in `logic.py` (`scan`, `create_item`, `create_data_item`, `create_file_item`, `place`, `paste`, `Runner`, ...), `items.py` (each kind and how it runs) and `versions.py` (`publish`, `restore`, `label`, ...).

## Adding a datatype
Rig data saved from the scene and applied back lives in `scripts/kaiju_suite/datatypes/`, one module per kind of data, so Builder's data items and the Utility Tools share one file format. Files are JSON with a header, `{"kaiju": <kind>, "format": 1, "data": <payload>}`, written deterministically so publishing unchanged content adds no version.

Add `datatypes/<kind>.py` with `KIND` (the header's `kaiju` value), `EXTENSION` (one, lower case, with the dot) and these functions: `gather(nodes)`, which returns the payload for the nodes (long names) or raises; `apply(payload, info=None)`, which changes the scene and returns a message, calling `info` with one line per item applied; `selection_problems(selection)`, which returns messages when the selection can't be gathered; `describe(payload)`, the info lines for the double-click window; `nodes(payload)`, the names of the nodes (or components, e.g. `body.f[0:9]`) the payload was gathered from, such that `gather` on them gives the same kind of payload again; and optionally `CHECKS`, QC checks (`core.checks.Check`, each `fn(nodes, **options)`) that the datatype's tool shows in its QC tab (`ui/qc_tab.py`; see the SkinCluster Tool) and Builder runs before publishing; `datatypes.run_qc(module, nodes)` runs them with the settings saved per user, shared by both. Don't import Qt, `ui` or any tool there; warn with `datatypes.warning` (`cmds.warning`). `datatypes.save(module, path, nodes)` and `datatypes.load(module, path)` write and apply a module's files; a tool's `logic.py` wraps them (with `@undoable` for load).

In `apply`, skip what's missing and check the rest first, raising before changing anything: `datatypes.skip_missing(names, "meshes")` returns the missing ones and warns once naming them, and `datatypes.require_nodes(names, "influences")` raises one error listing them. See `datatypes/skin.py` for a working example.

## Tests
```
mayapy -m pip install --user pytest   # once
mayapy -m pytest tests
```

## Checking the UI in a real Maya
`dev/maya_ui/maya_ui.py` starts a separate Maya 2026 with throwaway preferences, loads this checkout's module, and drives it through a localhost command port. It checks that the Kaiju menu lists every tool and that every tool window opens without errors, warnings or dialogs, and saves a screenshot of each. Extra scenario scripts can click buttons and check the scene (see `dev/maya_ui/example_scenario.py`):
```
mayapy dev/maya_ui/maya_ui.py check [scenario.py ...]
```
It exits 1 on any failure. Coding agents use it through the `maya-ui-check` skill (`.claude/skills/maya-ui-check/`). Docking and window layout after a restart still need checking by hand.

## Pushing
`main` only changes through pull requests. Turn on the pre-push hook once per clone; it refuses pushes to `main` and runs the tests before any other push:
```
git config core.hooksPath dev/hooks
git config kaiju.mayapy "D:/Program Files/Autodesk/Maya2026/bin/mayapy.exe"   # your mayapy; without it the hook uses mayapy on PATH
```

## Trying a branch in Maya
Point a Maya version's line in your `kaiju_suite.mod` (in `Documents\maya\modules`) at a `kaiju_suite-dev` folder next to the main checkout. Then link that folder to whichever worktree you want to try, with no copying:
```
.\dev\use-worktree.ps1                   # list the worktrees (* = linked now) and pick one by number
.\dev\use-worktree.ps1 feature/my-tool   # link the worktree that has that branch
.\dev\use-worktree.ps1 main              # link the main checkout again
.\dev\use-worktree.ps1 -Show             # say what's linked now
```
`kaiju_suite-dev` is a directory junction (no admin rights needed). If it's a plain folder, e.g. an old copy, it's renamed to `kaiju_suite-dev.old-<time>`, not deleted. Then click **Kaiju → Reload Kaiju Suite** or restart Maya. Switch away from a worktree before removing it, or the link breaks until you switch.
