"""
Pytest config for the Unreal port's pure helpers (no Unreal needed).

texture_autoloader_unreal.py does `import unreal` at the top, so a bare
stand-in module is registered first; the functions tested here never
touch it. Everything that does (importing textures, Material Instances,
slots) is covered by run_in_unreal.py, inside a real editor.

Like the Maya tests, the module is imported from a temp copy that mirrors
the repo layout (unreal/ next to dcc_mejoras/core/), so the config / log
files it writes next to itself never land in the repo.
"""
import importlib.util
import os
import shutil
import sys
import types

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_UNREAL_DIR = os.path.dirname(_HERE)
_REPO = os.path.dirname(_UNREAL_DIR)


@pytest.fixture
def tal(tmp_path):
    sys.modules["unreal"] = types.ModuleType("unreal")
    (tmp_path / "unreal").mkdir()
    (tmp_path / "dcc_mejoras" / "core").mkdir(parents=True)
    shutil.copyfile(os.path.join(_UNREAL_DIR, "texture_autoloader_unreal.py"),
                    tmp_path / "unreal" / "texture_autoloader_unreal.py")
    shutil.copyfile(os.path.join(_REPO, "dcc_mejoras", "core", "texture_autoloader_core.py"),
                    tmp_path / "dcc_mejoras" / "core" / "texture_autoloader_core.py")
    sys.modules.pop("texture_autoloader_core", None)
    spec = importlib.util.spec_from_file_location(
        "texture_autoloader_unreal_under_test", str(tmp_path / "unreal" / "texture_autoloader_unreal.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("unreal", None)
