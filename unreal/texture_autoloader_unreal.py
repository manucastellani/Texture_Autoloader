"""
Texture Autoloader — Unreal Engine front-end (work in progress)
================================================================
Author: Manuel Castellani

Unreal Engine port of Texture Autoloader, via the Python Editor Scripting
API. Same scanning/matching/UDIM/map-type logic as the Maya and Blender
versions, shared through dcc_mejoras/core/texture_autoloader_core.py —
this file only adds what is genuinely Unreal-specific (texture import as
assets, Material Instances bound to a Master Material's parameters, one
texture set per Material Slot). See CLAUDE.md, "Port a Unreal Engine".

Status: only the core bootstrap below. No Unreal logic yet.
"""

import os
import sys


# ══════════════════════════════════════════════════════════════
#  Bootstrap: hace importable el core compartido. Mismo patrón que
#  los front-ends de Maya y Blender, pero el core no es una carpeta
#  hermana: vive en dcc_mejoras/core/ (un solo core para los tres
#  DCCs, ver CLAUDE.md).
# ══════════════════════════════════════════════════════════════

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_CORE_DIR = os.path.join(os.path.dirname(_THIS_DIR), "dcc_mejoras", "core")
if _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)

import texture_autoloader_core as core  # noqa: E402
