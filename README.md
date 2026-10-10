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
  rig/                   rig module algorithms (IK, ...); imports only core, no Qt
  ui/                    menu builder and ToolWindow base class
  registry.py            discovers tools
  tools/<tool>/          one folder per tool
icons/
tests/
install/
```
Imports only flow one way: `tools` → `ui` → `core`, and `tools` → `rig` → `core`. Tools never import each other.

## Adding a tool
1. Create `scripts/kaiju_suite/tools/<my_tool>/`.
2. Put the Maya logic in `logic.py`. Don't import Qt there; wrap edits with `@undoable` from `core.undo`.
3. Put the UI in `widget.py`, as a subclass of `ui.base_window.ToolWindow`.
4. In `__init__.py`, define a `show()` that imports the widget lazily, then a `TOOL` dict:
   ```python
   TOOL = {"name": "My Tool", "category": "Rigging", "launch": show}
   ```
5. Click **Kaiju → Reload Kaiju Suite**. The tool shows up under its category, or directly in the Kaiju menu if it has none (`category` is optional). Add `"menu": False` to keep a tool out of the menu, e.g. one that's only opened from another tool; `registry.find(name)` still finds it.

See `tools/renamer/` for a working example. Ideas for tools to build next are in [docs/tool-ideas.md](docs/tool-ideas.md).

Shared helpers live in `core/` so tools can use them without importing each other: `core.curves` (NURBS curve shapes as data, and rebuilt from it), `core.colors` (Maya's index colors), `core.matching` (vertex matching by closest point, UV or topology, used by the SkinCluster Tool and the Assembler's SkinCluster, DeltaMush and BlendShapes items), `core.nodes.unique_name`, `core.naming.opposite_name` (`L_arm` ↔ `R_arm`), `core.attributes` (custom attributes and channel lock/hide state, read as data and applied back; used by the Assembler's Attributes items), `core.checks` (scene checks for naming, unfrozen transforms, leftover history and unknown nodes, each returning problem messages; the Assembler's QC items run them), `core.keys` (animation and driven key curves read and written as data; used by the Assembler's Animation and Set Driven Keys items), `core.deformers` (a mesh's index in a deformer, the vertices it deforms and its weights) and `core.paths` (file paths stored relative to a build folder or `$ASSET`, see below).

## Adding an Assembler product
The Assembler lists, runs and creates "products": scripts, scenes, folders, joints, meshes, skinClusters, deltaMush, blendShapes, curves, materials, deformers (cluster, softMod, wire, lattice, nonLinear), wraps, pose correctives (poseInterpolators), poses, animation, set driven keys, constraints, connections (utility node networks), attributes, sets & display layers, control shapes, rig modules, QC checks and outputs (which save the built rig as a `.ma`, `.mb` or FBX file) today. Each one is a module in `tools/assembler/products/`.
1. Add `tools/assembler/products/<my_product>.py`. Don't import Qt there.
2. Subclass `Product` and set `name`, `extensions` and `order`. Set `runnable = True` and implement `run(path)` if it should take part in **Run All** (runnable items can also be disabled; override `can_disable` to change that). Set `menu_slot = (group, position)` to place its entry in the right-click **New** menu (dividers separate groups; leave it unset to go in a last group, or set `None` to leave it out).
3. Set `versioned = True` to give its files **Publish** and a **Versions** submenu on the right-click menu. Versions are copies kept in a hidden `.versions/<file name>/` folder next to the item (`v001.py`, `v002.py`, ...); they follow the item when it's renamed or moved, and are deleted with it. Publish saves the file as it is; override `publish(path)` to return an `Action` that does something else (scenes open a file browser and save the picked Maya file's path as a new version). Return messages from `publish_problems(path)` to stop Publish before it runs; they're shown to the user in a dialog (meshes report an empty selection). Return messages from `publish_warnings(path)` for things that look wrong but shouldn't block; the user is asked whether to publish anyway (materials report missing texture files).
4. Optionally override `open(path)` for double-click, or return a `Panel` (a checklist of `Toggle`s, each with a hover tooltip and an optional `edit` Action shown as a "?" button on its row, then info lines and `Action` buttons; set `run_buttons=True` to add Run and Show Log buttons at the bottom, as QC does) from `panel(path)` to open a window on double-click instead. Set `utility` to a tool's name (e.g. `"Mesh Tool"`) to open that tool on double-click; the panel then moves to a right-click **Info** entry. Each product except Script, Folder, Separator, Scene, Curves, Pose Correctives, Set Driven Keys, Connections, Sets & Layers, QC and Output has a utility tool, one folder per tool under `tools/` (e.g. `tools/mesh_tool/`), listed under **Kaiju ▸ Utilities** (except the Rig Module Editor, which is only opened from the Assembler). The Assembler opens it through `registry.find(name)`, so it never imports the tool. A tool that edits the item itself adds `"open": fn(path)` to its `TOOL` dict; double-click then calls that with the item's path instead of `launch()` (the Rig Module Editor does this). Override `type_name(path)` to show something other than `name` for an item in the Type column, publish messages and run logs (Rig Modules show their module). Return right-click `Action`s from `actions(path)`, and list `Creator`s for its entries in the **New** submenu.
5. End the module with `PRODUCT = MyProduct()`.

Builds run from the right-click menu: **Run** (the selected items) and **Run '<folder>'** (every enabled item in a folder, top to bottom; `logic.collect_steps` picks them, Qt-free).

Each run of a step is logged and saved in a hidden `.logs/<file name>.log` next to the item (right-click **Show Log** opens it). The log gets anything `run` returns as a message, Maya's output during the step (`cmds.warning`, MEL `print`, errors) and, on failure, the traceback. Call `runlog.info(message)` to log what the step did, and `runlog.warning(message)` for things it skipped: a step with warnings ends orange (Warning) instead of green, and the build goes on.

After **Run '<folder>'**, a Build Report window lists each step's status (OK / Warning / Error / Skipped), its time and a button to open its log. The report data is Qt-free in `tools/assembler/report.py`: pass a `report.Recorder(paths)` as `on_status` to `logic.run_steps`, then read `recorder.results` (or `report.summary(results)` for plain text); the window is `report_widget.py`.

Nothing else needs registering. See `products/scene.py` for a working example.

### Storing file paths (portable paths)
A product that points to a file outside itself should store the path with `core/paths.py`, so the build folder still works when it's moved or opened on another machine. `paths.to_portable(path, root)` gives the text to store: relative to `root` (forward slashes) when the file is under it, else `$ASSET/...` when it's under the folder in the `ASSET` environment variable (pass `variables=` for others), else absolute; text that already starts with a variable is kept. `paths.resolve(stored, root)` turns that text back into a path: it expands variables and `~`, and joins relative text to `root`; absolute text, including entries written before this, is used as it is. Scene does this with `root` set to its **build folder**, the folder holding the `.scene` file (`scene.build_root(path)`): `scene.stored(path)` is the saved text and `scene.target(path)` the file it resolves to. Build plans export the stored text. Output does the same with the file it saves to (`output.build_root(path)`, `output.target(path)`). Moving a Scene item into a different folder of the tree changes its build folder, so a relative path then points somewhere else: publish it again.

### Rig-data products (`DataProduct`)
Products that save rig data from the scene and apply it back (Joints, Mesh, Curves, SkinCluster, DeltaMush, BlendShapes, Deformers, Wrap, Pose Correctives, Material, Pose, Animation, Set Driven Keys, Constraints, Connections, Attributes, Sets & Layers, ControlShape) subclass `DataProduct` from `tools/assembler/data.py` instead of `Product`. Their files are JSON with a header, `{"kaiju": <kind>, "format": 1, "data": <payload>}`, which `data.read(path, kind)` checks and `data.write(path, kind, payload)` writes (deterministically, so publishing unchanged content adds no version).
1. Set `name`, `kind` (the header's `kaiju` value), `extension` (one, lower case, with the dot) and `order`.
2. Implement `gather(selection)`, which returns the payload from the selected nodes (long names) or raises; `apply(payload)`, which changes the scene and may return a message; `selection_problems()`, which returns messages when the selection can't be published; and `describe(payload)`, which returns the info lines for the double-click window. Optionally implement `nodes(payload)`, which returns the names of the nodes (or components, e.g. `body.f[0:9]`) the payload was gathered from, such that `gather` on them gives the same kind of payload again. It gives items a right-click **Update from Scene** entry (re-publish without selecting anything: "same meshes, new weights"); products that don't implement it don't get the entry. Every product in this repo implements it.
3. Everything else comes from the base class: **New ▸ <name>** creates an empty file, which a build skips; **Run** applies the file as one undo step; **Publish** gathers from the selection and saves the result as the next version via `versions.export_into(path, write_fn)` (Scene uses it too, to write the picked path); `publish_problems` returns `selection_problems()`, and `publish_warnings` returns `selection_warnings()` (none unless overridden). **Update from Scene** (`update_from_scene(path)`) finds the names from `nodes()` with `data.resolve_nodes`, stops with one message naming any that are missing or match several nodes (`update_problems(path)`), then runs `gather` on them and saves the result as the next version, whatever is selected. Empty items don't get the entry. A product that overrides `actions(path)` should add `super().actions(path)` to keep it.
4. **Versions ▸ Compare With** comes free too: it lists the item's other versions and shows what changed from the picked one to the current file (`versions.compare_panel`). By default `compare(old_payload, new_payload)` returns a structural summary of the two JSON payloads from `tools/assembler/compare.py`: added, removed and changed keys, records matched by `name` (or `mesh`, `node`), and lists of numbers summed up as how many values changed and the largest change. Override `compare` for a better summary when it's cheap, using the helpers there (`match`, `changes`, `finish`): SkinCluster and DeltaMush say on how many vertices the weights changed and by how much at most; Joints and Mesh name the joints and meshes added, removed and changed. It needs no scene, so test it with plain payloads. A product that isn't a `DataProduct` gets Compare With by overriding `compare_files(old_path, new_path)`.
5. In `apply`, skip what's missing and check the rest first, raising before changing anything. `data.skip_missing(names, "meshes")` returns the missing ones and logs one warning naming them (Pose, SkinCluster, DeltaMush, BlendShapes, Wrap, Pose Correctives, Connections and ControlShape do this; Animation and Set Driven Keys the same by hand); `data.require_nodes(names, "influences")` instead raises one error listing them, for products where a missing node must stop the run (Material). Create nodes with `data.create_node(type, name, parent)`, which picks a free name the way Maya does (`spine_jnt` becomes `spine_jnt1`) and returns a UUID; get the current path with `data.node_path(uuid)`.

See `products/joints.py` for a working example.

### Rig modules
A rig module is an algorithm that builds part of a rig (an IK chain, ...) from parameters. The algorithm lives in `scripts/kaiju_suite/rig/modules/`, separate from the Assembler; the Assembler's **Rig Module** items (`.rig`) hold only the parameters, as `{"kaiju": "rigModule", "format": 1, "data": {"module": "simple_ik", "params": {...}}}` (`rig/spec.py` reads and writes them). Their Type column shows the module's name (e.g. `Simple IK`). **New** lists one entry per module and writes its defaults; **Run** builds the module as one undo step; **Publish** saves the parameters as the next version; double-click opens the **Rig Module Editor** on the file, with a form built from the module's parameters.

To add a module:
1. Add `rig/modules/<my_module>.py`. Don't import Qt, `ui` or `tools` there.
2. Subclass `RigModule` from `rig/module.py`. Set `key` (saved in the files; never change it), `name` (shown in **New** and the editor) and `params`, a tuple of `Param(key, label, kind, default, ...)`. `kind` is `"string"`, `"node"` (a scene node's name; the editor has a pick-from-selection button), `"float"`, `"bool"`, `"choice"` (with `choices`) or `"color"` (a Maya index color, 0 to 31, as in Drawing Overrides; 0 keeps Maya's default; the editor shows a drop-down of swatches). Set `required=True` for text that can't be blank and `tooltip` for the editor.
3. Implement `check(params)`, which returns messages for what stops a build in the current scene (types and required values are already checked), and `create(params)`, which builds and returns what it made. `build(params)` runs the checks, raises listing every problem before changing anything, then calls `create` inside one undo chunk.
4. End the module with `MODULE = MyModule()`.

Nothing else needs registering. See `rig/modules/simple_ik.py` for a working example, and `rig/modules/root.py` for one that needs no joints. `rig/helpers.py` has the shared pieces: checking a module's name, a node, a parent or a joint chain (`name_problems`, `node_problems`, `parent_problems`, `chain_problems`), and building groups, control curves (`circle`, `diamond`, `box`), a pole vector's position (`pole_position`), their color (`set_color`) and keeping the selection (`kept_selection`). `rig/space_switch.py` holds space switching (the `space` enum, its weights, and `switch`, which changes space without moving the control), used by the Space Switch module.

## Headless Assembler build
Build an Assembler folder from `mayapy` with no UI, e.g. for batch rebuilds or automatic rig checks:
```
set PYTHONPATH=<kaiju_suite>/scripts
mayapy -m kaiju_suite.tools.assembler.headless <build_folder> [--new-scene] [--save out.ma]
```
It runs the folder's enabled items like **Run All** (stopping at the first failure, and saving each step's log next to it as usual), prints each step's status and messages, and exits 0 if no step failed, 1 if one did, and 2 if the folder doesn't exist. `--new-scene` starts from an empty scene; `--save` saves the scene (`.ma` or `.mb`) only if no step failed. From Python already inside Maya or `maya.standalone`, `kaiju_suite.tools.assembler.headless.build(folder, new_scene=True, save=None)` does the same and returns the result: `result.ok`, and `result.steps`, each with its `name`, `status` (`success`, `warning`, `error` or `not run`) and `messages` (`(level, text)` pairs).

## Tests
```
mayapy -m pip install --user pytest   # once
mayapy -m pytest tests
```
