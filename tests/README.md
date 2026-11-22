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
pytest unreal/tests -v          # the Unreal port's pure helpers
```

None of the DCC interpreters ship pytest, and those are the ones worth
checking — mayapy is the Python the tool actually runs on, and Maya 2022's is
3.7. `run_unit_tests.py` runs the same suites with no dependencies at all:

```bash
"C:/Program Files/Autodesk/Maya2022/bin/mayapy.exe" tests/run_unit_tests.py
"C:/Program Files/Blender Foundation/Blender 5.2/5.2/python/bin/python.exe" tests/run_unit_tests.py
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

# Unreal, on a throwaway project (it creates and deletes /Game/TAL_Test)
UnrealEditor-Cmd.exe <Sandbox>.uproject -run=pythonscript \
    -script="<repo>/tests/integration_unreal.py" -unattended -nop4 -nosplash -NullRHI
```

The Unreal one is the odd one out: a commandlet's exit code doesn't follow
the script, so read its result from the file named by `TAL_UNREAL_RESULT`
(default `%TEMP%/tal_unreal_result.txt`). On Unreal 5.7 add
`-ini:Engine:[ConsoleVariables]:Interchange.FeatureFlags.Import.PNG=0` — 5.7's
Interchange importer asserts when there is no Slate UI, which only happens in
commandlet mode. Give each engine version **its own** throwaway project:
assets saved by 5.8 can't be opened by 5.7, and the leftovers make the next
run fail in its own setup rather than in the tool.

Also worth running, and the reason the single-file builds can be trusted:

```bash
python build_standalone.py --check   # are the generated builds up to date?
```

`--build standalone` is the default and tests the single-file build;
`--build modular` tests the one under `advanced/`. Both exit non-zero when a
check fails, so they can run in CI if a machine has the DCCs installed.

Each run works inside a temp folder: the module is loaded from a copy there, so
the `texture_autoloader_config.json` / `_state.json` / `.log` it writes next to
itself never land in the repo or in your Maya preferences. Test textures are
tiny PNGs generated on the fly, so there are no binary fixtures in the repo.

Verified on Maya 2022 (PySide2, Python 3.7) and 2027 (PySide6) with Arnold, on
Blender 5.0 and 5.2, and on Unreal 5.7 and 5.8.

### One thing worth knowing

`rapidfuzz` changes the scores. Maya picks it up from the user's
site-packages if it is installed there; Blender does not, so Blender always
uses the `difflib` fallback. Both paths are exercised by the unit tests, and
the tool says in the log which one it is using.
