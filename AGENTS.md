# Kaiju Suite: rules for coding agents

Read and follow `CLAUDE.md` before changing anything. It has the architecture rules, the test command and the conventions. `CLAUDE.local.md`, if present, has this machine's mayapy path. The rules below are the ones that matter most:

1. **Never commit or push to `main`.** Create a branch (in a new git worktree, see `CLAUDE.md`), commit there, and stop. Changes reach `main` only through a pull request that a person reviews. Pushes to `main` are refused anyway.
2. **Only touch the files the task names.** If the task is about one tool, don't change other tools, shared code or docs unless the task says so.
3. **Don't edit or delete existing tests to make them pass.** Add new tests for new behaviour, write them first and watch them fail.
4. **Run the full test suite with mayapy before saying you're done**, and report the real result: `"<mayapy>" -m pytest tests -q -p no:cacheprovider`. System Python has no Maya and can't run the tests.
5. **Don't add files nobody asked for** (new docs, guides, config, a second copy of these rules).
