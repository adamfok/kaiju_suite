import contextlib
import functools

from maya import cmds


@contextlib.contextmanager
def undo_chunk(name="kaiju"):
    """Group everything inside the block into a single undo step."""
    cmds.undoInfo(openChunk=True, chunkName=name)
    try:
        yield
    finally:
        cmds.undoInfo(closeChunk=True)


def undoable(func):
    """Decorator version of :func:`undo_chunk`."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with undo_chunk(func.__name__):
            return func(*args, **kwargs)

    return wrapper
