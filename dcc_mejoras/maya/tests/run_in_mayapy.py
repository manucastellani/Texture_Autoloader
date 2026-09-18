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


def run():
    import maya.standalone
    maya.standalone.initialize(name="python")
    import maya.cmds as cmds

    failures = []
    cmds.loadPlugin("mtoa", quiet=True)
    print(f"Maya {cmds.about(version=True)} — mtoa loaded: "
          f"{cmds.pluginInfo('mtoa', query=True, loaded=True)}")

    tmp = tempfile.mkdtemp(prefix="tal_maya_")
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

    print()
    if failures:
        print(f"TAL_MAYA_TEST: FAILED ({len(failures)})")
        return 1
    print("TAL_MAYA_TEST: PASSED")
    return 0


if __name__ == "__main__":
    try:
        code = run()
    except Exception:
        traceback.print_exc()
        print("TAL_MAYA_TEST: ERROR")
        code = 1
    # os._exit: maya.standalone can hang on interpreter shutdown.
    sys.stdout.flush()
    os._exit(code)
