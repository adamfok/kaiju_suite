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


LAST_GROUP = 99


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
    order = 100  # the lower one wins an extension clash
    # Place in the New menu, as (group, position); a divider separates groups.
    # A product without one goes in a last group, by ``order``. ``None``
    # leaves it out of the menu.
    menu_slot = (LAST_GROUP, 0)
    runnable = False  # joins Run All
    versioned = False  # gets Publish and the Versions submenu (see ..versions)
    utility = None  # name of the Kaiju tool double-click opens, e.g. "Mesh Tool"
    columns_text = None  # fixed text for the Version and Type columns, e.g. a separator's "====="
    creators = ()

    @property
    def can_disable(self):
        """Whether items can be switched off so Run All skips them."""
        return self.runnable

    def claims(self, path):
        return os.path.isfile(path) and ext_of(path) in self.extensions

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

    def publish(self, path):
        """An :class:`Action` to run for right-click Publish on a versioned
        product, or ``None`` to save the file as it is as its next version
        (see ``versions.publish_action``)."""
        return None

    def publish_problems(self, path):
        """Pre-publish check: why ``path`` can't be published right now, as
        messages for the user. Publish doesn't run unless this is empty."""
        return []

    def publish_warnings(self, path):
        """Pre-publish warnings: things that look wrong but don't stop Publish,
        as messages. The user is asked whether to publish anyway."""
        return []

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


def ext_of(path):
    """``path``'s extension, lower case, with the dot."""
    return os.path.splitext(path)[1].lower()


def is_empty(path):
    """Whether ``path`` is an empty entry, created but not published into yet."""
    return os.path.getsize(path) == 0


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


def new_menu():
    """The New menu: ``(product, creator)`` pairs grouped by ``menu_slot``,
    with ``None`` for the divider between groups."""
    slotted = [p for p in all_products() if p.creators and p.menu_slot is not None]
    slotted.sort(key=lambda p: (p.menu_slot, p.order))
    entries, group = [], None
    for product in slotted:
        if group is not None and product.menu_slot[0] != group:
            entries.append(None)
        group = product.menu_slot[0]
        entries.extend((product, creator) for creator in product.creators)
    return entries


def extensions():
    """Every file extension some product claims, in product order."""
    return list(dict.fromkeys(ext for p in all_products() for ext in p.extensions))
