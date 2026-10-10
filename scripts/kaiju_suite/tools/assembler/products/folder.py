"""Folders: they hold and order other items, and nest. Running one runs
what's inside; disabling one makes Run All skip all of it. Double-clicking
one opens it in the system file browser (Explorer on Windows).

Publishing a folder records its build plan with the version of every item
in it; restoring a folder version rebuilds the folder to match, adding and
removing items as needed (see ..folder_versions)."""

import os
import subprocess
import sys

from kaiju_suite.tools.assembler.products import Creator, Product, new_path


def create_folder(directory, name):
    path = new_path(directory, name, None)
    os.makedirs(path)
    return path


def _launch(path):
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def open_in_file_browser(path):
    """Open ``path`` in Explorer (Finder on macOS, the default file manager on Linux)."""
    if not os.path.isdir(path):
        raise FileNotFoundError(f"Folder not found: {path}")
    _launch(os.path.normpath(path))


class FolderProduct(Product):
    name = "Folder"
    icon = "SP_DirIcon"
    order = 20
    menu_slot = (1, 1)
    can_disable = True  # Run All skips a disabled folder and everything in it
    versioned = True  # its versions record its build plan and items' versions
    creators = (Creator("Folder", lambda directory, name, _ext: create_folder(directory, name)),)

    def claims(self, path):
        return os.path.isdir(path)

    def open(self, path):
        open_in_file_browser(path)

    def publish_problems(self, path):
        from kaiju_suite.tools.assembler import versions  # lazily: versions imports the products

        return versions.folder_publish_problems(path)


PRODUCT = FolderProduct()
