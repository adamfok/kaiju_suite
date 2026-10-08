"""Folders: they hold and order other items, and nest. Run All on one runs
what's inside; disabling one makes Run All skip all of it."""

import os

from kaiju_suite.tools.assembler.products import Creator, Product, new_path


def create_folder(directory, name):
    path = new_path(directory, name, None)
    os.makedirs(path)
    return path


class FolderProduct(Product):
    name = "Folder"
    icon = "SP_DirIcon"
    order = 20
    can_disable = True  # Run All skips a disabled folder and everything in it
    creators = (Creator("Folder", lambda directory, name, _ext: create_folder(directory, name)),)

    def claims(self, path):
        return os.path.isdir(path)


PRODUCT = FolderProduct()
