"""
Unreal startup script for Texture Autoloader: adds "Texture Autoloader…"
to the Content Browser's right-click menu and to the Tools menu.

Unreal runs every init_unreal.py it finds on its Python paths when the
editor starts. Add this folder (<repo>/unreal) to
Project Settings › Plugins › Python › Additional Paths and restart the
editor — see README.md in this folder.
"""
import os
import sys

try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
    if _HERE not in sys.path:
        sys.path.insert(0, _HERE)
except NameError:  # run without a file context: the folder is already on sys.path
    pass

import unreal

try:
    import texture_autoloader_unreal
    texture_autoloader_unreal.register_menus()
except Exception as e:  # never break the editor's startup over a menu entry
    unreal.log_warning(f"[TextureAutoloader] Could not add the menu entries: {e}")
