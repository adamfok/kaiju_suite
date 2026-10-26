import logging

ROOT = "kaiju_suite"


def get_logger(name):
    """Return a logger under the ``kaiju_suite`` namespace.

    Pass ``__name__`` from the calling module.
    """
    if not name.startswith(ROOT):
        name = f"{ROOT}.{name}"
    return logging.getLogger(name)
