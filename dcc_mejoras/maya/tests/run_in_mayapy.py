"""
Integration test for the Maya front-end, run with a real Maya (mayapy,
headless) and the Arnold plugin — no stubs:

    "C:/Program Files/Autodesk/Maya2027/bin/mayapy.exe" dcc_mejoras/maya/tests/run_in_mayapy.py

The pytest suite next to this file replaces maya.cmds with a stub, which
is great for the matching logic but can't tell whether the shading network
really gets built. This script builds it in a real Maya scene and inspects
the connections.

Everything happens in a temporary folder: the Maya module and the core are
copied there first (same layout as the repo), so the config / state / log
files the tool writes "next to itself" never touch the repo, and the test
textures are small PNGs generated on the fly.
"""
import os
import shutil
import struct
import sys
import tempfile
import traceback
import zlib

_HERE = os.path.dirname(os.path.abspath(__file__))
_MAYA_DIR = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_MAYA_DIR)  # dcc_mejoras/


def write_png(path, rgb=(128, 128, 128), size=8):
    """Minimal valid RGB PNG, no dependencies."""
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


def load_module_copy(tmp):
    for sub in ("core", "maya"):
        os.makedirs(os.path.join(tmp, sub))
    shutil.copyfile(os.path.join(_ROOT, "core", "texture_autoloader_core.py"),
                    os.path.join(tmp, "core", "texture_autoloader_core.py"))
    shutil.copyfile(os.path.join(_MAYA_DIR, "texture_autoloader_maya.py"),
                    os.path.join(tmp, "maya", "texture_autoloader_maya.py"))
    sys.modules.pop("texture_autoloader_core", None)
    sys.path.insert(0, os.path.join(tmp, "maya"))
    import texture_autoloader_maya as ta
    return ta


def make_textures(folder):
    for map_name in ("BaseColor", "Normal"):
        for tile in (1001, 1002):
            write_png(os.path.join(folder, f"Crate2048_{map_name}.{tile}.png"))
    for map_name in ("BaseColor", "Roughness", "Metallic", "Normal", "AO", "Height", "Curvature"):
        write_png(os.path.join(folder, f"Rock_{map_name}.png"))


def source_node(cmds, plug):
    src = cmds.listConnections(plug, source=True, destination=False, plugs=False) or []
    return src[0] if src else None


def check(condition, message, failures):
    print(("  ok    " if condition else "  FAIL  ") + message)
    if not condition:
        failures.append(message)


_APP = None  # module-level: if Python frees the QApplication while Maya runs, Maya crashes


def run():
    global _APP
    # The dialog smoke test needs a GUI QApplication, and it has to exist
    # BEFORE maya.standalone starts: otherwise Maya creates a plain
    # QCoreApplication and building any widget aborts the process.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6 import QtWidgets
    except ImportError:
        from PySide2 import QtWidgets
    _APP = app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    import maya.standalone
    maya.standalone.initialize(name="python")
    import maya.cmds as cmds

    cmds.loadPlugin("mtoa", quiet=True)
    print(f"Maya {cmds.about(version=True)} — mtoa loaded: "
          f"{cmds.pluginInfo('mtoa', query=True, loaded=True)}")

    tmp = tempfile.mkdtemp(prefix="tal_maya_")
    try:
        return _run_checks(cmds, app, tmp)
    finally:
        _close_tool_logs()  # an open .log file blocks deleting its folder on Windows
        shutil.rmtree(tmp, ignore_errors=True)


def _close_tool_logs():
    import logging
    for name, logger in list(logging.Logger.manager.loggerDict.items()):
        if name.startswith("TextureAutoloader.") and isinstance(logger, logging.Logger):
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)


def _run_checks(cmds, app, tmp):
    failures = []
    tex_dir = os.path.join(tmp, "textures")
    os.makedirs(tex_dir)
    make_textures(tex_dir)
    ta = load_module_copy(tmp)
    print(f"testing {ta.__file__}")

    crate = cmds.polyCube(name="SM_Crate2048")[0]
    rock = cmds.polyCube(name="SM_Rock")[0]

    config = ta.core.load_config(ta._app_dir(), warn_fn=ta._warn)
    tex_map = ta.scan_folder(tex_dir, config)
    matches = ta.match_objects_to_textures([crate, rock], tex_map, config)
    ta.apply_auto_textures(matches, config)

    # ── UDIM set ────────────────────────────────────────────────
    shader = ta._find_autoloader_shader(crate)
    check(shader is not None and cmds.nodeType(shader) == "aiStandardSurface",
          f"SM_Crate2048 got an aiStandardSurface ({shader})", failures)
    if shader:
        file_node = source_node(cmds, f"{shader}.baseColor")
        check(file_node is not None and cmds.nodeType(file_node) == "file",
              "baseColor is fed by a file node", failures)
        if file_node:
            check(cmds.getAttr(f"{file_node}.uvTilingMode") == 3,
                  "base color file node uses UDIM tiling (uvTilingMode 3)", failures)
            pattern = cmds.getAttr(f"{file_node}.computedFileTextureNamePattern") or ""
            check("<UDIM>" in pattern,
                  f"Maya resolves the UDIM pattern ({os.path.basename(pattern)})", failures)
        bump = source_node(cmds, f"{shader}.normalCamera")
        check(bump is not None and cmds.nodeType(bump) == "bump2d",
              "normalCamera is fed by a bump2d (tangent-space normal)", failures)

    # ── Plain set: roughness / metallic / AO / displacement ─────
    shader = ta._find_autoloader_shader(rock)
    check(shader is not None, f"SM_Rock got a material ({shader})", failures)
    if shader:
        for attr in ("specularRoughness", "metalness"):
            src = source_node(cmds, f"{shader}.{attr}")
            check(src is not None and cmds.nodeType(src) == "file", f"{attr} is wired", failures)
            if src:
                check(cmds.getAttr(f"{src}.colorSpace") == "Raw",
                      f"...with a Raw color space ({cmds.getAttr(src + '.colorSpace')})", failures)
        mult = source_node(cmds, f"{shader}.baseColor")
        check(mult is not None and cmds.nodeType(mult) == "multiplyDivide",
              "baseColor comes from the AO multiply", failures)
        sg = (cmds.listConnections(f"{shader}.outColor", type="shadingEngine") or [None])[0]
        disp = cmds.listConnections(f"{sg}.displacementShader") if sg else None
        check(not disp, "displacement is NOT wired by default (opt-in)", failures)
        wired = [os.path.basename(cmds.getAttr(f"{n}.fileTextureName"))
                 for n in (cmds.listHistory(shader) or []) if cmds.nodeType(n) == "file"]
        check("Rock_Curvature.png" not in wired, "the unknown map type (Curvature) is not wired", failures)

    # ── ✔/✘ report ──────────────────────────────────────────────
    report = ta.core.build_report(matches, "en", tex_map=tex_map)
    for expected in ("✔ Crate2048_BaseColor.<UDIM>.png → baseColor",
                     "✔ Rock_Metallic.png → metallic",
                     "✔ Rock_AO.png → ao",
                     "– Rock_Height.png → displacement: not wired, displacement is opt-in",
                     "✘ no match: Rock_Curvature.png",
                     "2/2 object(s) applied"):
        check(expected in report, f"report says: {expected}", failures)

    # ── Naming preset with short suffixes (_BC / _N / _R) ───────
    short_dir = os.path.join(tmp, "short")
    os.makedirs(short_dir)
    for name in ("Hero_BC.png", "Hero_N.png", "Hero_R.png"):
        write_png(os.path.join(short_dir, name))
    hero = cmds.polyCube(name="SM_Hero")[0]
    short_config = ta.core.apply_naming_preset(config, "short_suffixes")
    hero_matches = ta.match_objects_to_textures(
        [hero], ta.scan_folder(short_dir, short_config), short_config)
    ta.apply_auto_textures(hero_matches, short_config)
    shader = ta._find_autoloader_shader(hero)
    check(shader is not None, f"short_suffixes preset: SM_Hero got a material ({shader})", failures)
    if shader:
        for attr, expected in (("baseColor", "Hero_BC.png"), ("specularRoughness", "Hero_R.png")):
            src = source_node(cmds, f"{shader}.{attr}")
            got = os.path.basename(cmds.getAttr(f"{src}.fileTextureName")) if src else None
            check(got == expected, f"...{expected} feeds {attr} (got {got})", failures)
        bump = source_node(cmds, f"{shader}.normalCamera")
        check(bump is not None and cmds.nodeType(bump) == "bump2d",
              "...Hero_N.png goes through a bump2d", failures)

    # ── Render engines ──────────────────────────────────────────
    check(ta.engine_plugin_loaded("arnold"), "Arnold counts as loaded", failures)
    if not ta.engine_plugin_loaded("redshift"):
        try:
            ta.process_textures(None, rock, mat_basename="Rock", config=config,
                                channel_files={"baseColor": os.path.join(tex_dir, "Rock_BaseColor.png")},
                                engine="redshift")
            check(False, "Redshift without its plugin raises a clear error", failures)
        except RuntimeError as e:
            check("redshift4maya" in str(e), f"Redshift without its plugin raises: {e}", failures)

    # Opt-in displacement, for real: luminance into a displacementShader on the SG.
    cliff = cmds.polyCube(name="SM_Cliff")[0]
    write_png(os.path.join(tex_dir, "Cliff_BaseColor.png"))
    write_png(os.path.join(tex_dir, "Cliff_Height.png"))
    disp_config = dict(config, enable_displacement_wiring=True)
    cliff_matches = ta.match_objects_to_textures([cliff], ta.scan_folder(tex_dir, disp_config),
                                                 disp_config)
    ta.apply_auto_textures(cliff_matches, disp_config, engine="arnold")
    shader = ta._find_autoloader_shader(cliff)
    sg = (cmds.listConnections(f"{shader}.outColor", type="shadingEngine") or [None])[0]
    disp = source_node(cmds, f"{sg}.displacementShader") if sg else None
    check(disp is not None and cmds.nodeType(disp) == "displacementShader",
          "with enable_displacement_wiring, a displacementShader feeds the shading group", failures)
    if disp:
        height_file = source_node(cmds, f"{disp}.displacement")
        check(height_file is not None and cmds.getAttr(f"{height_file}.alphaIsLuminance"),
              "...reading the height map's luminance (alphaIsLuminance)", failures)

    # ── Qt dialog smoke test (offscreen) ────────────────────────
    # Builds the real dialog and drives a few handlers: catches typos and
    # missing widgets in UI code that no other test executes.
    dlg = ta.TextureAutoloaderDialog()
    presets = [dlg.combo_naming_preset.itemData(i) for i in range(dlg.combo_naming_preset.count())]
    check(presets[:1] == ["default"] and "short_suffixes" in presets,
          f"dialog lists the naming presets ({presets})", failures)
    dlg._on_toggle_language()
    check(dlg.lbl_naming_preset.text() == "PRESET DE NOMBRES", "dialog switches to Spanish", failures)
    dlg._on_toggle_language()
    dlg._set_folder(short_dir)
    check(sorted(dlg.tex_map) == ["Hero_BC", "Hero_N", "Hero_R"],
          f"default preset doesn't know _BC/_N/_R (sets: {sorted(dlg.tex_map)})", failures)
    dlg._on_naming_preset_activated(dlg.combo_naming_preset.findData("short_suffixes"))
    check(sorted(dlg.tex_map) == ["Hero"],
          f"picking short_suffixes re-scans into one set (sets: {sorted(dlg.tex_map)})", failures)
    check(ta.core.load_state(ta._app_dir()).get("last_naming_preset") == "short_suffixes",
          "the chosen preset is remembered in the state file", failures)
    engines = [dlg.combo_render_engine.itemData(i) for i in range(dlg.combo_render_engine.count())]
    check(engines == ["arnold", "redshift", "vray"], f"dialog lists the render engines ({engines})",
          failures)
    dlg._on_render_engine_activated(dlg.combo_render_engine.findData("vray"))
    check(ta.core.load_state(ta._app_dir()).get("last_render_engine") == "vray",
          "the chosen render engine is remembered in the state file", failures)
    dlg.close()
    app.processEvents()

    print()
    if failures:
        print(f"TAL_MAYA_TEST: FAILED ({len(failures)})")
        return 1
    print("TAL_MAYA_TEST: PASSED")
    return 0


def _hard_exit(code):
    """Leave without running Maya's shutdown: with a QApplication alive,
    maya.standalone can hang or crash while unloading (Arnold, Qt) — after
    the result is already printed, but it leaves a "Fatal Error" and a
    recovery .ma in %TEMP% behind. On Windows even os._exit still runs the
    DLL unload code, so terminate the process outright."""
    sys.stdout.flush()
    sys.stderr.flush()
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32")
        # Declared on purpose: with ctypes' default int types the 64-bit
        # process handle gets truncated and TerminateProcess silently fails.
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel32.TerminateProcess(kernel32.GetCurrentProcess(), code)
    os._exit(code)


if __name__ == "__main__":
    try:
        code = run()
    except Exception:
        traceback.print_exc()
        print("TAL_MAYA_TEST: ERROR")
        code = 1
    _hard_exit(code)
