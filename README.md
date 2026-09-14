# Texture Autoloader

*[Leer en español](README.es.md)*

A texture auto-loader for Maya (Arnold) and Blender. Point it at a
folder of Substance-exported textures, and it fuzzy-matches each mesh in
your scene to the right texture set by name — or by the material it
already has assigned — then wires a shader for you: `aiStandardSurface`
in Maya, a Principled BSDF node graph in Blender.

This exists because re-wiring shading networks by hand after every
Substance export is repetitive, error-prone, and doesn't scale past a
handful of assets. Texture Autoloader turns "reconnect 8 texture maps
per object, for 40 objects" into "scan a folder, review the matches,
click Apply."

|                Maya                |               Blender                |
|:-----------------------------------:|:-------------------------------------:|
| ![Texture Autoloader in Maya](docs/screenshot_maya.png) | ![Texture Autoloader in Blender](docs/screenshot_blender.png) |

## What it actually does

1. **Scan** a folder (optionally recursive) for texture files, grouping
   them into sets by their base asset name (stripping map-type suffixes
   like `_BaseColor`, `_Roughness`, resolution/UDIM modifiers, etc.).
2. **Match** each selected mesh to a texture set, either by the mesh's
   own name or by the name of the material already assigned to it (with
   automatic fallback to name-matching if the mesh has no material of
   its own yet). Matching is fuzzy (typo/substring tolerant) with an
   adjustable sensitivity threshold.
3. **Preview** the match per object, per channel, before touching the
   scene — disable a channel you don't want, or manually reassign a
   texture set or a single file.
4. **Apply**: creates a new shader per object and wires baseColor,
   roughness, metallic, normal, emission, ambient occlusion (multiplied
   into base color), opacity, and — opt-in only — displacement.

## Why displacement is opt-in, and why UDIM detection has a denylist

Two decisions worth knowing about before you use this on a real asset:

- **Displacement deforms actual render geometry.** Wiring a
  height/displacement map without a hand-tuned displacement scale and
  mesh subdivision leaves the object looking inflated. This tool detects
  displacement maps and reports them, but does **not** wire them unless
  you explicitly turn on `enable_displacement_wiring` in the config.
- **UDIM detection is bounded to tile numbers 1001–1999, with a denylist
  of common resolution suffixes** (512, 1024, 2048, 4096, 8192, 16384).
  Without this, two exports of the same map at different resolutions
  (e.g. `Wall_BaseColor_1024.png` and `Wall_BaseColor_2048.png`) get
  misread as UDIM tiles, which breaks tiling in the renderer.

Both of these came from hitting the actual failure mode in production
and are documented in more detail in the code comments where they're
implemented.

## Repository structure

```
TextureAutoloader/
├── maya/
│   └── texture_autoloader_maya_standalone.py     # paste into the Script Editor and run — that's it
├── blender/
│   └── texture_autoloader_blender_standalone.py  # Install... this one file — that's it
├── advanced/                       # modular build — see "Advanced / modular build" below
│   ├── core/
│   │   └── texture_autoloader_core.py
│   ├── maya/
│   │   ├── texture_autoloader_maya.py
│   │   ├── install_shelf_button.py
│   │   └── tests/
│   ├── blender/
│   │   └── texture_autoloader_blender.py
│   └── tests/
├── LICENSE
└── .gitignore
```

If you just want to use the tool, everything you need is the single
file in `maya/` or `blender/` above — nothing else in this repo matters
to you. `advanced/` holds a second, modular build of the exact same
tool, kept only for people extending or maintaining the matching logic
itself; skip straight to [Advanced / modular build](#advanced--modular-build)
if that's you, otherwise ignore that folder entirely.

## Installation

### Maya

Open `maya/texture_autoloader_maya_standalone.py`, copy the whole file,
paste it into Maya's Script Editor (Python tab), and run it — the tool
opens immediately, no dialogs, no folder to pick, ever. Paste it again
any time you want to reopen it. Its config/state/log files live in
Maya's own per-user preferences folder rather than "next to the
script," since a pasted script has no folder of its own.

### Blender

In Blender: **Edit > Preferences > Add-ons > Install...**, pick
`blender/texture_autoloader_blender_standalone.py`, enable it. Open the
3D Viewport's Sidebar (press `N`) — there's a **Texture Autoloader**
tab.

Both files are fully self-contained (single file, no imports from the
rest of this repo) — that's the whole install.

## Advanced / modular build

Everything below this point is only relevant if you're going to modify
the matching/naming logic itself, want Maya and Blender to always stay
perfectly in sync on that logic, or want to run the automated test
suite. If you just want to use the tool, you don't need any of this —
see Installation above.

The modular build lives in `advanced/`: `advanced/core/texture_autoloader_core.py`
has **zero dependencies on Maya, Blender, or any GUI toolkit**. Name
normalization, fuzzy matching, UDIM collapsing, map-type bucketing,
config/state persistence, logging, and the English/Spanish translation
table all live there, shared by both front-ends
(`advanced/maya/texture_autoloader_maya.py` and
`advanced/blender/texture_autoloader_blender.py`). Each front-end only
adds what's genuinely specific to its host application: the actual
shader-node wiring, and the UI. This is also why the two UIs can never
drift out of sync on translated strings — they read from the same
table. The two single-file builds under `maya/` and `blender/` inline
this same logic by hand and are not generated from it, so a change made
here needs to be manually ported to those files too.

### Installing the modular build

**Maya** — keep `advanced/`'s folder structure intact
(`advanced/maya/texture_autoloader_maya.py` needs its sibling `core/`
folder) and either add `advanced/maya/` to your Maya script path and run
```python
import texture_autoloader_maya as ta
ta.create_ui()
```
or use the one-time shelf installer, `advanced/maya/install_shelf_button.py`
(paste it into the Script Editor and run it once — it asks you to pick
the `TextureAutoloader/advanced` folder, then adds a shelf button so
future runs are a single click). **Don't paste
`advanced/maya/texture_autoloader_maya.py` itself directly into the
Script Editor** — it depends on finding its sibling `core/` folder on
disk, which a pasted script can't do; use `maya/texture_autoloader_maya_standalone.py`
if you want to paste-and-run.

**Blender** — keep the repo's folder structure intact and load
`advanced/blender/texture_autoloader_blender.py` as a *script* from
within Blender's Text Editor (Run Script), or add `advanced/blender/`
to Blender's `scripts/addons` path yourself, rather than using
"Install..." on the file directly (Blender's single-file installer only
copies that one file, not its sibling `core/` folder, and the addon
will fail with `RuntimeError: No module named 'texture_autoloader_core'`
if you try). `advanced/blender/` and `advanced/core/` need to stay
siblings.

## Configuration

The first run creates `texture_autoloader_config.json` next to the
running script, pre-filled with sensible defaults. Key options:

| Key | What it does |
|---|---|
| `mesh_prefixes` | Studio naming prefixes stripped before matching (`SM_`, `SK_`, ...) |
| `match_threshold` | Default fuzzy-match sensitivity (0.0–1.0); adjustable per-session from the UI |
| `match_mode` | `"object_name"` or `"material_id"` — default matching strategy |
| `enable_udim_detection` | Turn off if your naming convention triggers UDIM false positives |
| `enable_displacement_wiring` | Off by default — see above |
| `language` | `"en"` or `"es"` — default UI language |
| `suffix_strip_list` / `map_types` | The map-type vocabulary (baseColor, roughness, ...) — extend if your Substance export preset uses different suffixes |

Personal session preferences (last folder used, last threshold, last
match mode, language) are kept separately in
`texture_autoloader_state.json`, so they never overwrite the shared
studio config.

## Testing

Only the modular build in `advanced/` has an automated test suite (the
standalone files are hand-copied from it and aren't independently
tested):

```bash
pip install pytest
pytest advanced/tests -v        # core logic, no Maya/Blender/Qt needed
pytest advanced/maya/tests -v   # Maya wrapper, needs no real Maya install (stubs included)
```

There's currently no automated test suite for the Blender addon or for
either UI layer (Qt dialog, Blender panel) — see `advanced/tests/TESTING.md`
and `advanced/maya/tests/TESTING.md` for exactly what is and isn't
covered, and why. Manual testing inside the actual DCC is still the way
to validate the UI and the real shader output.

## Known limitations

- Fuzzy matching relies on [rapidfuzz](https://github.com/rapidfuzz/rapidfuzz)
  if it's installed in your Maya/Blender Python, and falls back to the
  standard-library `difflib` otherwise — no auto-install, no network
  calls without you asking for them.
- The Blender port is newer than the Maya version and has had less
  real-world mileage — please report anything that looks off, especially
  around UDIM handling and node socket names (Blender has renamed a few
  Principled BSDF sockets across versions).
- No thumbnail previews, and no "save this channel setup as a preset per
  character" yet — both noted as reasonable next steps.

## License

MIT — see [LICENSE](LICENSE).
