# Changelog

## Unreleased

### New
- **Guide Tool** (Kaiju ▸ Guide Tool) is back as its own tool: place a joint chain with move-only guides (start, middles, end and an up guide like a pole vector). The joints follow the guides live and always stay planar. **Build Guides** builds them, also from an existing chain; **Delete Guides** leaves clean joints. A **Preset** dropdown (root, spine, neck, head, l_shoulder, l_arm, l_hand, l_finger, l_leg, l_foot, l_quad_leg, tail) fills Name, # Mid, Aim, Up, End and Mirror, and Build places that chain on a ~180 cm body, each chain's end on the next one's start; Custom works as before. The joint on the end guide is named `<name>_<N>_jnt_end`; uncheck **End** (beside # Mid, on by default) to build no joint there; the end guide still aims the last joint, and building guides on those joints after Delete Guides puts the end guide back where it was. With **Mirror** checked, Build also makes a joint chain mirrored across X with behavior that follows the guided joints live, with no guides of its own; its names swap the side (l/r, L/R, left/right, Left/Right) or get `_mirrored`. Delete Guides cuts it loose too, building guides on those joints again picks it back up, and building again with Mirror off removes it. While guides drive them the joints draw as reference, so clicks pick the guides; Delete Guides makes them normal again. The preview plane, the disc around each joint's aim axis and a cylinder along its rotate axis (the axis it bends around) are solid light blue; select them to scale them (they can't be moved or rotated; the plane scales from the first joint), and building again keeps their scale. Each button is one undo step, and Delete Guides no longer prints a "zero-length output vector" error.
- **Outliner Tool**: **Unparent** sets selected nodes to world parent and remembers their previous parent. **Reparent** restores selected nodes back to where they were before. The two buttons sit to the left of Lock and Unlock. Each is one undo step.
- **Outliner Tool**: **Lock** locks and hides every channel box attribute of the selected nodes. **Unlock** unlocks them and makes Translate, Rotate, Scale, Visibility and the nodes' own number attributes keyable again (a joint's Radius comes back shown, not keyable). Each is one undo step.

### Fixes
- After **Reload Kaiju Suite**, Builder no longer fails to open, or errors on every click, with "Internal C++ object (PySide6.QtWidgets.QProxyStyle) already deleted". Its Browse and Refresh buttons now use Kaiju's own icons, and the Version column draws its own dropdown arrow.
- **Utility Tools**: the QC tab's hint and the **Run Checks** tooltip now name what each tool checks (joints, curves, controls, surfaces...) instead of saying "meshes" in every tool.

## 1.0.0
First release. Requires Maya 2025 or later.

### Builder (Kaiju ▸ Builder)
Builds a rig from a folder: pick a folder and Builder shows its items as a tree, in the order you drag them into, and **Run** runs them top to bottom as one undo step.
- **Scripts** (`.py`) run like the Script Editor; double-click edits one in the Script Editor
- **Folders**, **Separators** and **Breakpoints** (a breakpoint pauses a run; right-click ▸ **Continue** runs the rest)
- **Data items** save part of the scene to a file and put it back when run: Joints (`.jnt`), Skin (`.skin`), Mesh (`.mesh`), NurbsCurve (`.curve`), NurbsSurface (`.surface`), Loft (`.loft`), ControlShape (`.ctrl`), BlendShapes (`.bshp`), DeltaMush (`.dmsh`), ProximityWrap (`.pwrap`), Pose (`.pose`) and Animation (`.anim`). **New** saves the selection; **Publish...** runs the QC checks for that kind first and saves the selection again as the next version
- **Import File** and **Export File** items, and **Selection** items (selected objects, name patterns or selection sets)
- Every script and data item keeps a version history next to it: **Publish...** adds a version with a description, and the Version column's dropdown restores one
- Disable items to skip them; Copy, Paste, rename, move and delete keep their history

### Utility Tools (Kaiju ▸ Utility Tools)
One tool per kind of data item, each with a **QC** tab that checks the selection and changes nothing. Click a problem to select what it points at. Builder runs the same checks, with the same settings, before it publishes. Each tool also has a **Utilities** tab, empty for now. Double-clicking a data item in Builder selects its objects and opens its tool.
- **Animation Tool**: Not animated, Unsaved animation, Duplicate names
- **BlendShape Tool**: No blendShape, Above skin, Empty targets, Duplicate names
- **ControlShape Tool**: No curve shapes, Shape name mismatch, No color, Duplicate names, Rational curves
- **Curve Tool**: Duplicate names, Rational curves, Construction history, Degenerate curves
- **DeltaMush Tool**: No deltaMush, Below skin, Disabled, Empty weights, Duplicate names
- **Joint Tool**: Rotate not zero, Scale not one, End joint orient, Overlapping joints, Duplicate names, Unmatched mirror
- **Loft Tool**: Not a loft, Unsupported inputs, Duplicate names, Flipped curves
- **Mesh Tool**: N-gons, Non-manifold, Lamina faces, Zero-area faces, Zero-length edges, Missing UVs, Locked normals, Not symmetric, Unfrozen transform, Construction history, Duplicate name, Shape name; some problems have a **Fix** button
- **Pose Tool**: Driven attributes, Nothing to save, Duplicate names
- **ProximityWrap Tool**: No proximityWrap, Missing driver, Below skin, Disabled, Duplicate names
- **SkinCluster Tool**: Not skinned, Weights not normalized, Too many influences, Tiny weights, Unused influences
- **Surface Tool**: Duplicate name, Rational CVs, Trimmed, Construction history

### Outliner Tool (Kaiju ▸ Outliner Tool)
- Rename the selected nodes from one field: `##` numbers them, `*` adds a prefix or suffix, `>` searches and replaces
- Group, Chain and Offset the selected nodes

### Removed since 0.2.0
- The Assembler, the Asset Library and their editors. Builder replaces the Assembler
- Kaiju Scripter is now Builder. Folders and settings from Scripter move over by themselves the first time Builder opens them

## 0.2.0
- Assembler tool (ported from afk_tools Snippets Tool): browse a folder of `.py`/`.mel`/`.ma`/`.mb` snippets; open scripts in a Script Editor tab, run them as one undo step, import scenes, export the selection to a new scene, and add, move (drag and drop), or remove files and folders
- Changes from the original: Export Selected picks `.mb` or `.ma`; Overwrite Scene removed; name dialogs stay open on errors; hidden folders and `__pycache__` are not listed; delete confirmation names the item type
- Fix: tool windows failed to open after **Reload Kaiju Suite** ("workspace control name is not unique")

## 0.1.0
- Module skeleton, plug-in, and auto-generated Kaiju menu
- Core API: undo chunks, logging, settings, selection, naming
- Renamer tool
- Drag-and-drop installer
