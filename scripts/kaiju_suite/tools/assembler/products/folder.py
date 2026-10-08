"""Folders: they hold and order other items; Run All on one runs what's inside."""

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
    creators = (Creator("Folder", lambda directory, name, _ext: create_folder(directory, name)),)

    def claims(self, path):
        return os.path.isdir(path)


PRODUCT = FolderProduct()
