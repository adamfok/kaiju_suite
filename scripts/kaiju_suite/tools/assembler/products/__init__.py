"""Product types the Assembler knows: what each kind of item is and does.

A product is any module in this package that defines ``PRODUCT``, an
instance of a :class:`Product` subclass. Adding a product means adding a
module here; the Assembler's logic and window ask products for everything
type-specific (which files to list, how to run, menus).

No Qt here: icons are ``QStyle.StandardPixmap`` names; the widget turns
them into Qt objects.
"""

import importlib
import os
import pkgutil
from dataclasses import dataclass

from kaiju_suite.core.log import get_logger

log = get_logger(__name__)


@dataclass
class Action:
    """A right-click entry. ``fn()`` may return a message to show the user.

    If ``confirm`` is set, the widget asks it as a yes/no question first.
    """

    label: str
    fn: object
    confirm: str = None


@dataclass
class Panel:
    """What a double-click window shows: ``info`` lines, then one button per action.

    The window rebuilds it after every action, so it can reflect new state.
    """

    info: list
    actions: list


@dataclass
class Creator:
    """An "Add..." entry. ``fn(directory, name, ext)`` returns the new path.

    ``choices`` is a list of ``(label, ext)`` buttons, or ``None`` to ask
    for a name only (``ext`` is then ``None``). ``open_after`` opens the new
    item with :meth:`Product.open` once it's created.
    """

    label: str
    fn: object
    choices: list = None
    open_after: bool = False


class Product:
    name = ""
    extensions = ()  # lower case, with the dot
    icon = None  # QStyle.StandardPixmap name, e.g. "SP_DirIcon"
    order = 100  # menu order; the lower one wins an extension clash
    runnable = False  # joins Run All
    versioned = False  # gets Publish and the Versions submenu (see ..versions)
    creators = ()

    @property
    def can_disable(self):
        """Whether items can be switched off so Run All skips them."""
        return self.runnable

    def claims(self, path):
        return os.path.isfile(path) and os.path.splitext(path)[1].lower() in self.extensions

    def run(self, path):
        """One step of a build. Only called on runnable products."""
        raise NotImplementedError(f"{self.name} can't be run")

    def actions(self, path):
        """Extra right-click entries for ``path``, as :class:`Action`s."""
        return []

    def open(self, path):
        """Double-click. Does nothing unless overridden; may return a message."""
        return None

    def panel(self, path):
        """A :class:`Panel` to show in a window on double-click instead of :meth:`open`."""
        return None

    def before_replace(self, path):
        """Called just before the Assembler overwrites ``path`` on disk, e.g.
        to restore a version. Does nothing unless overridden."""
        return None


def new_path(directory, name, ext):
    """Validate a new item's name and return its path in ``directory``.

    ``ext`` is appended unless the name already ends with it; pass ``None``
    for folders.
    """
    name = name.strip()
    if not name:
        raise ValueError("Please provide a name.")
    if "/" in name or "\\" in name:
        raise ValueError("Name can't contain path separators.")
    if ext and not name.lower().endswith(ext):
        name += ext
    path = os.path.join(directory, name)
    if os.path.exists(path):
        raise FileExistsError(f"Already exists: {name}")
    return path


def discover():
    """Import every product module and return their products, by ``order``."""
    found = []
    for info in pkgutil.iter_modules(__path__):
        module_name = f"{__name__}.{info.name}"
        try:
            module = importlib.import_module(module_name)
        except Exception:
            log.exception("Failed to import Assembler product %s", module_name)
            continue
        product = getattr(module, "PRODUCT", None)
        if isinstance(product, Product):
            found.append(product)
    found.sort(key=lambda p: p.order)

    owners = {}
    for product in found:
        for ext in product.extensions:
            if ext in owners:
                log.warning("%s and %s both claim %s; %s wins", owners[ext].name, product.name, ext, owners[ext].name)
            else:
                owners[ext] = product
    return found


_cache = None


def all_products():
    """Discovered products, cached after the first call."""
    global _cache
    if _cache is None:
        _cache = discover()
    return _cache


def product_for(path):
    """The product that owns ``path``, or ``None`` if nothing does."""
    return next((p for p in all_products() if p.claims(path)), None)


def extensions():
    """Every file extension some product claims, in product order."""
    return list(dict.fromkeys(ext for p in all_products() for ext in p.extensions))
