# Kaiju Suite Development Guide

## Tool Structure
- Tools live in `scripts/kaiju_suite/tools/<tool_name>/`
- Each tool has `logic.py` (Maya logic, no Qt) and `widget.py` (UI)
- Entry point is defined in `__init__.py` with a `show()` function that imports the widget

## Development Workflow
1. Create new tool directory: `scripts/kaiju_suite/tools/<tool_name>/`
2. Implement Maya logic in `logic.py` using `@undoable` decorator from `core.undo`
3. Implement UI in `widget.py`, subclassing `ui.base_window.ToolWindow`
4. Define tool entry in `__init__.py` with `TOOL = {"name": "...", "category": "...", "launch": show}`
5. Click **Kaiju → Reload Kaiju Suite** to reload changes

## Testing
- Run tests with `mayapy -m pytest tests`
- Tools can be tested by running them in Maya (no external test framework needed)

## Key Files
- `scripts/kaiju_suite/tools/joint_tool/logic.py` - Contains `set_end_joints_to_zero()` functionality
- `scripts/kaiju_suite/tools/joint_tool/widget.py` - Contains UI for the Joint Tool