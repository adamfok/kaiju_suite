# Changelog

## Unreleased
- Assembler: disable or enable scripts from the right-click menu; disabled scripts are shown crossed out
- Assembler: select several scripts (Ctrl/Shift-click) and run them together in tree order, including disabled ones, as one undo step; stops at the first failing script
- Assembler: **Run All** on a folder (or on empty space for the whole snippets folder) runs every enabled script under it, top to bottom, as one undo step
- Assembler: drag items between others to reorder them; the order and disabled state are saved in a hidden `.assembler.json` in each folder, so they survive reopening and travel with the folder. New files appear at the bottom
- Assembler: the folder path field is gone; the folder button now opens the folder picker directly, starting in the current snippets folder (hover it to see the path)

## 0.2.0
- Assembler tool (ported from afk_tools Snippets Tool): browse a folder of `.py`/`.mel`/`.ma`/`.mb` snippets; open scripts in a Script Editor tab, run them as one undo step, import scenes, export the selection to a new scene, and add, move (drag and drop), or remove files and folders
- Changes from the original: Export Selected picks `.mb` or `.ma`; Overwrite Scene removed; name dialogs stay open on errors; hidden folders and `__pycache__` are not listed; delete confirmation names the item type
- Fix: tool windows failed to open after **Reload Kaiju Suite** ("workspace control name is not unique")

## 0.1.0
- Module skeleton, plug-in, and auto-generated Kaiju menu
- Core API: undo chunks, logging, settings, selection, naming
- Renamer tool
- Drag-and-drop installer
