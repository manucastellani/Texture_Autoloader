# Maya front-end tests — Texture Autoloader

Covers the parts of `texture_autoloader_maya.py` that actually call
`maya.cmds` (resolving assigned materials, filtering to real meshes)
before handing the matching decision to the shared core. The core's own
logic (thresholds, UDIM, the Material ID fallback itself) is already
tested with zero stubs in `../../tests/` — this suite only checks that
the Maya-specific wrapper feeds it the right data.

## How to run

```bash
pip install pytest
pytest ruta/a/maya/tests -v
```

No Maya or Qt installation required — `stubs/` provides minimal
replacements for `maya.cmds`, `maya.OpenMayaUI`, `PySide6` and
`shiboken6` (just enough to import the module and exercise its non-UI
functions; see `stubs/PySide6/__init__.py`'s docstring for exactly what
it does and doesn't simulate).

## Why it copies the module into a temp folder before importing

`_app_dir()` resolves to "the folder next to this script", and the
module's own bootstrap adds `../core` (relative to its `__file__`) to
`sys.path` to reach the shared core. `conftest.py` copies both
`core/texture_autoloader_core.py` and `maya/texture_autoloader_maya.py`
into a pytest `tmp_path`, mirroring the real repo's folder layout, before
importing — so both of those `__file__`-relative lookups naturally land
inside the temp directory. Running the suite never writes
`texture_autoloader_config.json`, `_state.json`, or `.log` into the real
repo, and never needs to monkeypatch the module under test.

## What's NOT covered here (on purpose)

The Qt UI (`TextureAutoloaderDialog`: window construction, button
wiring, the language-toggle button, the channel tree) is not exercised
by this suite. Verifying it thoroughly would need a much heavier Qt stub
(real signals, a working `QButtonGroup`, a stateful `QLabel`, etc.) than
is worth maintaining for a bundled test suite — it was built and used
ad hoc during this tool's development, but wasn't kept as part of the
shipped repo to keep the suite simple to read. Manual testing inside
Maya is the way to validate the UI itself; this suite's job is to catch
regressions in the *decisions* the UI relies on (what matched what, and
why).
