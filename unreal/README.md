# Texture Autoloader — Unreal Engine port (work in progress)

Point it at a folder of Substance Painter exports, select meshes in the
Content Browser, and it imports the textures, builds one **Material
Instance** per texture set from a Master Material, and assigns each one to
the right **Material Slot**.

It uses the same scanning / matching / naming-preset logic as the Maya and
Blender versions (`../dcc_mejoras/core/`). What changes in Unreal:

- **Slots, not objects.** A mesh with 3 material slots can need 3 texture
  sets. Each slot is matched trying, most specific first,
  `<mesh>_<slot>` (Substance's default `$mesh_$textureSet` export naming),
  `<slot>`, and `<mesh>`. So slot `Body` on `SM_Hero` picks `Hero_Body`
  even when `Villain_Body` is in the same folder. Slots with a generic name
  (`None`, `WorldGridMaterial`, …) fall back to the mesh name.
- **Parameter binding, not wiring.** Textures are imported as assets
  (sRGB / compression set per channel) and bound to the texture parameters
  of a Master Material through a Material Instance, which is created or
  updated in place on later runs.

Tested on Unreal Engine 5.7 and 5.8.

## Setup

1. In your project, enable the **Python Editor Script Plugin** and
   **Editor Scripting Utilities** plugins.
2. Keep the repo's layout: `unreal/` must stay next to `dcc_mejoras/`.
3. **Project Settings › Plugins › Python › Additional Paths**: add the
   path to this `unreal/` folder. Restart the editor.

`init_unreal.py` then adds **Texture Autoloader…** to the Content
Browser's right-click menu and to **Tools**.

## Use

1. Select one or more Static Meshes / Skeletal Meshes in the Content Browser.
2. Right-click › **Texture Autoloader…**
3. Pick the texture folder and options in the dialog.
4. Check the preview (which texture set each slot got, which files go
   to which channel) and confirm.
5. The ✔/✘ report shows what happened to every file (also in the Output
   Log and in `texture_autoloader.log`).

From a script, without dialogs:

```python
import texture_autoloader_unreal as tal
matches, report = tal.process_folder(tal.get_selected_meshes(), r"D:/exports/Hero")
```

## Master Material

If the configured Master Material doesn't exist, a default one is
generated at `/Game/TextureAutoloader/`, plus a **Masked** variant used
for texture sets that have an opacity map. Their parameters default to
neutral textures (white AO, black metallic, flat normal…), so a set that
lacks a channel still looks right.

To use your own Master Material, set its path in
`texture_autoloader_config.json` (created next to this file on first
run), under `"unreal"`:

| Key | Default |
|---|---|
| `master_material` / `master_material_masked` | `/Game/TextureAutoloader/M_TextureAutoloader_Master[_Masked]` |
| `parameters` | `BaseColor`, `Normal`, `Roughness`, `Metallic`, `AmbientOcclusion`, `Emissive`, `Opacity` — texture parameter name per channel |
| `texture_folder` | `/Game/TextureAutoloader/Textures` (one sub-folder per texture set) |
| `material_instance_folder` | `""` = next to each mesh |
| `texture_prefix` / `material_instance_prefix` | `T_` / `MI_` |
| `texture_settings` | per-channel override of the import settings, e.g. `{"roughness": {"compression": "TC_GRAYSCALE"}}` |

Textures are imported to match the default master's sampler types: base
color and emissive as sRGB (**Color**), normal maps as **Normal**, and
roughness / metallic / AO / opacity as linear **Masks**. If your master
samples a channel differently, override it in `texture_settings`, or
Unreal will flag the sampler mismatch.

A channel your master has no parameter for shows up as ✘ in the report.

## Known limitations

- **UDIM** sets are reported (✘) and skipped. Unreal imports UDIMs as
  virtual textures, which need a virtual-texture sampler in the master.
- **Displacement** isn't bound (opt-in in the other DCCs; Unreal needs
  Nanite tessellation or WPO for it).
- Packed textures (e.g. `_OcclusionRoughnessMetallic`) aren't split.

## Tests

- `pytest unreal/tests -v` — the pure helpers, no Unreal needed.
- `unreal/tests/run_in_unreal.py` — the whole flow inside a real editor,
  headless, on a **throwaway** project (it creates and deletes
  `/Game/TAL_Test`):

  ```
  UnrealEditor-Cmd.exe <Sandbox>.uproject -run=pythonscript -script="<repo>/unreal/tests/run_in_unreal.py" -unattended -nop4 -nosplash -NullRHI
  ```

  On **5.7**, add `-ini:Engine:[ConsoleVariables]:Interchange.FeatureFlags.Import.PNG=0`:
  5.7's Interchange importer asserts when there is no Slate UI (commandlet
  mode). That's a test-only workaround; inside the editor, Interchange
  works normally.
