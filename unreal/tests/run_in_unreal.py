"""
Integration test for the Unreal port, run INSIDE Unreal Editor as a
commandlet (headless, no UI) on a throwaway project:

    UnrealEditor-Cmd.exe <Sandbox>.uproject -run=pythonscript
        -script="<repo>/unreal/tests/run_in_unreal.py" -unattended -nop4 -nosplash -NullRHI

Use a throwaway project: the test creates everything under /Game/TAL_Test
and deletes that folder when it starts. The result (every check + PASSED /
FAILED) is printed to the log and written to the file in the
TAL_UNREAL_RESULT environment variable (default: %TEMP%/tal_unreal_result.txt).

The module and the core are copied to a temp folder first (same layout as
the repo), so the config / state / log files the tool writes "next to
itself" never touch the repo.
"""
import os
import shutil
import struct
import sys
import tempfile
import traceback
import zlib

import unreal

_HERE = os.path.dirname(os.path.abspath(__file__))
_UNREAL_DIR = os.path.dirname(_HERE)
_REPO = os.path.dirname(_UNREAL_DIR)
RESULT_FILE = os.environ.get("TAL_UNREAL_RESULT",
                             os.path.join(tempfile.gettempdir(), "tal_unreal_result.txt"))
ROOT = "/Game/TAL_Test"

_lines = []


def out(line=""):
    _lines.append(line)
    unreal.log(line)


def check(condition, message, failures):
    out(("  ok    " if condition else "  FAIL  ") + message)
    if not condition:
        failures.append(message)


def write_png(path, rgb=(128, 128, 128), size=8):
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw))
                + chunk(b"IEND", b""))


def load_module_copy(tmp):
    os.makedirs(os.path.join(tmp, "unreal"))
    os.makedirs(os.path.join(tmp, "dcc_mejoras", "core"))
    shutil.copyfile(os.path.join(_UNREAL_DIR, "texture_autoloader_unreal.py"),
                    os.path.join(tmp, "unreal", "texture_autoloader_unreal.py"))
    shutil.copyfile(os.path.join(_REPO, "dcc_mejoras", "core", "texture_autoloader_core.py"),
                    os.path.join(tmp, "dcc_mejoras", "core", "texture_autoloader_core.py"))
    for name in ("texture_autoloader_unreal", "texture_autoloader_core"):
        sys.modules.pop(name, None)
    sys.path.insert(0, os.path.join(tmp, "unreal"))
    import texture_autoloader_unreal as tal
    return tal


def make_textures(folder):
    files = {
        "Hero_Body_BaseColor.png": (200, 80, 60), "Hero_Body_Normal.png": (128, 128, 255),
        "Hero_Body_Roughness.png": (150, 150, 150), "Hero_Body_Curvature.png": (90, 90, 90),
        "Hero_Head_BaseColor.png": (220, 180, 160), "Hero_Head_Opacity.png": (255, 255, 255),
        "Villain_Body_BaseColor.png": (40, 40, 40),
        "Crate_BaseColor.png": (160, 110, 60), "Crate_Metallic.png": (0, 0, 0),
        "Crate_AO.png": (230, 230, 230), "Crate_Height.png": (128, 128, 128),
        "Wall_BaseColor.1001.png": (180, 180, 180), "Wall_BaseColor.1002.png": (170, 170, 170),
        "Wall_Roughness.png": (200, 200, 200),
    }
    for name, rgb in files.items():
        write_png(os.path.join(folder, name), rgb)


def make_mesh(name, slot_names):
    path = f"{ROOT}/Meshes/{name}"
    mesh = unreal.EditorAssetLibrary.duplicate_asset("/Engine/BasicShapes/Cube", path)
    if slot_names:
        slots = []
        for slot_name in slot_names:
            slot = unreal.StaticMaterial()
            slot.set_editor_property("material_slot_name", slot_name)
            slots.append(slot)
        mesh.set_editor_property("static_materials", slots)
    unreal.EditorAssetLibrary.save_loaded_asset(mesh, only_if_is_dirty=False)
    return mesh


def load(path):
    return unreal.EditorAssetLibrary.load_asset(path) \
        if unreal.EditorAssetLibrary.does_asset_exist(path) else None


def slot_material(mesh, index):
    material = mesh.get_editor_property("static_materials")[index].get_editor_property(
        "material_interface")
    return material.get_name() if material else None


def clear_test_folder():
    """Delete what a previous run left, users before what they use: force-
    deleting a texture that a Master Material still references makes Unreal
    recompile that material with a NULL texture ("Failed to compile
    Material ... Found NULL") right before deleting it — harmless, but it
    looks like the tool's fault in the log."""
    lib = unreal.EditorAssetLibrary
    if not lib.does_directory_exist(ROOT):
        return
    assets = [lib.load_asset(p) for p in lib.list_assets(ROOT, recursive=True)]
    order = (unreal.StaticMesh, unreal.MaterialInstanceConstant, unreal.Material)
    for cls in order:
        for asset in assets:
            if isinstance(asset, cls):
                lib.delete_loaded_asset(asset)
    lib.delete_directory(ROOT)


def run(failures):
    # With <repo>/unreal in Project Settings › Python › Additional Paths, the
    # editor ran init_unreal.py at startup, which imported the module and
    # added the menu entries (TAL_EXPECT_INIT=1 turns this check on).
    if os.environ.get("TAL_EXPECT_INIT") == "1":
        started = sys.modules.get("texture_autoloader_unreal")
        check(started is not None and os.path.dirname(os.path.abspath(started.__file__))
              == os.path.abspath(_UNREAL_DIR),
              "init_unreal.py ran at editor startup (module imported from the repo)", failures)
    clear_test_folder()

    tmp = tempfile.mkdtemp(prefix="tal_unreal_")
    tex_dir = os.path.join(tmp, "textures")
    os.makedirs(tex_dir)
    make_textures(tex_dir)
    tal = load_module_copy(tmp)
    out(f"Unreal {unreal.SystemLibrary.get_engine_version()} — testing {tal.__file__}")

    crate = make_mesh("SM_Crate", None)  # keeps the cube's own (generic) slot
    hero = make_mesh("SM_Hero", ["Body", "Head"])
    wall = make_mesh("SM_Wall", ["Wall_MAT"])
    out(f"SM_Crate slot name: {tal.mesh_slots(crate)}")

    config = tal.merge_unreal_section(dict(tal.UNREAL_DEFAULT_CONFIG, unreal={
        "master_material": f"{ROOT}/M_Master",
        "master_material_masked": f"{ROOT}/M_Master_Masked",
        "texture_folder": f"{ROOT}/Textures",
    }))
    matches, report = tal.process_folder([crate, hero, wall], tex_dir, config=config, language="en")
    out("")
    for line in report.splitlines():
        out("  | " + line)
    out("")

    # ── Matching per Material Slot ──────────────────────────────
    by_key = {m["obj"]: m["tex_base"] for m in matches}
    check(by_key.get("SM_Hero · Body") == "Hero_Body",
          f"slot Body -> Hero_Body, not Villain_Body (got {by_key.get('SM_Hero · Body')})", failures)
    check(by_key.get("SM_Hero · Head") == "Hero_Head", "slot Head -> Hero_Head", failures)
    crate_key = next((k for k in by_key if k.startswith("SM_Crate")), None)
    check(crate_key is not None and by_key[crate_key] == "Crate",
          f"generic slot falls back to the mesh name ({crate_key} -> {by_key.get(crate_key)})",
          failures)

    # ── Master Materials ────────────────────────────────────────
    mel = unreal.MaterialEditingLibrary
    master, masked = load(f"{ROOT}/M_Master"), load(f"{ROOT}/M_Master_Masked")
    check(master is not None and masked is not None, "both Master Materials were generated", failures)
    if master and masked:
        params = sorted(str(p) for p in mel.get_texture_parameter_names(master))
        check(params == ["AmbientOcclusion", "BaseColor", "Emissive", "Metallic", "Normal",
                         "Roughness"], f"master exposes the texture parameters ({params})", failures)
        masked_params = [str(p) for p in mel.get_texture_parameter_names(masked)]
        check("Opacity" in masked_params, "masked master adds an Opacity parameter", failures)
        check(masked.get_editor_property("blend_mode") == unreal.BlendMode.BLEND_MASKED,
              "masked master uses the Masked blend mode", failures)

    # ── Imported textures ───────────────────────────────────────
    texture_checks = (
        ("Hero_Body/T_Hero_Body_BaseColor", True, "TC_DEFAULT"),
        ("Hero_Body/T_Hero_Body_Normal", False, "TC_NORMALMAP"),
        ("Hero_Body/T_Hero_Body_Roughness", False, "TC_MASKS"),
        ("Crate/T_Crate_Metallic", False, "TC_MASKS"),
    )
    for rel, srgb, compression in texture_checks:
        texture = load(f"{ROOT}/Textures/{rel}")
        check(texture is not None, f"imported {rel}", failures)
        if texture:
            got_srgb = texture.get_editor_property("srgb")
            got_comp = texture.get_editor_property("compression_settings")
            check(got_srgb == srgb and got_comp == getattr(unreal.TextureCompressionSettings,
                                                           compression),
                  f"...sRGB {got_srgb}, {got_comp}", failures)
    check(load(f"{ROOT}/Textures/Hero_Body/T_Hero_Body_Curvature") is None,
          "the unknown map type (Curvature) is not imported", failures)

    # ── Material Instances + slot assignment ────────────────────
    mi_body = load(f"{ROOT}/Meshes/MI_Hero_Body")
    mi_head = load(f"{ROOT}/Meshes/MI_Hero_Head")
    check(mi_body is not None and mi_head is not None,
          "MI_Hero_Body and MI_Hero_Head were created next to the mesh", failures)
    if mi_body and mi_head and master and masked:
        check(mi_body.get_editor_property("parent") == master, "MI_Hero_Body's parent is the master",
              failures)
        check(mi_head.get_editor_property("parent") == masked,
              "MI_Hero_Head (has opacity) uses the masked master", failures)
        bound = mel.get_material_instance_texture_parameter_value(mi_body, "BaseColor")
        check(bound is not None and bound.get_name() == "T_Hero_Body_BaseColor",
              f"BaseColor parameter bound to T_Hero_Body_BaseColor ({bound.get_name() if bound else None})",
              failures)
        normal = mel.get_material_instance_texture_parameter_value(mi_body, "Normal")
        check(normal is not None and normal.get_name() == "T_Hero_Body_Normal",
              "Normal parameter bound to T_Hero_Body_Normal", failures)
    check([slot_material(hero, 0), slot_material(hero, 1)] == ["MI_Hero_Body", "MI_Hero_Head"],
          f"SM_Hero slots get their own MI ({[slot_material(hero, 0), slot_material(hero, 1)]})",
          failures)
    check(slot_material(crate, 0) == "MI_Crate", f"SM_Crate gets MI_Crate ({slot_material(crate, 0)})",
          failures)
    check(slot_material(wall, 0) == "MI_Wall", "SM_Wall gets MI_Wall", failures)

    # ── Report ──────────────────────────────────────────────────
    for expected in ("✔ Hero_Body_BaseColor.png → baseColor",
                     "✔ Hero_Head_Opacity.png → opacity",
                     "✘ no match: Hero_Body_Curvature.png",
                     "✘ Wall_BaseColor.<UDIM>.png → baseColor: UDIM isn't supported here yet",
                     "✔ Wall_Roughness.png → roughness",
                     "– Crate_Height.png → displacement: not wired, displacement is opt-in",
                     "Texture sets with no object: Villain_Body (1)",
                     "4/4 object(s) applied"):
        check(expected in report, f"report says: {expected}", failures)

    # ── Running again updates in place ──────────────────────────
    before = sorted(unreal.EditorAssetLibrary.list_assets(ROOT, recursive=True))
    _matches, report2 = tal.process_folder([crate, hero, wall], tex_dir, config=config)
    after = sorted(unreal.EditorAssetLibrary.list_assets(ROOT, recursive=True))
    check(before == after, f"a second run reuses every asset ({len(before)} -> {len(after)})", failures)
    check("4/4 object(s) applied" in report2, "...and applies cleanly again", failures)

    # ── Settings dialog + the flow after it (as the menu entry runs it) ──
    cls = tal._settings_class()
    check(tal._settings_class() is cls, "the settings uclass is defined once", failures)
    state = {"last_folder": tex_dir, "last_threshold": 0.7, "last_naming_preset": "default"}
    check(tal.ask_settings(3, config, state) is None,
          "the settings dialog builds, and counts as cancelled when unattended", failures)

    values = {"folder": tex_dir, "recursive": False, "match_mode": "material_id",
              "threshold": 0.6, "naming_preset": "default", "language": "es"}
    shown, asked = [], []
    report3 = tal.run_with_settings([crate, hero, wall], values, config, {},
                                    confirm=lambda text: asked.append(text) or True,
                                    show=shown.append)
    check(bool(asked) and "VISTA PREVIA" in asked[0] and "SM_Hero · Body  →  Hero_Body" in asked[0],
          "run_with_settings asks to confirm a preview (in Spanish)", failures)
    check(report3 is not None and shown == [report3] and "✘ sin match: Hero_Body_Curvature.png"
          in report3, "...then applies and shows the report", failures)
    saved_state = tal.core.load_state(tal._app_dir())
    check(saved_state.get("last_folder") == tex_dir and saved_state.get("language") == "es",
          "...and remembers the choices for next time", failures)
    declined = tal.run_with_settings([hero], values, config, {}, confirm=lambda text: False,
                                     show=shown.append)
    check(declined is None, "declining the preview applies nothing", failures)

    # ── Menu entries (need the editor's UI; skipped as a commandlet) ──
    if unreal.SystemLibrary.is_unattended() and not os.environ.get("TAL_QUIT_EDITOR"):
        out("  skip  menu entries (commandlet: no editor menus)")
    else:
        tal.register_menus()
        menus = unreal.ToolMenus.get()
        for menu_name in ("ContentBrowser.AssetContextMenu", "LevelEditor.MainMenu.Tools"):
            menu = menus.find_menu(menu_name)
            check(menu is not None, f"{menu_name} exists", failures)

    tal_logs = [h for name, logger in __import__("logging").Logger.manager.loggerDict.items()
                if name.startswith("TextureAutoloader.") and hasattr(logger, "handlers")
                for h in logger.handlers]
    for handler in tal_logs:
        handler.close()
    shutil.rmtree(tmp, ignore_errors=True)


def main():
    failures = []
    try:
        run(failures)
        result = "PASSED" if not failures else f"FAILED ({len(failures)})"
    except Exception:
        out(traceback.format_exc())
        result = "ERROR"
    out(f"TAL_UNREAL_TEST: {result}")
    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(_lines) + "\n")
    # Running in the full editor (-ExecutePythonScript=...) instead of as a
    # commandlet: TAL_QUIT_EDITOR=1 closes it when done.
    if os.environ.get("TAL_QUIT_EDITOR") == "1":
        unreal.SystemLibrary.quit_editor()


main()
