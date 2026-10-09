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
  ui/                    menu builder and ToolWindow base class
  registry.py            discovers tools
  tools/<tool>/          one folder per tool
icons/
tests/
install/
```
Imports only flow one way: `tools` → `ui` → `core`. Tools never import each other.

## Adding a tool
1. Create `scripts/kaiju_suite/tools/<my_tool>/`.
2. Put the Maya logic in `logic.py`. Don't import Qt there; wrap edits with `@undoable` from `core.undo`.
3. Put the UI in `widget.py`, as a subclass of `ui.base_window.ToolWindow`.
4. In `__init__.py`, define a `show()` that imports the widget lazily, then a `TOOL` dict:
   ```python
   TOOL = {"name": "My Tool", "category": "Rigging", "launch": show}
   ```
5. Click **Kaiju → Reload Kaiju Suite**. The tool shows up under its category.

See `tools/renamer/` for a working example.

## Adding an Assembler product
The Assembler lists, runs and creates "products": scripts, scenes, folders, joints and meshes today. Each one is a module in `tools/assembler/products/`.
The Assembler lists, runs and creates "products": scripts, scenes, folders, joints and skinClusters today. Each one is a module in `tools/assembler/products/`.
The Assembler lists, runs and creates "products": scripts, scenes, folders, joints and deltaMush today. Each one is a module in `tools/assembler/products/`.
The Assembler lists, runs and creates "products": scripts, scenes, folders, joints and blendShapes today. Each one is a module in `tools/assembler/products/`.
The Assembler lists, runs and creates "products": scripts, scenes, folders, joints and materials today. Each one is a module in `tools/assembler/products/`.
The Assembler lists, runs and creates "products": scripts, scenes, folders, joints and poses today. Each one is a module in `tools/assembler/products/`.
The Assembler lists, runs and creates "products": scripts, scenes, folders, joints and animation today. Each one is a module in `tools/assembler/products/`.
1. Add `tools/assembler/products/<my_product>.py`. Don't import Qt there.
2. Subclass `Product` and set `name`, `extensions` and `order`. Set `runnable = True` and implement `run(path)` if it should take part in **Run All** (runnable items can also be disabled; override `can_disable` to change that).
3. Set `versioned = True` to give its files **Publish** and a **Versions** submenu on the right-click menu. Versions are copies kept in a hidden `.versions/<file name>/` folder next to the item (`v001.ma`, `v002.ma`, ...); they follow the item when it's renamed or moved, and are deleted with it. Publish saves the file as it is; override `publish(path)` to return an `Action` that does something else (scenes export the selection into a new version). Return messages from `publish_problems(path)` to stop Publish before it runs; they're shown to the user in a dialog (scenes report an empty selection). Return messages from `publish_warnings(path)` for things that look wrong but shouldn't block; the user is asked whether to publish anyway (materials report missing texture files).
4. Optionally override `open(path)` for double-click, or return a `Panel` (info lines plus `Action` buttons) from `panel(path)` to open a window on double-click instead. Return right-click `Action`s from `actions(path)`, and list `Creator`s for its entries in the **New** submenu.
5. End the module with `PRODUCT = MyProduct()`.

Nothing else needs registering. See `products/scene.py` for a working example.

### Rig-data products (`DataProduct`)
Products that save rig data from the scene and apply it back (Joints, Material, and later Mesh, SkinCluster, ...) subclass `DataProduct` from `tools/assembler/data.py` instead of `Product`. Their files are JSON with a header, `{"kaiju": <kind>, "format": 1, "data": <payload>}`, which `data.read(path, kind)` checks and `data.write(path, kind, payload)` writes (deterministically, so publishing unchanged content adds no version).
Products that save rig data from the scene and apply it back (Joints, Animation, and later Mesh, SkinCluster, ...) subclass `DataProduct` from `tools/assembler/data.py` instead of `Product`. Their files are JSON with a header, `{"kaiju": <kind>, "format": 1, "data": <payload>}`, which `data.read(path, kind)` checks and `data.write(path, kind, payload)` writes (deterministically, so publishing unchanged content adds no version).
1. Set `name`, `kind` (the header's `kaiju` value), `extension` (one, lower case, with the dot) and `order`.
2. Implement `gather(selection)`, which returns the payload from the selected nodes (long names) or raises; `apply(payload)`, which changes the scene and may return a message; `selection_problems()`, which returns messages when the selection can't be published; and `describe(payload)`, which returns the info lines for the double-click window.
3. Everything else comes from the base class: **New ▸ <name>** creates an empty file, which a build skips; **Run** applies the file as one undo step; **Publish** gathers from the selection and saves the result as the next version via `versions.export_into(path, write_fn)` (Scene uses it too); `publish_problems` returns `selection_problems()`, and `publish_warnings` returns `selection_warnings()` (none unless overridden).
4. In `apply`, check first and raise before changing anything: `data.require_nodes(names, "influences")` raises one error listing every missing node. Create nodes with `data.create_node(type, name, parent)`, which picks a free name the way Maya does (`spine_jnt` becomes `spine_jnt1`) and returns a UUID; get the current path with `data.node_path(uuid)`.

See `products/joints.py` for a working example.

## Tests
```
mayapy -m pip install --user pytest   # once
mayapy -m pytest tests
```
