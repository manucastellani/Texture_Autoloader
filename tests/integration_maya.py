"""
Integration test for the Maya build, run inside a real Maya (mayapy), headless.

    "C:/Program Files/Autodesk/Maya2027/bin/mayapy.exe" tests/integration_maya.py
    "C:/Program Files/Autodesk/Maya2027/bin/mayapy.exe" tests/integration_maya.py --build modular

The unit suites under advanced/ replace maya.cmds with a stub, which is right
for the matching logic but cannot tell whether the shading network really gets
built: every bug this file checks for shipped while those suites were green.
So this one builds the network in a real Maya scene, with Arnold loaded, and
inspects the actual connections and attributes.

`--build standalone` (the default) tests maya/texture_autoloader_maya_standalone.py,
the file the README tells people to paste into the Script Editor;
`--build modular` tests advanced/maya/texture_autoloader_maya.py.

Everything happens in a temp folder: the module is loaded from a copy there, so
the config / state / log it writes next to itself never touch the repo or your
Maya preferences. Exits non-zero if any check fails.
"""
import argparse
import os
import shutil
import struct
import sys
import tempfile
import traceback
import zlib

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)

failures = []


def check(condition, message):
    print(("  ok    " if condition else "  FAIL  ") + message)
    sys.stdout.flush()
    if not condition:
        failures.append(message)
    return bool(condition)


def write_png(path, rgb=(128, 128, 128), size=8):
    """Minimal valid RGB PNG, so the test needs no texture files of its own."""
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def load_module(tmp, build):
    maya_dir = os.path.join(tmp, "maya")
    os.makedirs(maya_dir)
    if build == "standalone":
        src = os.path.join(REPO, "maya", "texture_autoloader_maya_standalone.py")
        name = "texture_autoloader_maya_standalone"
    else:
        src = os.path.join(REPO, "advanced", "maya", "texture_autoloader_maya.py")
        name = "texture_autoloader_maya"
        core_dir = os.path.join(tmp, "core")
        os.makedirs(core_dir)
        shutil.copyfile(os.path.join(REPO, "advanced", "core", "texture_autoloader_core.py"),
                        os.path.join(core_dir, "texture_autoloader_core.py"))
        sys.modules.pop("texture_autoloader_core", None)
    shutil.copyfile(src, os.path.join(maya_dir, name + ".py"))
    sys.path.insert(0, maya_dir)
    return __import__(name)


def source_node(cmds, plug):
    sources = cmds.listConnections(plug, source=True, destination=False) or []
    return sources[0] if sources else None


def make_textures(folder):
    for map_name in ("BaseColor", "Roughness", "Metallic", "Normal", "AO", "Height",
                     "Curvature"):
        write_png(os.path.join(folder, "Rock_%s.png" % map_name))
    # UDIM tiles the way Substance and Mari name them, on an asset whose own
    # name contains a 4-digit number (that combination used to break twice).
    for tile in (1001, 1002):
        write_png(os.path.join(folder, "Crate2048_BaseColor.%d.png" % tile))
    write_png(os.path.join(folder, "Cliff_BaseColor.png"))
    write_png(os.path.join(folder, "Cliff_Height.png"))


def apply_to(ta, build, objects, folder, config):
    """Scan + match + apply, through whichever entry points this build has."""
    if build == "standalone":
        tex_map = ta.scan_texture_folder(folder, config["suffix_strip_list"],
                                         set(config["texture_extensions"]))
    else:
        tex_map = ta.scan_folder(folder, config)
    matches = ta.match_objects_to_textures(objects, tex_map, config)
    ta.apply_auto_textures(matches, config)
    return matches


def run(build, tmp):
    import maya.cmds as cmds
    cmds.loadPlugin("mtoa", quiet=True)
    tex = os.path.join(tmp, "textures")
    os.makedirs(tex)
    make_textures(tex)

    ta = load_module(tmp, build)
    print("Maya %s  |  build: %s  |  mtoa loaded: %s"
          % (cmds.about(version=True), build,
             cmds.pluginInfo("mtoa", query=True, loaded=True)))
    print("  config/state/log go to: %s" % ta._app_dir())

    config = (ta.load_config() if build == "standalone"
              else ta.core.load_config(ta._app_dir(), warn_fn=ta._warn))

    rock = cmds.polyCube(name="SM_Rock")[0]
    crate = cmds.polyCube(name="SM_Crate2048")[0]
    apply_to(ta, build, [rock, crate], tex, config)

    # ── The standard set ────────────────────────────────────────
    shader = ta._find_autoloader_shader(rock)
    if check(shader is not None and cmds.nodeType(shader) == "aiStandardSurface",
             "SM_Rock got an aiStandardSurface (%s)" % shader):
        for attr, node_type in (("specularRoughness", "file"), ("metalness", "file"),
                                ("normalCamera", "bump2d")):
            src = source_node(cmds, "%s.%s" % (shader, attr))
            check(src is not None and cmds.nodeType(src) == node_type,
                  "%s is fed by a %s (%s)" % (attr, node_type, src))
        # scalar inputs must read the luminance: a Substance export has no
        # alpha channel, so outAlpha alone is a constant 1.0
        rough = source_node(cmds, "%s.specularRoughness" % shader)
        check(rough is not None and cmds.getAttr("%s.alphaIsLuminance" % rough) is True,
              "...roughness reads the luminance (alphaIsLuminance)")
        mult = source_node(cmds, "%s.baseColor" % shader)
        check(mult is not None and cmds.nodeType(mult) == "multiplyDivide",
              "baseColor comes from the AO multiply (%s)" % mult)
        wired = [os.path.basename(cmds.getAttr("%s.fileTextureName" % n))
                 for n in (cmds.listHistory(shader) or []) if cmds.nodeType(n) == "file"]
        check("Rock_Curvature.png" not in wired,
              "the unrecognized map (Curvature) is not wired")

    # ── UDIM ────────────────────────────────────────────────────
    shader = ta._find_autoloader_shader(crate)
    fn = source_node(cmds, "%s.baseColor" % shader) if shader else None
    pattern = os.path.basename(cmds.getAttr("%s.computedFileTextureNamePattern" % fn) or "") \
        if fn else ""
    tiling = cmds.getAttr("%s.uvTilingMode" % fn) if fn else -1
    check(fn is not None and tiling == 3 and "<UDIM>" in pattern,
          "tiles named Crate2048_BaseColor.1001.png become one <UDIM> node "
          "(uvTilingMode=%s, %s)" % (tiling, pattern))

    # ── Displacement, opted in ──────────────────────────────────
    cliff = cmds.polyCube(name="SM_Cliff")[0]
    disp_config = dict(config, enable_displacement_wiring=True)
    apply_to(ta, build, [cliff], tex, disp_config)
    shader = ta._find_autoloader_shader(cliff)
    sg = (cmds.listConnections("%s.outColor" % shader, type="shadingEngine") or [None])[0] \
        if shader else None
    disp = source_node(cmds, "%s.displacementShader" % sg) if sg else None
    if check(disp is not None and cmds.nodeType(disp) == "displacementShader",
             "enable_displacement_wiring feeds a displacementShader to the SG (%s)" % disp):
        height = source_node(cmds, "%s.displacement" % disp)
        check(height is not None and cmds.getAttr("%s.alphaIsLuminance" % height) is True,
              "...reading the height map's luminance, not a constant 1.0")

    # ── A map type the tool cannot wire ─────────────────────────
    gem = cmds.polyCube(name="SM_Gem")[0]
    write_png(os.path.join(tex, "Gem_BaseColor.png"))
    write_png(os.path.join(tex, "Gem_Specular.png"))
    custom = dict(config)
    custom["map_types"] = list(config["map_types"]) + [
        {"id": "specular", "match": ["_specular"], "color_space": "Raw", "raw": True}]
    custom["suffix_strip_list"] = list(config["suffix_strip_list"]) + ["specular"]
    before = set(cmds.ls(type="file") or [])
    apply_to(ta, build, [gem], tex, custom)
    new_files = [n for n in (cmds.ls(type="file") or []) if n not in before]
    dangling = [n for n in new_files
                if not (cmds.listConnections(n + ".outColor", destination=True,
                                             source=False) or [])
                and not (cmds.listConnections(n + ".outAlpha", destination=True,
                                              source=False) or [])]
    check(not dangling,
          "a map type with no wiring rule leaves no unconnected node (%s)" % (dangling or "none"))

    # ── The dialog ──────────────────────────────────────────────
    dialog = ta.TextureAutoloaderDialog
    check(dialog.MINIMUM_HEIGHT <= 1032,
          "the dialog's minimum height fits a 1080p screen (%s)" % dialog.MINIMUM_HEIGHT)
    try:
        dlg = dialog()
        built = dlg.windowTitle() != ""
        dlg.close()
        check(built, "the Qt dialog builds")
    except Exception as e:
        check(False, "the Qt dialog builds: %s" % e)


def close_tool_logs():
    """An open .log file blocks deleting its folder on Windows."""
    import logging
    for name, logger in list(logging.Logger.manager.loggerDict.items()):
        if "TextureAutoloader" in name and isinstance(logger, logging.Logger):
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", choices=("standalone", "modular"), default="standalone")
    args = parser.parse_args()

    # A GUI QApplication has to exist BEFORE maya.standalone starts, or Maya
    # creates a plain QCoreApplication and building any widget aborts the
    # process. Kept in a module-level name so Python can't free it early.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    global _app
    try:
        from PySide6 import QtWidgets
    except ImportError:
        from PySide2 import QtWidgets
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    import maya.standalone
    maya.standalone.initialize(name="python")

    tmp = tempfile.mkdtemp(prefix="tal_integration_")
    code = 0
    try:
        run(args.build, tmp)
    except Exception:
        traceback.print_exc()
        failures.append("unhandled exception")
    finally:
        close_tool_logs()
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print("FAILED (%d): %s" % (len(failures), "; ".join(failures)))
        code = 1
    else:
        print("PASSED")
    sys.stdout.flush()
    # Leave without Maya's shutdown: with a live QApplication it can crash
    # while unloading Arnold/Qt, after the result is already printed, and it
    # leaves a recovery .ma behind. On Windows os._exit still runs the DLL
    # unload path, so terminate the process outright.
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel32.TerminateProcess(kernel32.GetCurrentProcess(), code)
    os._exit(code)


_app = None
main()
