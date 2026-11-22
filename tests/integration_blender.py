"""
Integration test for the Blender build, run inside a real Blender, headless.

    blender -b --factory-startup --python-exit-code 1 --python tests/integration_blender.py
    blender -b --factory-startup --python-exit-code 1 --python tests/integration_blender.py -- --build modular

Checks what only real Blender can answer: that the node graph ends up wired,
which socket each link lands on, that UDIM tiles register as one tiled image,
and which colorspace each texture gets.

`--build standalone` (the default) tests
blender/texture_autoloader_blender_standalone.py, the file the README tells
people to install; `--build modular` tests advanced/blender/texture_autoloader_blender.py.

Everything happens in a temp folder: the addon is loaded from a copy there, so
the config / state / log it writes next to itself never touch the repo.
--python-exit-code 1 makes Blender exit non-zero if a check fails.
"""
import os
import shutil
import struct
import sys
import tempfile
import zlib

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
BUILD = argv[argv.index("--build") + 1] if "--build" in argv else "standalone"

failures = []


def check(condition, message):
    print(("  ok    " if condition else "  FAIL  ") + message)
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


def load_addon(tmp):
    addon_dir = os.path.join(tmp, "blender")
    os.makedirs(addon_dir)
    if BUILD == "standalone":
        src = os.path.join(REPO, "blender", "texture_autoloader_blender_standalone.py")
        name = "texture_autoloader_blender_standalone"
    else:
        src = os.path.join(REPO, "advanced", "blender", "texture_autoloader_blender.py")
        name = "texture_autoloader_blender"
        core_dir = os.path.join(tmp, "core")
        os.makedirs(core_dir)
        shutil.copyfile(os.path.join(REPO, "advanced", "core", "texture_autoloader_core.py"),
                        os.path.join(core_dir, "texture_autoloader_core.py"))
        sys.modules.pop("texture_autoloader_core", None)
    shutil.copyfile(src, os.path.join(addon_dir, name + ".py"))
    sys.path.insert(0, addon_dir)
    addon = __import__(name)
    addon.register()
    return addon


def make_mesh(name):
    data = bpy.data.meshes.new(name + "_mesh")
    data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def select_only(objects):
    """--factory-startup opens with a Cube selected, so select explicitly."""
    for obj in bpy.context.scene.objects:
        obj.select_set(obj in objects)
    bpy.context.view_layer.objects.active = objects[0] if objects else None


def source_of(socket):
    return socket.links[0].from_socket if socket.is_linked else None


def material_of(obj):
    return obj.material_slots[0].material if obj.material_slots else None


def make_textures(folder):
    for map_name, rgb in (("BaseColor", (200, 60, 60)), ("Roughness", (150, 150, 150)),
                          ("Metallic", (10, 10, 10)), ("Normal", (128, 128, 255)),
                          ("AO", (230, 230, 230)), ("Height", (128, 128, 128)),
                          ("Opacity", (255, 255, 255)), ("Curvature", (90, 90, 90))):
        write_png(os.path.join(folder, "Rock_%s.png" % map_name), rgb)
    # UDIM tiles the way Substance and Mari name them, on an asset whose own
    # name contains a 4-digit number (that combination used to break twice).
    for tile in (1001, 1002):
        write_png(os.path.join(folder, "Crate2048_BaseColor.%d.png" % tile))


def run(tmp):
    tex = os.path.join(tmp, "textures")
    os.makedirs(tex)
    make_textures(tex)
    addon = load_addon(tmp)
    print("Blender %s  |  build: %s" % (bpy.app.version_string, BUILD))

    rock, crate = make_mesh("SM_Rock"), make_mesh("SM_Crate2048")
    select_only([rock, crate])
    props = bpy.context.scene.texture_autoloader
    props.folder = tex
    bpy.ops.texture_autoloader.scan_folder()
    bpy.ops.texture_autoloader.smart_match()
    bpy.ops.texture_autoloader.apply_all()

    # ── The standard set ────────────────────────────────────────
    mat = material_of(rock)
    if check(mat is not None, "SM_Rock got a material"):
        nodes = mat.node_tree.nodes
        bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
        images = {os.path.basename(n.image.filepath): n for n in nodes
                  if n.type == "TEX_IMAGE" and n.image}

        for socket in ("Roughness", "Metallic", "Alpha"):
            src = source_of(bsdf.inputs[socket])
            check(src is not None and src.node.type == "TEX_IMAGE", "%s is wired" % socket)
        normal = source_of(bsdf.inputs["Normal"])
        check(normal is not None and normal.node.type == "NORMAL_MAP",
              "Normal goes through a Normal Map node")

        # AO x base color: the Mix node has float, vector and color sockets
        # that all answer to "A"/"B"/"Result", and only the color ones carry
        # a texture correctly
        base_src = source_of(bsdf.inputs["Base Color"])
        mix = base_src.node if base_src else None
        if check(mix is not None and mix.type == "MIX",
                 "Base Color is fed by the AO multiply"):
            check(base_src.type == "RGBA",
                  "...from its color output (socket type %s)" % base_src.type)
            linked = [(s.name, s.type) for s in mix.inputs if s.is_linked]
            check(len(linked) == 2 and all(t == "RGBA" for _n, t in linked),
                  "...with both maps on its color inputs (%s)" % linked)

        base = images.get("Rock_BaseColor.png")
        rough = images.get("Rock_Roughness.png")
        if base and rough:
            check(base.image.colorspace_settings.name == "sRGB",
                  "base color is sRGB (%s)" % base.image.colorspace_settings.name)
            check(rough.image.colorspace_settings.name == "Non-Color",
                  "roughness is Non-Color (%s)" % rough.image.colorspace_settings.name)

        output = mat.node_tree.nodes.get("Material Output")
        disp = source_of(output.inputs["Displacement"]) if output else None
        check(disp is None, "displacement is NOT wired by default (opt-in)")
        check("Rock_Curvature.png" not in images,
              "the unrecognized map (Curvature) is not wired")

    # ── UDIM ────────────────────────────────────────────────────
    mat = material_of(crate)
    tiled = [n.image for n in mat.node_tree.nodes
             if n.type == "TEX_IMAGE" and n.image and n.image.source == "TILED"] if mat else []
    if check(len(tiled) == 1,
             "tiles named Crate2048_BaseColor.1001.png load as one tiled image"):
        numbers = sorted(t.number for t in tiled[0].tiles)
        check(numbers == [1001, 1002],
              "...with tiles 1001 and 1002, not the 2048 in the asset's name (%s)" % numbers)

    # ── Re-matching an object this tool already processed ───────
    select_only([rock])
    props.match_mode = "material_id"
    bpy.ops.texture_autoloader.smart_match()
    got = addon._MATCHES[0]["tex_base"] if addon._MATCHES else None
    check(got == "Rock", "Material ID mode still matches M_Rock_TXA to Rock (%s)" % got)

    # ── The config's color_space is honored, not hardcoded ─────
    import json
    config_path = os.path.join(os.path.dirname(addon.__file__), "texture_autoloader_config.json")
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)
    for mt in config["map_types"]:
        if mt["id"] == "roughness":
            mt["color_space"] = "sRGB"  # deliberately wrong, to prove it is read
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    for image in list(bpy.data.images):
        bpy.data.images.remove(image)
    select_only([rock])
    props.match_mode = "object_name"
    bpy.ops.texture_autoloader.scan_folder()
    bpy.ops.texture_autoloader.smart_match()
    bpy.ops.texture_autoloader.apply_all()
    rough = {os.path.basename(n.image.filepath): n.image
             for n in material_of(rock).node_tree.nodes
             if n.type == "TEX_IMAGE" and n.image}.get("Rock_Roughness.png")
    check(rough is not None and rough.colorspace_settings.name == "sRGB",
          "a color_space set in the config reaches the image (%s)"
          % (rough.colorspace_settings.name if rough else None))


def close_tool_logs():
    """An open .log file blocks deleting its folder on Windows."""
    import logging
    for name, logger in list(logging.Logger.manager.loggerDict.items()):
        if "TextureAutoloader" in name and isinstance(logger, logging.Logger):
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)


tmp_dir = tempfile.mkdtemp(prefix="tal_integration_")
try:
    run(tmp_dir)
except Exception:
    import traceback
    traceback.print_exc()
    failures.append("unhandled exception")
finally:
    close_tool_logs()
    shutil.rmtree(tmp_dir, ignore_errors=True)

print()
if failures:
    print("FAILED (%d): %s" % (len(failures), "; ".join(failures)))
    raise SystemExit(1)
print("PASSED")
