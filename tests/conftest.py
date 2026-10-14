"""Run with mayapy:  mayapy -m pytest tests"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))


def pytest_configure(config):
    import maya.standalone

    maya.standalone.initialize(name="python")


def pytest_unconfigure(config):
    import maya.standalone

    maya.standalone.uninitialize()


@pytest.fixture
def new_scene():
    from maya import cmds

    cmds.file(new=True, force=True)
    yield
    cmds.file(new=True, force=True)


@pytest.fixture
def maya_errors():
    """Maya's error and warning output while the test runs."""
    from maya.api import OpenMaya as om

    found = []
    kinds = (om.MCommandMessage.kError, om.MCommandMessage.kWarning)
    callback = om.MCommandMessage.addCommandOutputCallback(lambda message, kind, *_: kind in kinds and found.append(message))
    yield found
    om.MMessage.removeCallback(callback)
