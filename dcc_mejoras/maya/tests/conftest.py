"""
Pytest config for the Maya front-end's tests. Doesn't require Maya or Qt
installed: stubs/ provides minimal replacements for maya.cmds,
maya.OpenMayaUI, PySide6 and shiboken6.

The Maya module imports the shared core via a relative sys.path bootstrap
(see the top of texture_autoloader_maya.py: it adds "../core" next to
its own __file__). To keep that working AND keep tests from writing
config/state/log files into the real repo, this fixture copies BOTH
`core/texture_autoloader_core.py` and `maya/texture_autoloader_maya.py`
into a temporary directory that mirrors the real repo's folder layout
(`<tmp>/core/...` next to `<tmp>/maya/...`) before importing. That way
`_app_dir()` (which resolves to "the folder next to this script") and
the core-import bootstrap both naturally resolve inside the temp
directory — no monkeypatching needed.
"""
import os
import sys
import shutil
import importlib.util

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_STUBS_DIR = os.path.join(_HERE, "stubs")
_MAYA_DIR = os.path.dirname(_HERE)            # .../TextureAutoloader/advanced/maya
_REPO_ROOT = os.path.dirname(_MAYA_DIR)       # .../TextureAutoloader/advanced
_CORE_SOURCE = os.path.join(_REPO_ROOT, "core", "texture_autoloader_core.py")
_MAYA_SOURCE = os.path.join(_MAYA_DIR, "texture_autoloader_maya.py")

if _STUBS_DIR not in sys.path:
    sys.path.insert(0, _STUBS_DIR)


def _fresh_import(tmp_path):
    tmp_core_dir = tmp_path / "core"
    tmp_maya_dir = tmp_path / "maya"
    tmp_core_dir.mkdir()
    tmp_maya_dir.mkdir()
    shutil.copyfile(_CORE_SOURCE, tmp_core_dir / "texture_autoloader_core.py")
    shutil.copyfile(_MAYA_SOURCE, tmp_maya_dir / "texture_autoloader_maya.py")

    # Never reuse a texture_autoloader_core module cached from a
    # different tmp copy in an earlier test — always load the one that
    # lives next to THIS test's maya copy.
    sys.modules.pop("texture_autoloader_core", None)

    spec = importlib.util.spec_from_file_location(
        "texture_autoloader_maya_under_test", str(tmp_maya_dir / "texture_autoloader_maya.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ta(tmp_path):
    """Fixture principal: módulo texture_autoloader_maya recién importado
    (desde una copia aislada en tmp_path, junto a su propia copia de
    core/), con el stub de maya.cmds reseteado entre tests."""
    import maya.cmds as maya_cmds
    maya_cmds.reset()
    return _fresh_import(tmp_path)
