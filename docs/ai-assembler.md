# Kaiju Suite — AI chat for the Assembler

Research on whether an AI chat box ("rig this biped's arms and legs, IK/FK, left blue, right red") could
create an Assembler build, what it can and can't do, and what Kaiju needs first. Status is as of
2026-10-09 (after PR #27). Nothing here is built yet. For other ideas, see
[assembler-ideas.md](assembler-ideas.md) and [tool-ideas.md](tool-ideas.md).

## Summary
**Yes, and Kaiju is unusually well suited for it**, but only for the "wiring" half of a rig. An AI can
choose and fill in Rig Modules, order the build and write glue scripts. It can't reliably place joints,
paint weights or design control shapes; those stay with the rigger.

## 1. Why Kaiju already fits this well
- **A build is plain files.** Each Rig Module item is a small JSON file
  (`{"kaiju": "rigModule", "format": 1, "data": {"module": "simple_ik", "params": {...}}}`, read and
  written by `rig/spec.py`). The order and the disabled items are in `.assembler.json` per folder
  (`tools/assembler/logic.py`). An AI only has to write text files, not drive Maya.
- **Modules describe themselves.** Every module lists its parameters as `Param(key, label, kind, default,
  choices, required, tooltip)` (`rig/module.py`). That is almost a ready-made instruction sheet for an AI.
- **Errors are written for people.** `RigModule.problems(params)` returns plain messages ("The chain is
  straight, so the pole vector has no side to go on"). An AI can read those and fix its own mistakes.
- **No Qt in the logic.** `logic.run_steps`, `logic.run_folder` and `runlog` work headless, so an AI can
  build, read the step logs and retry.
- **Safety net exists.** Each step is one undo step, and items have versions, so an AI's edits can be
  rolled back.

## 2. What an AI can and can't do here

| Task | AI good at it? | Why |
|---|---|---|
| Pick modules for a request (arm → IK/FK, tail → Spline IK, fingers → FK Chain) | Yes | Pure reasoning over the module list |
| Fill parameters from the scene's joint names (`L_shoulder_jnt` → `L_wrist_jnt`) | Yes, if given the joint list | Name matching; needs a scene summary |
| Mirror left/right, apply naming and color conventions | Yes | Text patterns (`core.naming.opposite_name` exists) |
| Order the build, group into folders, set parents between modules | Mostly | Needs to know what nodes each module will create (see section 4, item 3) |
| Write Script items for constraints, attributes, driven keys | Partly | It can write the Python, but it's unreviewed code run in the scene |
| Place joints on a mesh from text | No | LLMs are poor at 3D placement; dedicated auto-riggers (RigNet, Uthana) use mesh-based models, and even those are humanoid-only |
| Skin weights, blendshapes, delta mush | No | These come from painting/sculpting; the AI can only add empty placeholders for the rigger to publish |
| Nice control shapes | Weak | It can pick circle / box / diamond, not shape them to the character |
| Use modules Kaiju doesn't have (spine, foot roll, hand, space switch) | No | It can only compose the 7 modules that exist, or fall back to writing scripts |

**Realistic first result:** the rigger builds or imports the skeleton and mesh, types a request, and gets
a ready-ordered build folder of Rig Module items (plus optional script items) to review, then
Run All.

## 3. Three ways to wire it up (cheapest first)

1. **Copy-paste (no API).** A menu item exports "what modules exist + the scene's joints" as text. The rigger
   pastes it into any chat (claude.ai), and pastes the AI's answer, a *build plan* JSON, back into an
   "Import build plan" action. Cheapest way to test whether the idea is useful.
2. **Claude Desktop / Claude Code talks to Maya (MCP).** A small MCP server exposes Kaiju actions
   (list modules, describe scene, write plan, validate, run) over Maya's `commandPort`. Several community
   "Maya MCP" servers already prove the commandPort route works, but none know about rigging or Kaiju.
   No chat UI to build, no API key inside Maya; the chat happens outside Maya.
3. **Chat panel inside Maya.** A new tool (`tools/rig_chat/`) with a PySide6 chat window calling the
   Claude API with *tool use*: the model calls the same actions as option 2, shows a preview of the
   files it will write, and the rigger clicks Apply. Best experience, most work.

Autodesk's own Maya AI Assistants (announced AU 2025) are general scene helpers; they don't know Kaiju's
Assembler, so they don't replace any of this.

**Recommendation:** build the shared foundation (section 4, items 1–4) first, since all three options
need it; try option 1 to see if the results are worth it; then go to option 3 (or 2 if chatting outside Maya is fine).

## 4. What needs to be built

### Structure changes (needed by every option)
1. **Module schema export.** `rig.describe_modules()` → JSON of every module's key, name, docstring
   summary and params (kind, default, choices, required, tooltip). Add two missing facts as data:
   minimum chain length (today hidden in `check()`, e.g. Simple IK needs 3 joints) and what node type a
   `"node"` param expects (joint vs any transform).
2. **Build plan format + import/export.** Today a build is spread over many files plus one
   `.assembler.json` per folder. Add one JSON that describes a whole tree (folders, items, order,
   enabled, module params), with `logic.export_plan(root)` and `logic.import_plan(plan, root)`. This is
   what the AI writes, and also gives shareable templates for free.
   **Done:** `tools/assembler/plan.py` (`export_plan`, `import_plan`, `plan_problems`, `parse_plan`);
   its docstring describes the format. Right-click ▸ Build Plan ▸ Export / Import in the Assembler.
3. **Modules declare what they create.** Module B's `parent` often has to be a node that module A
   builds later (e.g. the Root module's control). Today that is only known after `create()` runs.
   Add a static `outputs(params)` (names like `{name}_ik_ctrl`) so a plan can be validated before
   anything is built, and the AI can see which parents are valid.
4. **Scene summary.** A `core` function that returns the joint hierarchy (names, parents, world
   positions, side by name), mesh names and existing controls, compactly. The AI can't see Maya.
5. **Plan validation (dry run).** Run every item's `problems()` against the current scene plus the
   planned outputs from item 3, and return all messages in one list for the AI to fix.

### More building blocks (so the AI doesn't fall back to scripts)
6. **More rig modules.** For a usable biped: spine (ribbon or spline), neck/head, foot roll,
   hand/fingers, space switch. The AI can only compose what exists.
7. **The missing products** from `docs/assembler-ideas.md`: Constraints, Attributes, Set Driven Keys.
   Each one turns "AI writes risky Python" into "AI writes safe data".
8. **Rebuild / headless build** (assembler-ideas improvements #1 and #5): new scene → Run All → read the
   logs, so the AI can check its own work.

### Templates and examples
9. **Example builds as build plans:** biped, quadruped, prop with a hinge, tail/tentacle, simple face.
   They are shown to the AI as examples (big quality gain) and are starting templates for riggers.
10. **A short conventions file:** naming (`L_`/`R_`, `_jnt`, `_ctrl`), colors per side, folder layout.
    The AI follows written rules much better than guessed ones.

### For the in-Maya chat (option 3) only
11. **API access:** an Anthropic API key (from an environment variable, not an optionVar, because
    `core.settings` stores optionVars in plain-text Maya prefs), and either `pip install --user anthropic`
    into mayapy or plain `urllib` calls to avoid a dependency. A model such as `claude-sonnet-5-5` for
    chat; usage is billed per request.
12. **Threading:** API calls run off the main thread (so Maya doesn't freeze); every `maya.cmds` call
    goes back to the main thread (`maya.utils.executeInMainThreadWithResult`).
13. **Guard rails:** the AI writes only through `import_plan` into a new or chosen folder, shows a
    preview first, never runs Script items by itself, and every Apply is one undo step.

### Testing (per CLAUDE.md, TDD)
- Items 1–5, 8 and the tool-call handlers are plain logic: test headless under mayapy with a fake
  model client that replays recorded answers (no network in tests).
- The chat window can't be tested headless; it needs manual checks in Maya.

## 5. Limitations and risks to accept
- **Joint placement stays manual** (or a separate auto-rig/guide step). The AI works from names and
  positions already in the scene.
- **Badly named skeletons** (`joint1`, `joint2`, ...) give poor results; the AI relies on names.
- **Answers vary** between runs; the preview + validation step is what makes it safe.
- **Generated scripts** can do anything in the scene; keep them off by default or always reviewed.
- **Cost and network:** option 3 needs internet and a paid API key; option 1 doesn't.

## Next step
Start with the build plan format and its import/export (section 4, item 2): every way of wiring up the AI
needs it, and it's useful on its own for sharing build templates. Then try the copy-paste route to see
whether the results are worth an in-Maya chat window.

## Sources
- [Maya MCP server (Jeffreytsai1004)](https://github.com/Jeffreytsai1004/maya-mcp-server) and
  [Autodesk-Maya-MCP (AYDJI)](https://glama.ai/mcp/servers/@AYDJI/Autodesk-Maya-MCP/blob/3db6b8b98806568b33526d5855c0ccb25cd620d1/README.md)
  — Claude driving Maya through `commandPort`; no rigging tools
- [Autodesk adds AI Assistants to Maya](https://digitalproduction.com/2025/09/18/autodesk-adds-ai-assistants-to-maya-and-beyond/)
- [Uthana auto-rigging](https://uthana.com/product/auto-rigging) and
  [Meshy: auto rigging](https://www.meshy.ai/3d-glossary/auto-rigging) — mesh-based auto-riggers,
  humanoid-only, need a T/A pose
- RigNet (SIGGRAPH 2020) — neural skeleton prediction from a mesh, not from text
