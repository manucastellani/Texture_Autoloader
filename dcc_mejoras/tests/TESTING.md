# Core tests — Texture Autoloader

These tests cover `core/texture_autoloader_core.py` only: the naming,
matching, UDIM, config/state, and i18n logic shared by both the Maya and
Blender front-ends. **No stubs needed** — the core module has zero
dependencies on Maya, Blender, or any GUI toolkit, so these tests just
`import texture_autoloader_core` directly.

For the Maya-specific wrapper (the parts that actually call `maya.cmds`
and build the Qt UI), see `../maya/tests/` instead — that suite needs
stub packages, documented there. There is currently no equivalent stub
suite for the Blender wrapper (see "Known gaps" below).

## How to run

```bash
pip install pytest
pytest ruta/a/tests -v
```

## What's covered

- **`test_core_pure_functions.py`** — name normalization (mesh/material/
  texture), the UDIM-tile-vs-resolution-suffix distinction, map-type
  bucketing, and the recent-folders/threshold helpers.
- **`test_core_matching.py`** — `match_objects_to_textures` (the
  DCC-agnostic entry point both front-ends call, given pre-resolved
  `(object_name, material_or_none)` pairs), including the Material ID
  fallback to object-name matching, and `apply_auto_textures`'s
  respect for per-channel enable/disable flags and its cancel callback.
- **`test_core_config_and_state.py`** — config load/merge/corruption
  handling, state round-trips, and that `ensure_rapidfuzz()` never
  attempts a network install.
- **`test_core_i18n.py`** — the shared EN/ES translation table: every
  key exists in both languages, and every `{placeholder}` in a template
  matches between languages (so `tr(lang, key, **kwargs)` can't silently
  break in only one language).

## Known gaps (documented, not hidden)

- The Maya Qt UI and the Blender Panel/Operators are not exercised by
  any automated test in this repo — see `../maya/tests/TESTING.md` for
  the reasoning on the Maya side. The Blender side doesn't have a stub
  suite at all yet; testing `bpy`-dependent code needs a stub of
  Blender's Python API, which wasn't built for this release. Manual
  testing in Blender is currently the way to validate the addon.
- The actual node wiring (Arnold shading network / Blender's Principled
  BSDF node graph) is not verified beyond "the calls don't raise" — a
  stub can't tell you the render looks right. That still needs a real
  Maya or Blender scene.
