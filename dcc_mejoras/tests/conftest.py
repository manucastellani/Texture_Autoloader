"""
Shared pytest config for the core (DCC-agnostic) test suite.

Unlike the Maya-specific tests (see ../maya/tests/), these need NO stubs
at all: texture_autoloader_core.py has zero dependencies on maya, bpy, or
any GUI toolkit, and every function that touches disk (config/state/log)
takes the target directory as an explicit argument instead of resolving
it internally — so tests just point it at pytest's own `tmp_path` and
nothing ever touches the real repo.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
_CORE_DIR = os.path.join(_REPO_ROOT, "core")

if _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)

import texture_autoloader_core as core  # noqa: E402

import pytest


@pytest.fixture
def core_module():
    return core


@pytest.fixture
def app_dir(tmp_path):
    """A throwaway directory for config/state/log — never the real repo."""
    return str(tmp_path)
