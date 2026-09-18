"""
Texture Autoloader — one-time shelf installer for Maya (modular build)
========================================================================
Paste THIS file's contents into Maya's Script Editor (Python tab) and
run it ONCE. It asks you to pick the TextureAutoloader/advanced folder,
then adds a "Texture Autoloader" button to your current shelf. From then
on, just click that button — no more pasting scripts into the Script
Editor.

This installer itself doesn't need to know its own file location (it
only uses a folder picker), so it's safe to paste directly, unlike
texture_autoloader_maya.py itself — see that file's docstring and the
README for why the actual modular tool prefers being imported instead
of pasted. If you'd rather skip this installer entirely, paste
`maya/texture_autoloader_maya_standalone.py` (in the parent
TextureAutoloader folder) directly into the Script Editor instead — it
has no folder dependency at all.

Re-running this installer is safe: it won't create a duplicate button
for the same TextureAutoloader/advanced folder, it just re-points the
existing one (handy if you move the folder or update the repo).
"""

import os
import maya.cmds as cmds
import maya.mel as mel


_BUTTON_LABEL = "Texture\nAutoloader"
_BUTTON_ANNOTATION = "Open Texture Autoloader"


def _validate_repo_root(folder: str) -> bool:
    return (
        os.path.isfile(os.path.join(folder, "maya", "texture_autoloader_maya.py"))
        and os.path.isfile(os.path.join(folder, "core", "texture_autoloader_core.py"))
    )


def _current_shelf() -> str:
    top_shelf = mel.eval("$_tmp = $gShelfTopLevel")
    return cmds.tabLayout(top_shelf, query=True, selectTab=True)


def _find_existing_button(shelf: str) -> "str | None":
    for child in (cmds.shelfLayout(shelf, query=True, childArray=True) or []):
        try:
            if cmds.shelfButton(child, query=True, annotation=True) == _BUTTON_ANNOTATION:
                return child
        except Exception:
            continue
    return None


def install() -> None:
    result = cmds.fileDialog2(
        fileMode=3, dialogStyle=2,
        caption="Select the TextureAutoloader/advanced folder (contains 'core' and 'maya')")
    if not result:
        cmds.warning("Texture Autoloader: installation cancelled.")
        return

    repo_root = result[0].rstrip("/\\")
    if not _validate_repo_root(repo_root):
        cmds.warning(
            f"Texture Autoloader: '{repo_root}' doesn't look like the "
            f"TextureAutoloader/advanced folder — expected to find "
            f"core/texture_autoloader_core.py and maya/texture_autoloader_maya.py "
            f"inside it. Nothing was installed.")
        return

    # El comando queda "horneado" con la ruta elegida ahora — el shelf
    # button no depende de ningún __file__ ni de que Maya recuerde nada
    # entre sesiones, sólo de este string.
    core_dir = os.path.join(repo_root, "core").replace("\\", "/")
    maya_dir = os.path.join(repo_root, "maya").replace("\\", "/")
    command = (
        "import sys\n"
        f"for _d in ({core_dir!r}, {maya_dir!r}):\n"
        "    if _d not in sys.path:\n"
        "        sys.path.insert(0, _d)\n"
        "import texture_autoloader_maya as ta\n"
        "ta.create_ui()\n"
    )

    shelf = _current_shelf()
    existing = _find_existing_button(shelf)
    if existing:
        cmds.shelfButton(existing, edit=True, command=command, sourceType="python")
        cmds.warning(f"Texture Autoloader: existing shelf button on '{shelf}' updated.")
        return

    cmds.shelfButton(
        parent=shelf,
        label=_BUTTON_LABEL,
        annotation=_BUTTON_ANNOTATION,
        command=command,
        sourceType="python",
        image1="commandButton.png",
        style="iconAndTextVertical",
    )
    print(f"[TextureAutoloader] Shelf button added to '{shelf}'. Click it to open the tool.")


install()
