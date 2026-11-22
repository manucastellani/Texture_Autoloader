# Tests

Two layers, and they answer different questions.

## Unit tests (`advanced/tests`, `advanced/maya/tests`)

The matching logic, the config/state files and the translation table, with no
Maya and no Blender involved — `maya.cmds` is replaced by a stub. Fast, run
anywhere:

```bash
pip install pytest
pytest advanced/tests -v        # the shared core
pytest advanced/maya/tests -v   # the Maya wrapper and the wiring, on the stub
```

## Integration tests (this folder)

The unit suites cannot tell whether the shading network really gets built: a
stub accepts any `connectAttr`. Every bug fixed in this round shipped while
those suites were green — a UDIM set that silently became one texture set per
tile, a displacement map that displaced by a constant, a texture node left
dangling in the scene. These scripts build the real thing inside a real Maya
and a real Blender, headless, and inspect the connections, the attributes and
the colorspaces.

They also cover the single-file builds in `maya/` and `blender/`, which is
what the README tells people to install and what the unit suites never touch.

```bash
# Maya (needs Arnold for aiStandardSurface)
"C:/Program Files/Autodesk/Maya2027/bin/mayapy.exe" tests/integration_maya.py
"C:/Program Files/Autodesk/Maya2027/bin/mayapy.exe" tests/integration_maya.py --build modular

# Blender
blender -b --factory-startup --python-exit-code 1 --python tests/integration_blender.py
blender -b --factory-startup --python-exit-code 1 --python tests/integration_blender.py -- --build modular
```

`--build standalone` is the default and tests the single-file build;
`--build modular` tests the one under `advanced/`. Both exit non-zero when a
check fails, so they can run in CI if a machine has the DCCs installed.

Each run works inside a temp folder: the module is loaded from a copy there, so
the `texture_autoloader_config.json` / `_state.json` / `.log` it writes next to
itself never land in the repo or in your Maya preferences. Test textures are
tiny PNGs generated on the fly, so there are no binary fixtures in the repo.

Verified on Maya 2022 (PySide2, Python 3.7) and 2027 (PySide6) with Arnold, and
on Blender 5.0 and 5.2.

### One thing worth knowing

`rapidfuzz` changes the scores. Maya picks it up from the user's
site-packages if it is installed there; Blender does not, so Blender always
uses the `difflib` fallback. Both paths are exercised by the unit tests, and
the tool says in the log which one it is using.
