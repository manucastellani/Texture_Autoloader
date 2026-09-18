"""
Integration test for the Blender front-end, run INSIDE a real Blender
(no stubs), headless:

    blender -b --factory-startup --python-exit-code 1 --python dcc_mejoras/blender/tests/run_in_blender.py

Unlike the pytest suites (which never need Blender), this checks what only
real Blender can tell: that the node graph actually ends up wired, that
UDIM tiles register as a tiled image, and which socket each link lands on.

Everything happens in a temporary folder: the addon module and the core
are copied there first (same layout as the repo), so the config / state /
log files the addon writes "next to itself" never touch the repo, and the
test textures are small PNGs generated on the fly.
"""
import os
import shutil
import struct
import sys
import tempfile
import traceback
import zlib

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
_BLENDER_DIR = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_BLENDER_DIR)  # dcc_mejoras/


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


def load_addon_copy(tmp):
    for sub in ("core", "blender"):
        os.makedirs(os.path.join(tmp, sub))
    shutil.copyfile(os.path.join(_ROOT, "core", "texture_autoloader_core.py"),
                    os.path.join(tmp, "core", "texture_autoloader_core.py"))
    shutil.copyfile(os.path.join(_BLENDER_DIR, "texture_autoloader_blender.py"),
                    os.path.join(tmp, "blender", "texture_autoloader_blender.py"))
    sys.modules.pop("texture_autoloader_core", None)
    sys.path.insert(0, os.path.join(tmp, "blender"))
    import texture_autoloader_blender as addon
    addon.register()
    return addon


def make_textures(folder):
    # UDIM set whose asset name contains a 4-digit number on purpose.
    for map_name, rgb in (("BaseColor", (200, 60, 60)), ("Normal", (128, 128, 255))):
        for tile in (1001, 1002):
            write_png(os.path.join(folder, f"Crate2048_{map_name}.{tile}.png"), rgb)
    # Plain (non-UDIM) set, plus a map type the tool doesn't know.
    for map_name in ("BaseColor", "Roughness", "Normal", "AO", "Curvature"):
        write_png(os.path.join(folder, f"Rock_{map_name}.png"))


def make_mesh(name):
    mesh = bpy.data.meshes.new(name + "_mesh")
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def linked_from(socket):
    return [link.from_socket for link in socket.links] if socket.is_linked else []


def check(condition, message, failures):
    print(("  ok    " if condition else "  FAIL  ") + message)
    if not condition:
        failures.append(message)


def run():
    tmp = tempfile.mkdtemp(prefix="tal_blender_")
    try:
        _run_checks(tmp)
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


def _run_checks(tmp):
    failures = []
    tex_dir = os.path.join(tmp, "textures")
    os.makedirs(tex_dir)
    make_textures(tex_dir)
    addon = load_addon_copy(tmp)
    print(f"Blender {bpy.app.version_string} — testing {addon.__file__}")

    crate = make_mesh("SM_Crate2048")
    rock = make_mesh("SM_Rock")
    for obj in bpy.context.scene.objects:  # the factory scene's Cube starts selected
        obj.select_set(obj in (crate, rock))

    props = bpy.context.scene.texture_autoloader
    props.folder = tex_dir
    bpy.ops.texture_autoloader.scan_folder()
    bpy.ops.texture_autoloader.smart_match()
    bpy.ops.texture_autoloader.apply_all()

    # ── UDIM set ────────────────────────────────────────────────
    mat = crate.material_slots[0].material if crate.material_slots else None
    check(mat is not None, "SM_Crate2048 got a material", failures)
    if mat:
        nodes = mat.node_tree.nodes
        bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
        images = [n.image for n in nodes if n.type == "TEX_IMAGE" and n.image]
        tiled = [img for img in images if img.source == "TILED"]
        check(len(tiled) == 2, f"both UDIM maps load as tiled images (got {len(tiled)})", failures)
        for img in tiled:
            numbers = sorted(t.number for t in img.tiles)
            check(numbers == [1001, 1002],
                  f"{os.path.basename(img.filepath)} registers tiles 1001+1002 (got {numbers})",
                  failures)
        base_src = linked_from(bsdf.inputs["Base Color"])
        check(bool(base_src) and base_src[0].node.type == "TEX_IMAGE",
              "Base Color is fed by the base color image", failures)
        normal_src = linked_from(bsdf.inputs["Normal"])
        check(bool(normal_src) and normal_src[0].node.type == "NORMAL_MAP",
              "Normal is fed by a Normal Map node", failures)

    # ── Plain set with AO ───────────────────────────────────────
    mat = rock.material_slots[0].material if rock.material_slots else None
    check(mat is not None, "SM_Rock got a material", failures)
    if mat:
        nodes = mat.node_tree.nodes
        bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
        wired_files = sorted(os.path.basename(n.image.filepath)
                             for n in nodes if n.type == "TEX_IMAGE" and n.image)
        check("Rock_Curvature.png" not in wired_files,
              "the unknown map type (Curvature) is not wired", failures)
        rough_src = linked_from(bsdf.inputs["Roughness"])
        check(bool(rough_src) and rough_src[0].node.type == "TEX_IMAGE",
              "Roughness is wired", failures)
        # AO x BaseColor: the Mix node must feed Base Color from its COLOR
        # output, and both color inputs must be the RGBA ones (the Mix node
        # has float/vector/color sockets that all share the names A/B/Result).
        base_src = linked_from(bsdf.inputs["Base Color"])
        mix = base_src[0].node if base_src else None
        check(mix is not None and mix.type == "MIX", "Base Color comes from the AO multiply", failures)
        if mix is not None:
            check(base_src[0].type == "RGBA",
                  f"...through the Mix node's color output (got a {base_src[0].type} socket)",
                  failures)
            color_inputs = [s for s in mix.inputs if s.type == "RGBA" and s.is_linked]
            check(len(color_inputs) == 2,
                  f"...with base color and AO both on the color inputs (got {len(color_inputs)})",
                  failures)

    # ── ✔/✘ report ──────────────────────────────────────────────
    text = bpy.data.texts.get(addon.REPORT_TEXT_NAME)
    check(text is not None, f"the report is saved as the text block '{addon.REPORT_TEXT_NAME}'",
          failures)
    report = text.as_string() if text else ""
    for expected in ("✔ Crate2048_BaseColor.<UDIM>.png → baseColor",
                     "✔ Rock_Roughness.png → roughness",
                     "✔ Rock_AO.png → ao",
                     "✘ no match: Rock_Curvature.png",
                     "2/2 object(s) applied"):
        check(expected in report, f"report says: {expected}", failures)
    if failures:
        print("\n--- report ---\n" + report + "\n--------------")

    # ── Naming preset with short suffixes (_BC / _N / _R) ───────
    short_dir = os.path.join(tmp, "short")
    os.makedirs(short_dir)
    for name in ("Hero_BC.png", "Hero_N.png", "Hero_R.png"):
        write_png(os.path.join(short_dir, name))
    hero = make_mesh("SM_Hero")
    for obj in bpy.context.scene.objects:
        obj.select_set(obj is hero)
    props.folder = short_dir
    props.naming_preset = "short_suffixes"  # re-scans the folder on its own
    bpy.ops.texture_autoloader.smart_match()
    bpy.ops.texture_autoloader.apply_all()
    mat = hero.material_slots[0].material if hero.material_slots else None
    check(mat is not None, "short_suffixes preset: SM_Hero got a material", failures)
    if mat:
        bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        for socket, expected in (("Base Color", "Hero_BC.png"), ("Roughness", "Hero_R.png")):
            src = linked_from(bsdf.inputs[socket])
            got = os.path.basename(src[0].node.image.filepath) if src else None
            check(got == expected, f"...{expected} feeds {socket} (got {got})", failures)
        normal_src = linked_from(bsdf.inputs["Normal"])
        check(bool(normal_src) and normal_src[0].node.type == "NORMAL_MAP",
              "...Hero_N.png goes through a Normal Map node", failures)

    print()
    if failures:
        print(f"TAL_BLENDER_TEST: FAILED ({len(failures)})")
        raise SystemExit(1)
    print("TAL_BLENDER_TEST: PASSED")


try:
    run()
except SystemExit:
    raise
except Exception:
    traceback.print_exc()
    print("TAL_BLENDER_TEST: ERROR")
    raise SystemExit(1)
