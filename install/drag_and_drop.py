"""Drag this file into a Maya viewport to install Kaiju Suite.

It writes a kaiju_suite.mod file into your user modules folder that points
at this repo, then loads the plug-in right away and sets it to auto-load.
"""

import os
import sys

from maya import cmds

MODULE_NAME = "kaiju_suite"
PLUGIN_NAME = "kaiju_suite_plugin"
MAYA_VERSIONS = ("2025", "2026", "2027")


def install():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    repo = repo.replace("\\", "/")

    modules_dir = os.path.join(cmds.internalVar(userAppDir=True), "modules")
    os.makedirs(modules_dir, exist_ok=True)
    mod_path = os.path.join(modules_dir, f"{MODULE_NAME}.mod")

    version_str = _read_version(repo)
    with open(mod_path, "w") as f:
        for version in MAYA_VERSIONS:
            f.write(f"+ MAYAVERSION:{version} {MODULE_NAME} {version_str} {repo}\n")

    # Module paths only apply on restart, so make this session work now.
    scripts = f"{repo}/scripts"
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    plugin_path = f"{repo}/plug-ins/{PLUGIN_NAME}.py"
    if not cmds.pluginInfo(PLUGIN_NAME, query=True, loaded=True):
        cmds.loadPlugin(plugin_path)
    cmds.pluginInfo(plugin_path, edit=True, autoload=True)

    cmds.confirmDialog(
        title="Kaiju Suite",
        message=f"Installed Kaiju Suite {version_str}.\nModule file: {mod_path}",
        button=["OK"],
    )


def _read_version(repo):
    namespace = {}
    with open(f"{repo}/scripts/{MODULE_NAME}/__init__.py") as f:
        exec(f.read(), namespace)
    return namespace["__version__"]


def onMayaDroppedPythonFile(*_):
    install()
