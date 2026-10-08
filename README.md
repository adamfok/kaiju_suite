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
The Assembler lists, runs and creates "products": scripts, scenes and folders today. Each one is a module in `tools/assembler/products/`.
1. Add `tools/assembler/products/<my_product>.py`. Don't import Qt there.
2. Subclass `Product` and set `name`, `extensions` and `order`. Set `runnable = True` and implement `run(path)` if it should take part in **Run All** (runnable items can also be disabled; override `can_disable` to change that).
3. Optionally override `open(path)` for double-click, or return a `Panel` (info lines plus `Action` buttons) from `panel(path)` to open a window on double-click instead. Return right-click `Action`s from `actions(path)`, and list `Creator`s for its entries in the **New** submenu.
4. End the module with `PRODUCT = MyProduct()`.

Nothing else needs registering. See `products/scene.py` for a working example.

## Tests
```
mayapy -m pip install --user pytest   # once
mayapy -m pytest tests
```
