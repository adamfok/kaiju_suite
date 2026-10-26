---
name: maya-ui-check
description: Check Kaiju Suite's UI in a real Maya 2026 - the Kaiju menu, every tool window opening cleanly, and button-driven scenarios - with screenshots. Use before saying "done" on any change that touches scripts/kaiju_suite/ui/ or a tool's widget.py or __init__.py, or when asked to check something in the Maya UI.
---

# Maya UI check

`dev/maya_ui/maya_ui.py` starts a **separate** Maya 2026 that loads the module from the worktree it sits in, with throwaway preferences and no autoloaded plug-ins, and drives it through a localhost command port. It never touches the user's own Maya, scenes or preferences, and only ever closes the Maya it started. Several runs can go at once.

## Run it

From the worktree root, with the mayapy path from `CLAUDE.local.md` (in the main checkout):

```
"<mayapy>" dev/maya_ui/maya_ui.py check [scenario.py ...]
```

This starts Maya (about 15s), runs the smoke check, runs each scenario, closes Maya, prints a PASS/FAIL report, and exits 1 on any failure. A whole run takes about 30s plus your scenarios. Run it in the foreground with a 10-minute Bash timeout.

The **smoke check** (`smoke.py`) checks the Kaiju menu lists every menu tool, then opens every tool's window and screenshots it. A step fails if it raises, if Maya prints a warning or error while it runs, or if a dialog pops up.

## Write a one-off scenario for the change

Put it in your scratchpad, not the repo. Copy `dev/maya_ui/example_scenario.py`. Scenarios run inside the test Maya with `cmds` and `ui` already defined:

- `with ui.step("what is being checked"):` – one PASS/FAIL line; put asserts inside.
- `ui.open_tool("Outliner Tool")` – launches it like the menu does, returns the window.
- `ui.click(window, "Reparent")` – clicks the visible button with that label. Icon-only buttons go by their tooltip up to the first colon. A wrong label fails and lists the labels there are.
- `ui.button(window, label)`, `ui.buttons(window)` – the Qt button(s), for anything else (e.g. `isEnabled()`).
- `ui.screenshot(widget, "name")`, `ui.screenshot_maya("name")` – saved PNGs, listed in the report.
- `ui.close_tool(window)`.
- For anything else, use Qt directly: `window.findChildren(QtWidgets.QLineEdit)` etc.

Start with `cmds.file(new=True, force=True)` and build the scene the scenario needs.

## Read and report the result

- Open the screenshots of the windows the change touched, and of any that failed, with Read, and look at them: layout, labels, nothing clipped or empty. Send those to the user with SendUserFile. Leave the rest in the session folder the report names.
- Give the user the PASS/FAIL list. Say plainly what failed, with the detail lines.
- `Dialog appeared` means a modal dialog popped up. It was screenshotted and closed, and counts as a failure.
- `ABORTED` means Maya hung (30s per scenario, 5 minutes per run) or crashed. That Maya was closed and the end of its log is printed.
- `Maya didn't start` after one automatic retry: report it with the log path, and don't claim the UI works.

## What it can't check

Docking a window by dragging, and windows coming back where they were after a Maya restart, still need the user's hand check. List those steps for them when a change touches docking or window state.

## Session commands (for poking around)

`start` prints a session folder and leaves Maya open; then use `run <session> <script>`, `smoke <session>`, and always `stop <session>` when done. `check --keep` leaves Maya open after the run (it is still closed on a hang).
