# Kaiju Suite

Maya tools shipped as one Maya module. Targets Maya 2025+ (Python 3.11, PySide6). See README.md for layout and the "adding a tool" steps.

## Running tests
Tests need `mayapy` (they start `maya.standalone`), not system Python. The interpreter path for this machine is in CLAUDE.local.md.

```
"<mayapy>" -m pytest tests -q -p no:cacheprovider
```

Run the suite after every change. It takes about 5s.

## Architecture rules (keep these)
- Imports only go one way: `tools` → `ui` → `core`. `core` never imports `ui` or `tools`. Tools never import each other.
- No Qt in `core/` or in any tool's `logic.py`. Qt goes only in `ui/` and `tools/<tool>/widget.py`.
- A tool's `__init__.py` must not import Qt or its widget at module level. `show()` imports the widget lazily, because the registry imports every tool package when it builds the menu.
- Wrap scene-changing logic functions with `@undoable` from `core.undo`, so one user action is one undo step.
- When renaming or reparenting several nodes, track them by UUID, not by long path: paths go stale once a parent changes (see `renamer/logic.py`).
- Store per-user settings with `core.settings` (optionVars), keyed by the tool name.
- Log through `core.log.get_logger(__name__)`. In UI code, show user-facing problems with `cmds.warning`.
- Adding a tool means adding a folder under `tools/`. Never hard-code tools in the menu or registry.

## Testing conventions
- Test `logic.py` and `core` headless under mayapy. Widgets can't be tested in standalone, so keep logic out of widgets.
- Use the `new_scene` fixture for any test that creates nodes.
- Each new tool gets a `tests/test_<tool>.py` that covers its logic, including the undo behavior.

## Housekeeping
- The version lives in `scripts/kaiju_suite/__init__.py` (`__version__`). The installer reads it from there; `kaiju_suite.mod` has its own copy, so keep both in sync when bumping.
- Add user-visible changes to CHANGELOG.md.
- You can't check the real Maya UI from here (menus, docking, widgets). If a change needs that, say so; don't claim it works.

## Worktrees

When starting any new feature or fix, begin by creating a separate git worktree from the base
branch and do all work inside it, so parallel agents never overwrite each other's changes.
After the work is merged, clean up by removing the worktree. For the next task, create a fresh
worktree from the latest base branch — don't reuse old trees.

## TDD is mandatory

Every change follows **failing test first → implement → verify**:
1. Write the test(s) that capture the desired behavior and watch them **fail** (red).
2. Implement the minimum to make them pass.
3. Run the mayapy test suite (see "Running tests") and confirm green.

Don't write implementation before a failing test exists. When fixing a bug, reproduce it with a
failing test first.

## Verify before claiming "done"

Never report something as working without running it. "Done" means the mayapy test suite is
green. The Maya UI (menus, docking, widgets, dialogs) can't be exercised from here, so for any
change that touches it, list the exact steps I need to check by hand in Maya instead of claiming
it works. If tests fail or a step was skipped, say so plainly with the output.
