"""
Texture Autoloader — Blender front-end
=======================================
Author: Manuel Castellani

Blender addon port of Texture Autoloader. Same matching/naming logic as
the Maya version (shared via ../core/texture_autoloader_core.py — see
that file's docstring for why the core is split out), adapted to
Blender's node-based Principled BSDF shading and its own UI conventions
(a Sidebar panel + operators, instead of a floating Qt dialog).

Honest scope note: this is a genuine, from-scratch port, not a re-skin.
Blender's UI system doesn't have an equivalent of Qt's multi-select tree
widget with inline checkboxes, so the "preview" here is a flat list of
rows with a per-row remove button and per-channel checkboxes — same
underlying capability (review matches, disable a channel, remove an
object from the batch before applying), different, native-feeling
layout. If you're coming from the Maya version, don't expect pixel
parity — expect the same pipeline value.

Install: Edit > Preferences > Add-ons > Install..., pick this .py file.
The addon needs `core/texture_autoloader_core.py` to be importable — it
adds the sibling `core/` folder to sys.path itself (see the bootstrap
right below the imports), so keep this repo's folder structure intact
(don't move this file out of `blender/` on its own). This is the
modular build meant for keeping the matching logic shared and tested
alongside the Maya version — if you just want to install a single file
with no folder dependency, use
`blender/texture_autoloader_blender_standalone.py` in the parent
TextureAutoloader folder instead.

Once enabled, the panel lives in the 3D Viewport's Sidebar (press N),
under the "Texture Autoloader" tab.
"""

bl_info = {
    "name": "Texture Autoloader",
    "author": "Manuel Castellani",
    "version": (5, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Texture Autoloader",
    "description": "Scans a folder, matches meshes to Substance texture sets by name, "
                    "and wires a Principled BSDF per object.",
    "category": "Material",
}

import os
import re
import sys
from typing import Optional, List, Dict, Tuple, Any

import bpy
from bpy.props import (
    StringProperty, BoolProperty, FloatProperty, EnumProperty, IntProperty,
)
from bpy.types import Operator, Panel, PropertyGroup, Menu


# ══════════════════════════════════════════════════════════════
#  Bootstrap: hace importable el core compartido (carpeta hermana
#  "core/") sin depender de que el usuario instale nada extra.
# ══════════════════════════════════════════════════════════════

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_CORE_DIR = os.path.join(os.path.dirname(_THIS_DIR), "core")
if _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)

import texture_autoloader_core as core  # noqa: E402


def _app_dir() -> str:
    try:
        base = os.path.dirname(os.path.abspath(__file__))
        os.makedirs(base, exist_ok=True)
        return base
    except Exception:
        return os.path.expanduser("~")


def _warn(message: str) -> None:
    """Reporta el warning en la consola de Python de Blender Y lo deja en
    texture_autoloader.log. No usa self.report({'WARNING'}, ...) porque
    esta función se llama también desde el core (donde no hay un
    `self` de operator disponible) — los operators que sí tienen acceso
    a self.report lo llaman aparte, ver _report_and_warn más abajo."""
    print(f"[Texture Autoloader] WARNING: {message}")
    try:
        core.get_logger(_app_dir()).warning(message)
    except Exception:
        pass


def _log_print(message: str) -> None:
    print(message)
    try:
        core.get_logger(_app_dir()).info(message)
    except Exception:
        pass


if not core.HAS_RAPIDFUZZ:
    _warn(
        "[TextureAutoloader] rapidfuzz is not installed in Blender's Python — "
        "using the internal difflib fallback for fuzzy matching. This is not "
        "an error, it only lowers precision a bit on very different-looking names.")


# ══════════════════════════════════════════════════════════════
#  Estado de sesión (no persistido en el .blend a propósito — un
#  escaneo de carpeta es información de "sesión de trabajo", no algo
#  que tenga sentido guardar dentro del archivo de la escena. Se
#  guarda sí en texture_autoloader_state.json entre sesiones de Blender,
#  igual que en la versión de Maya, para la carpeta/threshold/idioma).
# ══════════════════════════════════════════════════════════════

_TEX_MAP: Dict[str, List[str]] = {}
_MATCHES: List[Dict[str, Any]] = []
_LAST_REPORT: str = ""

REPORT_TEXT_NAME = "TextureAutoloader_Report"


def _publish_report(report: str) -> str:
    """Deja el reporte ✔/✘ donde se pueda leer después de cerrar el popup:
    en la consola, en texture_autoloader.log y en un bloque de texto del
    .blend (Text Editor). Devuelve el nombre de ese bloque de texto."""
    global _LAST_REPORT
    _LAST_REPORT = report
    print(report)
    try:
        core.get_logger(_app_dir()).info("\n" + report)
    except Exception:
        pass
    text = bpy.data.texts.get(REPORT_TEXT_NAME) or bpy.data.texts.new(REPORT_TEXT_NAME)
    text.clear()
    text.write(report)
    return text.name


def _config() -> Dict[str, Any]:
    return core.load_config(_app_dir(), warn_fn=_warn)


def _t(key: str, **kwargs) -> str:
    scene = bpy.context.scene
    language = getattr(scene.texture_autoloader, "language", core.DEFAULT_LANGUAGE) \
        if hasattr(scene, "texture_autoloader") else core.DEFAULT_LANGUAGE
    return core.tr(language, key, **kwargs)


# ══════════════════════════════════════════════════════════════
#  BLENDER — WIRING (Principled BSDF)
# ══════════════════════════════════════════════════════════════

_MAT_NAME_RE = re.compile(r'^M_.+_TXA\d*$')


def _find_autoloader_material(obj: "bpy.types.Object") -> Optional["bpy.types.Material"]:
    """Análogo a la versión Maya: reconoce materiales generados por esta
    herramienta (patrón "M_..._TXA") ya asignados al objeto."""
    for slot in obj.material_slots:
        if slot.material and _MAT_NAME_RE.match(slot.material.name):
            return slot.material
    return None


def has_autoloader_material(obj: "bpy.types.Object") -> bool:
    return _find_autoloader_material(obj) is not None


def _get_assigned_material_name(obj: "bpy.types.Object") -> Optional[str]:
    """Devuelve el nombre del primer material 'real' asignado al objeto
    (no None, no un placeholder vacío). Blender no tiene el concepto de
    "material default" que sí tiene Maya (lambert1) — un slot sin
    material asignado es simplemente None, así que el filtro acá es más
    simple que en la versión de Maya."""
    for slot in obj.material_slots:
        if slot.material is not None:
            return slot.material.name
    return None


def _socket(node: "bpy.types.Node", *names: str) -> Optional["bpy.types.NodeSocket"]:
    """Busca el primer input existente entre varios nombres candidatos —
    los nombres de los sockets del Principled BSDF cambiaron entre
    versiones de Blender (ej. "Emission" -> "Emission Color" en 4.0), así
    que probamos varias variantes en vez de asumir una sola."""
    for n in names:
        if n in node.inputs:
            return node.inputs[n]
    return None


def _udim_tiles_from_disk(representative_path: str) -> Dict[int, str]:
    """Dado un path con el token "<UDIM>", busca en disco los archivos
    reales de cada tile y devuelve {numero_de_tile: filepath}. Blender
    necesita registrar cada tile a mano (a diferencia de Arnold, que
    resuelve el token <UDIM> por convención en el momento del render).

    El número de tile se lee en la posición del token (ver
    core.get_udim_tile_files), no como "el primer grupo de 4 dígitos del
    nombre": con eso, un asset como "Crate2048_BaseColor.1001.png" se
    registraba como tile 2048."""
    folder = os.path.dirname(representative_path)
    try:
        names = os.listdir(folder)
    except OSError:
        return {}
    return core.get_udim_tile_files(
        representative_path, [os.path.join(folder, n) for n in names])


def _load_image(file_path: str, is_udim: bool, colorspace: str) -> Optional["bpy.types.Image"]:
    try:
        if is_udim:
            tiles = _udim_tiles_from_disk(file_path)
            if not tiles:
                _warn(f"[TextureAutoloader] No UDIM tiles found on disk for: {file_path}")
                return None
            first_tile = min(tiles)
            image = bpy.data.images.load(tiles[first_tile], check_existing=True)
            image.source = 'TILED'
            for tile_number in sorted(tiles):
                if tile_number == first_tile:
                    continue
                try:
                    image.tiles.new(tile_number=tile_number)
                except RuntimeError:
                    pass  # el tile ya estaba registrado
        else:
            image = bpy.data.images.load(file_path, check_existing=True)
        try:
            image.colorspace_settings.name = colorspace
        except TypeError:
            # Nombre de colorspace no reconocido por el config de color
            # activo (ej. OCIO custom) — no es un error fatal, sólo el
            # colorspace queda en el default que Blender infiera.
            _warn(f"[TextureAutoloader] Could not set colorspace '{colorspace}' on {file_path}.")
        return image
    except RuntimeError as e:
        _warn(f"[TextureAutoloader] Could not load image '{file_path}': {e}")
        return None


def _add_image_node(node_tree: "bpy.types.NodeTree", file_path: str, is_udim: bool,
                     colorspace: str, label: str, x: float, y: float
                     ) -> Optional["bpy.types.Node"]:
    image = _load_image(file_path, is_udim, colorspace)
    if image is None:
        return None
    node = node_tree.nodes.new("ShaderNodeTexImage")
    node.image = image
    node.label = label
    node.location = (x, y)
    return node


def _cleanup_existing_material(obj: "bpy.types.Object") -> int:
    """Si el objeto ya tiene un material generado por esta herramienta, lo
    limpia (borra el material entero — a diferencia de Maya no tratamos
    de rescatar nodos sueltos, ya que en Blender un material completo con
    su node tree es una sola unidad de datos)."""
    mat = _find_autoloader_material(obj)
    if not mat:
        return 0
    users = mat.users
    name = mat.name
    try:
        bpy.data.materials.remove(mat, do_unlink=True)
        core.get_logger(_app_dir()).info(
            f"[TextureAutoloader] Cleaned up previous material '{name}' "
            f"(had {users} user(s)) from {obj.name} before rewiring.")
        return 1
    except Exception as e:
        _warn(f"Could not remove previous material '{name}' from {obj.name}: {e}")
        return 0


def _color_socket(sockets, name: str) -> "bpy.types.NodeSocket":
    """El nodo Mix tiene sockets float / vector / color que comparten el
    nombre ("A", "B", "Result"): pedimos explícitamente el de color en vez
    de confiar en qué devuelve sockets[name] en cada versión de Blender."""
    return next((s for s in sockets if s.name == name and s.type == 'RGBA'), sockets[name])


def process_textures(obj_name: str, mat_basename: str, channel_files: Dict[str, str],
                      config: Dict[str, Any]) -> Dict[str, Any]:
    """Crea un material Principled BSDF NUEVO, lo asigna al objeto (único
    slot — reemplaza cualquier asignación anterior) y conecta las
    texturas por tipo de mapa. Si el objeto ya tenía un material generado
    por esta herramienta, lo limpia primero.

    Devuelve un core.new_apply_result(): qué canal quedó cableado, cuál
    se salteó y por qué, y cuál falló — de ahí sale el reporte ✔/✘."""
    obj = bpy.data.objects.get(obj_name)
    if obj is None:
        raise RuntimeError(f"object '{obj_name}' not found in the scene")

    _cleanup_existing_material(obj)

    mat_name = f"M_{mat_basename}_TXA"
    mat = bpy.data.materials.new(name=mat_name)
    mat.use_nodes = True
    node_tree = mat.node_tree
    node_tree.nodes.clear()

    output = node_tree.nodes.new("ShaderNodeOutputMaterial")
    output.location = (500, 0)
    bsdf = node_tree.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (150, 0)
    node_tree.links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    obj.data.materials.clear()
    obj.data.materials.append(mat)

    result = core.new_apply_result(material=mat.name)
    base_color_node = None
    ao_node = None
    y = 400
    skipped_displacement = 0

    def link_to(node, socket, map_id, file_path, output_name="Color") -> None:
        """Conecta y anota el canal en el resultado: sin imagen = falló la
        carga; sin socket = el Principled BSDF de esta versión no lo tiene."""
        if node is None:
            result["failed"][map_id] = f"could not load {os.path.basename(file_path)}"
        elif socket is None:
            result["skipped"][map_id] = {"reason": "no_target", "target": "Principled BSDF"}
        else:
            node_tree.links.new(node.outputs[output_name], socket)
            result["wired"][map_id] = file_path

    for map_id, file_path in channel_files.items():
        is_udim = "<UDIM>" in file_path

        if map_id == "displacement" and not config.get("enable_displacement_wiring", False):
            skipped_displacement += 1
            result["skipped"][map_id] = {"reason": "displacement_off"}
            continue

        if map_id == "baseColor":
            node = _add_image_node(node_tree, file_path, is_udim, "sRGB", "Base Color", -400, y)
            base_color_node = node
            link_to(node, _socket(bsdf, "Base Color"), map_id, file_path)

        elif map_id == "roughness":
            node = _add_image_node(node_tree, file_path, is_udim, "Non-Color", "Roughness", -400, y)
            link_to(node, _socket(bsdf, "Roughness"), map_id, file_path)

        elif map_id == "metallic":
            node = _add_image_node(node_tree, file_path, is_udim, "Non-Color", "Metallic", -400, y)
            link_to(node, _socket(bsdf, "Metallic"), map_id, file_path)

        elif map_id == "normal":
            node = _add_image_node(node_tree, file_path, is_udim, "Non-Color", "Normal", -600, y)
            normal_map = None
            if node:
                normal_map = node_tree.nodes.new("ShaderNodeNormalMap")
                normal_map.location = (-350, y)
                node_tree.links.new(node.outputs["Color"], normal_map.inputs["Color"])
            link_to(normal_map if node else None, _socket(bsdf, "Normal"), map_id, file_path,
                    output_name="Normal")

        elif map_id == "emission":
            node = _add_image_node(node_tree, file_path, is_udim, "sRGB", "Emission", -400, y)
            link_to(node, _socket(bsdf, "Emission Color", "Emission"), map_id, file_path)
            strength_socket = _socket(bsdf, "Emission Strength")
            if node and strength_socket:
                strength_socket.default_value = 1.0

        elif map_id == "ao":
            ao_node = _add_image_node(node_tree, file_path, is_udim, "Non-Color", "AO", -400, y)
            if ao_node is None:
                result["failed"][map_id] = f"could not load {os.path.basename(file_path)}"

        elif map_id == "opacity":
            node = _add_image_node(node_tree, file_path, is_udim, "Non-Color", "Opacity", -400, y)
            link_to(node, _socket(bsdf, "Alpha"), map_id, file_path)
            if node:
                # Blender's transparency handling has changed across
                # versions (blend_method was removed from EEVEE Next in
                # 4.2). Best-effort: set it only if the attribute exists.
                try:
                    mat.blend_method = 'HASHED'
                except (AttributeError, TypeError):
                    pass

        elif map_id == "displacement":
            node = _add_image_node(node_tree, file_path, is_udim, "Non-Color", "Displacement", -400, y)
            disp_node = None
            if node:
                disp_node = node_tree.nodes.new("ShaderNodeDisplacement")
                disp_node.location = (150, -300)
                node_tree.links.new(node.outputs["Color"], disp_node.inputs["Height"])
                # True displacement only renders correctly in Cycles with
                # adaptive subdivision on the mesh — this wires the graph
                # but doesn't configure that for you, same conservative
                # stance as the Maya version's "detected but not
                # automatically deformed" behavior.
            link_to(disp_node, output.inputs["Displacement"], map_id, file_path,
                    output_name="Displacement")

        y -= 260

    # Post-proceso: AO × BaseColor, igual que en la versión de Maya
    if ao_node is not None:
        mix_node = node_tree.nodes.new("ShaderNodeMix")
        mix_node.data_type = 'RGBA'
        mix_node.blend_type = 'MULTIPLY'
        mix_node.inputs["Factor"].default_value = 1.0
        mix_node.location = (-150, 400)
        input_a = _color_socket(mix_node.inputs, "A")
        if base_color_node is not None:
            node_tree.links.new(base_color_node.outputs["Color"], input_a)
        else:
            input_a.default_value = (1.0, 1.0, 1.0, 1.0)
        node_tree.links.new(ao_node.outputs["Color"], _color_socket(mix_node.inputs, "B"))
        base_socket = _socket(bsdf, "Base Color")
        if base_socket:
            node_tree.links.new(_color_socket(mix_node.outputs, "Result"), base_socket)
            result["wired"]["ao"] = channel_files["ao"]
        else:
            result["skipped"]["ao"] = {"reason": "no_target", "target": "Principled BSDF"}

    if skipped_displacement:
        _warn(
            f"[TextureAutoloader] {skipped_displacement} displacement/height map(s) "
            f"detected on {obj.name} but NOT wired (enable "
            f"'enable_displacement_wiring' in texture_autoloader_config.json if you "
            f"want them — true displacement also needs Cycles + adaptive "
            f"subdivision to look right).")

    core.get_logger(_app_dir()).info(
        f"[TextureAutoloader] Material '{mat.name}' applied to {obj.name} "
        f"with {len(result['wired'])} of {len(channel_files)} channel(s) wired.")
    return result


# ══════════════════════════════════════════════════════════════
#  PropertyGroup — estado expuesto en la UI (persistido en el .blend
#  salvo folder/threshold/etc., que también se guardan en
#  texture_autoloader_state.json para sobrevivir entre archivos .blend
#  distintos, igual que la carpeta reciente en la versión de Maya).
# ══════════════════════════════════════════════════════════════

def _on_language_update(self, context):
    state = core.load_state(_app_dir())
    state["language"] = self.language
    core.save_state(_app_dir(), state)


def _on_threshold_update(self, context):
    state = core.load_state(_app_dir())
    state["last_threshold"] = self.threshold
    core.save_state(_app_dir(), state)


def _on_match_mode_update(self, context):
    state = core.load_state(_app_dir())
    state["last_match_mode"] = self.match_mode
    core.save_state(_app_dir(), state)


def _on_recursive_update(self, context):
    state = core.load_state(_app_dir())
    state["last_recursive"] = self.recursive
    core.save_state(_app_dir(), state)


class TEXTUREAUTOLOADER_PG_properties(PropertyGroup):
    folder: StringProperty(
        name="Folder", subtype='DIR_PATH', default="")
    recursive: BoolProperty(
        name="Recursive", default=False, update=_on_recursive_update)
    threshold: FloatProperty(
        name="Sensitivity", default=0.60, min=0.0, max=1.0, subtype='FACTOR',
        update=_on_threshold_update)
    match_mode: EnumProperty(
        name="Match by",
        items=[
            ("object_name", "Object name", ""),
            ("material_id", "Material ID", ""),
        ],
        default="object_name",
        update=_on_match_mode_update,
    )
    language: EnumProperty(
        name="Language",
        items=[("en", "English", ""), ("es", "Español", "")],
        default="en",
        update=_on_language_update,
    )
    scan_info: StringProperty(name="Scan info", default="")
    match_status: StringProperty(name="Match status", default="")


# ══════════════════════════════════════════════════════════════
#  Operators
# ══════════════════════════════════════════════════════════════

class TEXTUREAUTOLOADER_OT_toggle_language(Operator):
    bl_idname = "texture_autoloader.toggle_language"
    bl_label = "Toggle language"
    bl_description = "Switch the panel between English and Spanish"

    def execute(self, context):
        props = context.scene.texture_autoloader
        props.language = core.other_language(props.language)
        return {'FINISHED'}


class TEXTUREAUTOLOADER_OT_browse_folder(Operator):
    bl_idname = "texture_autoloader.browse_folder"
    bl_label = "Select texture folder"
    directory: StringProperty(subtype='DIR_PATH')

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        context.scene.texture_autoloader.folder = self.directory
        bpy.ops.texture_autoloader.scan_folder()
        return {'FINISHED'}


class TEXTUREAUTOLOADER_OT_select_recent(Operator):
    bl_idname = "texture_autoloader.select_recent"
    bl_label = "Recent folder"
    path: StringProperty()

    def execute(self, context):
        context.scene.texture_autoloader.folder = self.path
        bpy.ops.texture_autoloader.scan_folder()
        return {'FINISHED'}


class TEXTUREAUTOLOADER_MT_recent_folders(Menu):
    bl_idname = "TEXTUREAUTOLOADER_MT_recent_folders"
    bl_label = "Recent folders"

    def draw(self, context):
        layout = self.layout
        state = core.load_state(_app_dir())
        recent = [f for f in state.get("recent_folders", []) if os.path.isdir(f)]
        if not recent:
            layout.label(text=_t("recent_placeholder"))
            return
        for path in recent:
            op = layout.operator(TEXTUREAUTOLOADER_OT_select_recent.bl_idname, text=path)
            op.path = path


class TEXTUREAUTOLOADER_OT_scan_folder(Operator):
    bl_idname = "texture_autoloader.scan_folder"
    bl_label = "Scan folder"
    bl_description = "Scan the selected folder for texture sets"

    def execute(self, context):
        global _TEX_MAP, _MATCHES
        props = context.scene.texture_autoloader
        folder = props.folder

        # Blender's DIR_PATH StringProperty stores paths like "//textures/"
        # (blend-relative) or with a trailing separator — normalize both.
        folder = bpy.path.abspath(folder)

        if not folder or not os.path.isdir(folder):
            self.report({'WARNING'}, _t("msg_folder_missing", folder=folder or "(empty)"))
            return {'CANCELLED'}

        config = _config()
        _TEX_MAP = core.scan_texture_folder(
            folder, config["suffix_strip_list"], set(config["texture_extensions"]),
            recursive=props.recursive)
        _MATCHES = []

        total_files = sum(len(v) for v in _TEX_MAP.values())
        props.scan_info = _t("scan_info", sets=len(_TEX_MAP), files=total_files)
        props.match_status = ""

        state = core.load_state(_app_dir())
        recent = core.push_recent_folder(state.get("recent_folders", []), folder)
        state["recent_folders"] = recent
        state["last_recursive"] = props.recursive
        core.save_state(_app_dir(), state)

        _log_print(f"[TextureAutoloader] Loaded {len(_TEX_MAP)} set(s) from: {folder}")
        return {'FINISHED'}


class TEXTUREAUTOLOADER_OT_smart_match(Operator):
    bl_idname = "texture_autoloader.smart_match"
    bl_label = "Smart Match"
    bl_description = "Match the selected mesh objects to the scanned texture sets"

    def execute(self, context):
        global _MATCHES
        props = context.scene.texture_autoloader
        selected = [o for o in context.selected_objects if o.type == 'MESH']

        if not selected:
            self.report({'WARNING'}, _t("msg_select_meshes"))
            return {'CANCELLED'}
        if not _TEX_MAP:
            self.report({'WARNING'}, _t("msg_load_folder_first"))
            return {'CANCELLED'}

        config = _config()
        object_entries: List[Tuple[str, Optional[str]]] = []
        for obj in selected:
            assigned = _get_assigned_material_name(obj) if props.match_mode == "material_id" else None
            object_entries.append((obj.name, assigned))

        _MATCHES = core.match_objects_to_textures(
            object_entries, _TEX_MAP, config, match_mode=props.match_mode, warn_fn=_warn)

        matched = sum(1 for m in _MATCHES if m["tex_base"])
        props.match_status = _t("match_status", matched=matched, total=len(_MATCHES))
        _log_print(f"[TextureAutoloader] Smart Match ({props.match_mode}): "
                   f"{matched}/{len(_MATCHES)}")
        return {'FINISHED'}


class TEXTUREAUTOLOADER_OT_toggle_channel(Operator):
    bl_idname = "texture_autoloader.toggle_channel"
    bl_label = "Toggle channel"
    match_index: IntProperty()
    map_id: StringProperty()

    def execute(self, context):
        if 0 <= self.match_index < len(_MATCHES):
            ch = _MATCHES[self.match_index]["channels"].get(self.map_id)
            if ch:
                ch["enabled"] = not ch["enabled"]
        return {'FINISHED'}


class TEXTUREAUTOLOADER_OT_remove_match(Operator):
    bl_idname = "texture_autoloader.remove_match"
    bl_label = "Remove from batch"
    bl_description = "Remove this object from the batch without deleting anything in the scene"
    match_index: IntProperty()

    def execute(self, context):
        global _MATCHES
        if 0 <= self.match_index < len(_MATCHES):
            _MATCHES.pop(self.match_index)
        return {'FINISHED'}


class TEXTUREAUTOLOADER_OT_reassign_match(Operator):
    bl_idname = "texture_autoloader.reassign_match"
    bl_label = "Reassign texture set"
    match_index: IntProperty()
    tex_base: StringProperty()

    def execute(self, context):
        global _MATCHES
        if 0 <= self.match_index < len(_MATCHES):
            config = _config()
            m = _MATCHES[self.match_index]
            new_base = self.tex_base or None
            _MATCHES[self.match_index] = core.build_match_entry(
                m["obj"], new_base, 1.0 if new_base else 0.0, _TEX_MAP, config, warn_fn=_warn)
        return {'FINISHED'}


class TEXTUREAUTOLOADER_MT_reassign(Menu):
    bl_idname = "TEXTUREAUTOLOADER_MT_reassign"
    bl_label = "Reassign"

    def draw(self, context):
        layout = self.layout
        match_index = context.window_manager.texture_autoloader_reassign_index
        op = layout.operator(TEXTUREAUTOLOADER_OT_reassign_match.bl_idname,
                              text=_t("dialog_reassign_none"))
        op.match_index = match_index
        op.tex_base = ""
        for tex_base in _TEX_MAP.keys():
            op = layout.operator(TEXTUREAUTOLOADER_OT_reassign_match.bl_idname, text=tex_base)
            op.match_index = match_index
            op.tex_base = tex_base


class TEXTUREAUTOLOADER_OT_open_reassign_menu(Operator):
    bl_idname = "texture_autoloader.open_reassign_menu"
    bl_label = "Reassign"
    match_index: IntProperty()

    def execute(self, context):
        context.window_manager.texture_autoloader_reassign_index = self.match_index
        bpy.ops.wm.call_menu(name=TEXTUREAUTOLOADER_MT_reassign.bl_idname)
        return {'FINISHED'}


class TEXTUREAUTOLOADER_OT_apply_all(Operator):
    bl_idname = "texture_autoloader.apply_all"
    bl_label = "Apply to all matches"
    bl_description = "Wire a Principled BSDF for every matched object in the batch"

    def execute(self, context):
        if not _MATCHES:
            self.report({'WARNING'}, _t("msg_run_smart_match_first"))
            return {'CANCELLED'}

        config = _config()
        conflicts = [m["obj"] for m in _MATCHES if m["tex_base"]
                     and bpy.data.objects.get(m["obj"])
                     and has_autoloader_material(bpy.data.objects[m["obj"]])]
        if conflicts:
            # Blender operators can't easily block on a modal confirm
            # dialog from execute() the way Qt's QMessageBox.question()
            # does — the old material is simply replaced, same end
            # result as answering "Yes" in the Maya version, just without
            # the extra click. Reported as an INFO so it's visible in the
            # status bar / Info log either way.
            self.report(
                {'INFO'},
                _t("dialog_existing_materials_body", count=len(conflicts)).replace("\n\n", " "))

        def _apply_one(obj_name: str, mat_basename: str,
                       channel_files: Dict[str, str]) -> Dict[str, Any]:
            return process_textures(obj_name, mat_basename, channel_files, config)

        applied, skipped = core.apply_auto_textures(
            _MATCHES, config, apply_one_fn=_apply_one, log_fn=_log_print)

        language = context.scene.texture_autoloader.language
        text_name = _publish_report(core.build_report(_MATCHES, language, tex_map=_TEX_MAP))
        self.report(
            {'INFO'},
            f"{_t('done_body_applied')}: {applied}    {_t('done_body_skipped')}: {skipped}    "
            f"{_t('report_in_text_editor', name=text_name)}")
        return {'FINISHED'}


class TEXTUREAUTOLOADER_OT_show_report(Operator):
    bl_idname = "texture_autoloader.show_report"
    bl_label = "Texture Autoloader — report"
    bl_description = "Show the ✔/✘ report of the last run"

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=720)

    def execute(self, context):
        return {'FINISHED'}

    def draw(self, context):
        col = self.layout.column(align=True)
        for line in (_LAST_REPORT or "").splitlines():
            col.label(text=line or " ")


class TEXTUREAUTOLOADER_OT_manual_apply(Operator):
    """Modo manual: aplica archivos elegidos a mano al objeto activo,
    sin pasar por el escaneo/matching del Auto-Loader."""
    bl_idname = "texture_autoloader.manual_apply"
    bl_label = "Select files and apply"
    filepath: StringProperty(subtype='FILE_PATH')
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement)
    directory: StringProperty(subtype='DIR_PATH')
    filter_glob: StringProperty(
        default="*.png;*.jpg;*.jpeg;*.tga;*.exr;*.tif;*.tiff;*.hdr;*.bmp", options={'HIDDEN'})

    def invoke(self, context, event):
        if context.active_object is None or context.active_object.type != 'MESH':
            self.report({'WARNING'}, _t("msg_select_object"))
            return {'CANCELLED'}
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        obj = context.active_object
        config = _config()
        file_paths = [os.path.join(self.directory, f.name) for f in self.files]
        if not file_paths:
            return {'CANCELLED'}

        label = core.tex_base_name(os.path.basename(file_paths[0]), config["suffix_strip_list"])
        entry = core.build_entry_from_files(obj.name, label, file_paths, config, warn_fn=_warn)
        channel_files = {mid: ch["file"] for mid, ch in entry["channels"].items()}
        try:
            entry["result"] = process_textures(obj.name, obj.name, channel_files, config)
            entry["status"] = "applied"
        except Exception as e:
            entry["status"], entry["error"] = "error", str(e)

        text_name = _publish_report(
            core.build_report([entry], context.scene.texture_autoloader.language))
        self.report({'WARNING'} if entry["unrecognized"] or entry["status"] == "error" else {'INFO'},
                    _t("report_in_text_editor", name=text_name))
        return {'FINISHED'}


# ══════════════════════════════════════════════════════════════
#  Panel — Sidebar (N-panel) del 3D Viewport
# ══════════════════════════════════════════════════════════════

def _wrapped_label(layout, text: str, width_chars: int = 46) -> None:
    """Blender's UILayout.label() doesn't wrap text — split manually at
    roughly `width_chars` per line on word boundaries."""
    import textwrap
    col = layout.column(align=True)
    for line in textwrap.wrap(text, width_chars):
        col.label(text=line)


class TEXTUREAUTOLOADER_PT_main(Panel):
    bl_idname = "TEXTUREAUTOLOADER_PT_main"
    bl_label = "Texture Autoloader"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Texture Autoloader"

    def draw(self, context):
        layout = self.layout
        props = context.scene.texture_autoloader
        L = props.language

        header_row = layout.row()
        header_row.label(text=core.tr(L, "app_title"), icon='TEXTURE')
        lang_row = header_row.row()
        lang_row.alignment = 'RIGHT'
        lang_row.scale_x = 0.8
        lang_row.operator(
            TEXTUREAUTOLOADER_OT_toggle_language.bl_idname,
            text=core.tr(core.other_language(L), "lang_button"))

        layout.separator()

        # ── Manual ──────────────────────────────────────────
        box = layout.box()
        box.label(text="◆  " + core.tr(L, "section_manual"))
        _wrapped_label(box, core.tr(L, "section_manual_desc"))
        box.operator(TEXTUREAUTOLOADER_OT_manual_apply.bl_idname,
                     text=core.tr(L, "btn_manual_apply"))

        layout.separator()

        # ── Auto-Loader ─────────────────────────────────────
        box = layout.box()
        box.label(text="✦  " + core.tr(L, "section_autoloader"))
        _wrapped_label(box, core.tr(L, "section_autoloader_desc"))

        row = box.row(align=True)
        row.menu(TEXTUREAUTOLOADER_MT_recent_folders.bl_idname,
                 text=core.tr(L, "recent_label"))

        row = box.row(align=True)
        row.prop(props, "folder", text="")
        row.operator(TEXTUREAUTOLOADER_OT_browse_folder.bl_idname, text="", icon='FILE_FOLDER')
        row.prop(props, "recursive", text=core.tr(L, "btn_recursive"), toggle=True)

        box.operator(TEXTUREAUTOLOADER_OT_scan_folder.bl_idname,
                     text=core.tr(L, "btn_browse"), icon='VIEWZOOM')

        if props.scan_info:
            box.label(text=props.scan_info)

        box.prop(props, "threshold", text=core.tr(L, "sensitivity_label"), slider=True)

        box.label(text=core.tr(L, "match_by_label"))
        row = box.row(align=True)
        row.prop_enum(props, "match_mode", "object_name", text=core.tr(L, "match_by_object_name"))
        row.prop_enum(props, "match_mode", "material_id", text=core.tr(L, "match_by_material_id"))

        info_key = "match_mode_info_material_id" if props.match_mode == "material_id" \
            else "match_mode_info_object_name"
        _wrapped_label(box, core.tr(L, info_key))

        box.operator(TEXTUREAUTOLOADER_OT_smart_match.bl_idname,
                     text=core.tr(L, "btn_smart_match"), icon='SHADING_RENDERED')

        if _MATCHES:
            box.label(text=core.tr(L, "preview_label"))
            preview_col = box.column(align=True)
            for idx, m in enumerate(_MATCHES):
                row = preview_col.box().column(align=True)
                header = row.row(align=True)
                obj_short = m["obj"]
                tex_label = m["tex_base"] if m["tex_base"] else core.tr(L, "no_match")
                header.label(text=f"{m['score']:.0%}  {obj_short} → {tex_label}")
                reassign_op = header.operator(
                    TEXTUREAUTOLOADER_OT_open_reassign_menu.bl_idname, text="", icon='DOWNARROW_HLT')
                reassign_op.match_index = idx
                remove_op = header.operator(
                    TEXTUREAUTOLOADER_OT_remove_match.bl_idname, text="", icon='X')
                remove_op.match_index = idx

                for map_id, ch in m["channels"].items():
                    ch_row = row.row(align=True)
                    toggle_op = ch_row.operator(
                        TEXTUREAUTOLOADER_OT_toggle_channel.bl_idname,
                        text=map_id,
                        depress=ch["enabled"],
                    )
                    toggle_op.match_index = idx
                    toggle_op.map_id = map_id
                    tag = core.tr(L, "overridden_tag") if ch["overridden"] else (
                        core.tr(L, "udim_tag") if ch["is_udim"] else "")
                    ch_row.label(text=os.path.basename(ch["file"]) + tag)

            box.label(text=props.match_status)

        box.operator(TEXTUREAUTOLOADER_OT_apply_all.bl_idname,
                     text=core.tr(L, "btn_apply_all"), icon='PLAY')
        if _LAST_REPORT:
            box.label(text=_LAST_REPORT.splitlines()[-1])
            box.operator(TEXTUREAUTOLOADER_OT_show_report.bl_idname,
                         text=core.tr(L, "btn_show_report"), icon='TEXT')

        layout.separator()
        footer_row = layout.row()
        footer_row.alignment = 'CENTER'
        footer_row.label(text=core.tr(L, "footer"))


# ══════════════════════════════════════════════════════════════
#  Registro del addon
# ══════════════════════════════════════════════════════════════

_CLASSES = (
    TEXTUREAUTOLOADER_PG_properties,
    TEXTUREAUTOLOADER_OT_toggle_language,
    TEXTUREAUTOLOADER_OT_browse_folder,
    TEXTUREAUTOLOADER_OT_select_recent,
    TEXTUREAUTOLOADER_MT_recent_folders,
    TEXTUREAUTOLOADER_OT_scan_folder,
    TEXTUREAUTOLOADER_OT_smart_match,
    TEXTUREAUTOLOADER_OT_toggle_channel,
    TEXTUREAUTOLOADER_OT_remove_match,
    TEXTUREAUTOLOADER_OT_reassign_match,
    TEXTUREAUTOLOADER_MT_reassign,
    TEXTUREAUTOLOADER_OT_open_reassign_menu,
    TEXTUREAUTOLOADER_OT_apply_all,
    TEXTUREAUTOLOADER_OT_show_report,
    TEXTUREAUTOLOADER_OT_manual_apply,
    TEXTUREAUTOLOADER_PT_main,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.texture_autoloader = bpy.props.PointerProperty(
        type=TEXTUREAUTOLOADER_PG_properties)
    bpy.types.WindowManager.texture_autoloader_reassign_index = IntProperty(default=-1)

    # Restaura preferencias persistidas (threshold/idioma/modo/recursivo)
    # en la primera escena disponible al habilitar el addon — Blender no
    # tiene un "on scene load" simple para PropertyGroups sin usar
    # handlers de app; hacerlo acá cubre el caso normal de habilitar el
    # addon y abrir el panel en la sesión actual.
    try:
        state = core.load_state(_app_dir())
        config = core.load_config(_app_dir(), warn_fn=_warn)
        for scene in bpy.data.scenes:
            props = scene.texture_autoloader
            props.language = state.get("language", config.get("language", core.DEFAULT_LANGUAGE))
            props.threshold = state.get("last_threshold", config.get("match_threshold", 0.60))
            props.match_mode = state.get("last_match_mode", config.get("match_mode", "object_name"))
            props.recursive = bool(state.get("last_recursive", False))
    except Exception:
        pass


def unregister():
    del bpy.types.WindowManager.texture_autoloader_reassign_index
    del bpy.types.Scene.texture_autoloader
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
