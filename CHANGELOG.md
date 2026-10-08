# Changelog

## 0.2.0
- Assembler tool (ported from afk_tools Snippets Tool): browse a folder of `.py`/`.mel`/`.ma`/`.mb` snippets; open scripts in a Script Editor tab, run them as one undo step, import scenes, export the selection to a new scene, and add, move (drag and drop), or remove files and folders
- Changes from the original: Export Selected picks `.mb` or `.ma`; Overwrite Scene removed; name dialogs stay open on errors; hidden folders and `__pycache__` are not listed; delete confirmation names the item type
- Fix: tool windows failed to open after **Reload Kaiju Suite** ("workspace control name is not unique")

## 0.1.0
- Module skeleton, plug-in, and auto-generated Kaiju menu
- Core API: undo chunks, logging, settings, selection, naming
- Renamer tool
- Drag-and-drop installer
