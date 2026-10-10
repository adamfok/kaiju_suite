"""Separators (.sep): empty files that divide the tree into sections.

They aren't run, versioned or disabled; the Version and Type columns show
``=====`` so they stand out as dividers.
"""

from kaiju_suite.tools.assembler.products import Creator, Product, new_path

EXTENSION = ".sep"


def create_separator(directory, name):
    """Create an empty separator named ``name`` and return its path."""
    path = new_path(directory, name, EXTENSION)
    with open(path, "w", encoding="utf-8"):
        pass
    return path


class SeparatorProduct(Product):
    name = "Separator"
    extensions = (EXTENSION,)
    order = 130
    top_menu = True
    columns_text = "====="
    creators = (Creator("Separator", lambda directory, name, _ext: create_separator(directory, name)),)


PRODUCT = SeparatorProduct()
