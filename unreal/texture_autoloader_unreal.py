"""
Texture Autoloader — Unreal Engine front-end (work in progress)
================================================================
Author: Manuel Castellani

Unreal Engine port of Texture Autoloader, via the Python Editor Scripting
API. Same scanning / matching / map-type logic as the Maya and Blender
versions, shared through dcc_mejoras/core/texture_autoloader_core.py —
this file only adds what is genuinely Unreal-specific:

  - The unit of matching is the Material Slot, not the object: a mesh
    with 3 slots can need 3 texture sets. Each slot tries, most specific
    first, "<mesh>_<slot>" (Substance's default $mesh_$textureSet export
    naming), "<slot>" and "<mesh>".
  - No node graph is wired. Textures are imported as assets (with sRGB /
    compression set per channel), and a Material Instance per texture set
    is created (or updated) from a Master Material, binding each texture
    to a texture parameter ("parameter binding", not "wiring").
  - If the configured Master Material doesn't exist, a default one is
    generated (plus a Masked variant, used for sets with an opacity map),
    with neutral default textures so a missing channel stays neutral.

UI: a "Texture Autoloader…" entry in the Content Browser's right-click
menu and in Tools (see register_menus / init_unreal.py). It opens a native
details dialog for the settings, shows a preview of the matches to
confirm, applies, and shows the ✔/✘ report. process_folder() does the
same without any dialog, for scripting and tests.

Known limitation: UDIM texture sets are reported (✘) and skipped — Unreal
imports UDIMs as virtual textures, which needs a virtual-texture sampler
in the Master Material; not handled yet.

See unreal/README.md for setup.
"""

import os
import re
import shutil
import struct
import sys
import tempfile
import zlib
from typing import Any, Dict, List, Optional, Tuple

import unreal


# ══════════════════════════════════════════════════════════════
#  Bootstrap: hace importable el core compartido. Mismo patrón que
#  los front-ends de Maya y Blender, pero el core no es una carpeta
#  hermana: vive en dcc_mejoras/core/ (un solo core para los tres
#  DCCs, ver CLAUDE.md).
# ══════════════════════════════════════════════════════════════

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_CORE_DIR = os.path.join(os.path.dirname(_THIS_DIR), "dcc_mejoras", "core")
if _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)

import texture_autoloader_core as core  # noqa: E402


TITLE = "Texture Autoloader"


def _app_dir() -> str:
    return _THIS_DIR


def _warn(message: str) -> None:
    unreal.log_warning(message)
    try:
        core.get_logger(_app_dir()).warning(message)
    except Exception:
        pass


def _log(message: str) -> None:
    unreal.log(message)
    try:
        core.get_logger(_app_dir()).info(message)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
#  CONFIG — la del core + una sección "unreal" propia. Se guarda en
#  texture_autoloader_config.json junto a este archivo, como en Maya
#  y Blender.
# ══════════════════════════════════════════════════════════════

UNREAL_SECTION_DEFAULTS: Dict[str, Any] = {
    # Master Materials (created with default parameters if missing).
    "master_material": "/Game/TextureAutoloader/M_TextureAutoloader_Master",
    "master_material_masked": "/Game/TextureAutoloader/M_TextureAutoloader_Master_Masked",
    "create_master_materials": True,
    # Where imported textures go: one sub-folder per texture set.
    "texture_folder": "/Game/TextureAutoloader/Textures",
    # Where Material Instances go; "" = next to each mesh.
    "material_instance_folder": "",
    "texture_prefix": "T_",
    "material_instance_prefix": "MI_",
    # Core channel id -> texture parameter name in the Master Material.
    "parameters": {
        "baseColor": "BaseColor",
        "normal": "Normal",
        "roughness": "Roughness",
        "metallic": "Metallic",
        "ao": "AmbientOcclusion",
        "emission": "Emissive",
        "opacity": "Opacity",
    },
    # Optional per-channel override of the import settings, e.g.
    # {"roughness": {"srgb": false, "compression": "TC_GRAYSCALE"}} if your
    # own Master Material samples roughness as Linear Grayscale.
    "texture_settings": {},
}

UNREAL_DEFAULT_CONFIG: Dict[str, Any] = dict(
    core.DEFAULT_CONFIG,
    # In Unreal the slot IS the material id: match by slot name by default.
    match_mode="material_id",
    unreal=UNREAL_SECTION_DEFAULTS,
)

# Slot names that say nothing about the texture set (FBX without
# materials, DCC defaults): those slots fall back to the mesh's name.
_GENERIC_SLOT_NAMES = {"", "none", "material", "defaultmaterial", "worldgridmaterial",
                       "lambert1", "standardsurface1", "initialshadinggroup"}


def load_config() -> Dict[str, Any]:
    config = core.load_config(_app_dir(), warn_fn=_warn, defaults=UNREAL_DEFAULT_CONFIG)
    return merge_unreal_section(config)


def merge_unreal_section(config: Dict[str, Any]) -> Dict[str, Any]:
    """core.load_config merges top-level keys only: a config file that sets
    just "unreal": {"master_material": ...} would otherwise lose every
    other key of the section."""
    section = dict(UNREAL_SECTION_DEFAULTS)
    section.update(config.get("unreal") or {})
    section["parameters"] = dict(UNREAL_SECTION_DEFAULTS["parameters"],
                                 **((config.get("unreal") or {}).get("parameters") or {}))
    return dict(config, unreal=section)


# ══════════════════════════════════════════════════════════════
#  PURE HELPERS (no Unreal calls — covered by unreal/tests)
# ══════════════════════════════════════════════════════════════

def slot_candidates(mesh_name: str, slot_name: str, match_mode: str,
                    config: Dict[str, Any]) -> List[str]:
    """Names a Material Slot is matched against, most specific first.

    material_id (default): "<mesh>_<slot>", "<slot>", "<mesh>".
    object_name: "<mesh>" only — every slot of the mesh gets the same set.
    A generic slot name ("None", "WorldGridMaterial", ...) always falls
    back to the mesh name."""
    prefixes = config["mesh_prefixes"]
    mesh_base = core.mesh_base_name(mesh_name, prefixes)
    slot_base = core.material_base_name(slot_name, prefixes)
    generic = (slot_name.strip().lower() in _GENERIC_SLOT_NAMES
               or slot_base.strip().lower() in _GENERIC_SLOT_NAMES)
    if match_mode != "material_id" or generic:
        return [mesh_base]
    candidates = []
    for name in (f"{mesh_base}_{slot_base}", slot_base, mesh_base):
        if name and name not in candidates:
            candidates.append(name)
    return candidates


def slot_key(mesh_name: str, slot_name: str) -> str:
    """How a slot shows up in the preview and the report."""
    return f"{mesh_name} · {slot_name or '(slot)'}"


def asset_name(stem: str, prefix: str) -> str:
    """Valid Unreal asset name: letters, digits and "_" only, with the
    studio prefix ("T_", "MI_") unless it's already there."""
    name = re.sub(r"[^A-Za-z0-9_]", "_", stem).strip("_") or "Asset"
    return name if name.upper().startswith(prefix.upper()) else prefix + name


def texture_settings_for(channel: str, config: Dict[str, Any]) -> Tuple[bool, str]:
    """(sRGB, compression setting) to import a channel's texture with,
    matching the sampler types of the generated Master Material: color
    maps sRGB / Default, normal maps Normalmap, everything else linear
    Masks."""
    override = (config["unreal"].get("texture_settings") or {}).get(channel) or {}
    if channel == "normal":
        srgb, compression = False, "TC_NORMALMAP"
    else:
        map_type = next((mt for mt in config["map_types"] if mt["id"] == channel), None)
        raw = map_type.get("raw", True) if map_type else True
        srgb, compression = (False, "TC_MASKS") if raw else (True, "TC_DEFAULT")
    return bool(override.get("srgb", srgb)), str(override.get("compression", compression))


def write_png(path: str, rgb: Tuple[int, int, int], size: int = 4) -> None:
    """Minimal valid RGB PNG (for the Master Material's default textures)."""
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw))
                + chunk(b"IEND", b""))


# ══════════════════════════════════════════════════════════════
#  MESHES & SLOTS
# ══════════════════════════════════════════════════════════════

def get_selected_meshes() -> List[Any]:
    assets = unreal.EditorUtilityLibrary.get_selected_assets() or []
    return [a for a in assets if isinstance(a, (unreal.StaticMesh, unreal.SkeletalMesh))]


def _slot_array(mesh) -> List[Any]:
    prop = "static_materials" if isinstance(mesh, unreal.StaticMesh) else "materials"
    return list(mesh.get_editor_property(prop))


def mesh_slots(mesh) -> List[str]:
    return [str(m.get_editor_property("material_slot_name")) for m in _slot_array(mesh)]


def assign_slot_material(mesh, slot_index: int, material) -> None:
    if isinstance(mesh, unreal.StaticMesh):
        mesh.set_material(slot_index, material)
    else:
        slots = _slot_array(mesh)
        slots[slot_index].set_editor_property("material_interface", material)
        mesh.set_editor_property("materials", slots)
    unreal.EditorAssetLibrary.save_loaded_asset(mesh, only_if_is_dirty=False)


def match_meshes(meshes: List[Any], tex_map: Dict[str, List[str]], config: Dict[str, Any],
                 match_mode: str) -> Tuple[List[Dict[str, Any]], Dict[str, Tuple[Any, int]]]:
    """One core match entry per Material Slot. Returns (matches,
    {slot key: (mesh, slot index)})."""
    named: List[Tuple[str, List[str]]] = []
    refs: Dict[str, Tuple[Any, int]] = {}
    for mesh in meshes:
        mesh_name = mesh.get_name()
        for index, slot_name in enumerate(mesh_slots(mesh)):
            key = slot_key(mesh_name, slot_name)
            if key in refs:  # two selected meshes share a name
                key = f"{key} ({mesh.get_path_name()})"
            refs[key] = (mesh, index)
            named.append((key, slot_candidates(mesh_name, slot_name, match_mode, config)))
    return core.match_names_to_textures(named, tex_map, config, warn_fn=_warn), refs


# ══════════════════════════════════════════════════════════════
#  ASSETS: textures, default textures, Master Materials, MIs
# ══════════════════════════════════════════════════════════════

def _asset_tools():
    return unreal.AssetToolsHelpers.get_asset_tools()


def _load(path: str):
    return unreal.EditorAssetLibrary.load_asset(path) \
        if unreal.EditorAssetLibrary.does_asset_exist(path) else None


def import_texture(file_path: str, destination: str, channel: str,
                   config: Dict[str, Any]):
    """Imports (or re-imports over) one texture file as a Texture2D asset
    and sets sRGB / compression for its channel."""
    name = asset_name(os.path.splitext(os.path.basename(file_path))[0],
                      config["unreal"]["texture_prefix"])
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", file_path)
    task.set_editor_property("destination_path", destination)
    task.set_editor_property("destination_name", name)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("save", False)
    _asset_tools().import_asset_tasks([task])

    texture = None
    for path in task.get_editor_property("imported_object_paths") or []:
        texture = unreal.load_asset(path)
        if isinstance(texture, unreal.Texture2D):
            break
    if not isinstance(texture, unreal.Texture2D):
        texture = _load(f"{destination}/{name}")
    if not isinstance(texture, unreal.Texture2D):
        raise RuntimeError(f"could not import {os.path.basename(file_path)}")

    srgb, compression = texture_settings_for(channel, config)
    texture.set_editor_property("srgb", srgb)
    texture.set_editor_property("compression_settings",
                                getattr(unreal.TextureCompressionSettings, compression))
    unreal.EditorAssetLibrary.save_loaded_asset(texture, only_if_is_dirty=False)
    return texture


# name, color, sRGB, compression
_DEFAULT_TEXTURES = {
    "white": ("T_TAL_Default_White", (255, 255, 255), True, "TC_DEFAULT"),
    "black": ("T_TAL_Default_Black", (0, 0, 0), True, "TC_DEFAULT"),
    "white_mask": ("T_TAL_Default_WhiteMask", (255, 255, 255), False, "TC_MASKS"),
    "black_mask": ("T_TAL_Default_BlackMask", (0, 0, 0), False, "TC_MASKS"),
    "flat_normal": ("T_TAL_Default_FlatNormal", (128, 128, 255), False, "TC_NORMALMAP"),
}


def ensure_default_textures(folder: str) -> Dict[str, Any]:
    """Tiny neutral textures for the generated Master Material's
    parameters, so a set that lacks a channel stays neutral (white AO,
    black metallic, flat normal...). Generated instead of borrowing engine
    content: engine textures come with sRGB/compression that don't match
    the Masks/Normal samplers, which Unreal rejects."""
    textures = {}
    tmp = tempfile.mkdtemp(prefix="tal_defaults_")
    try:
        for key, (name, rgb, srgb, compression) in _DEFAULT_TEXTURES.items():
            texture = _load(f"{folder}/{name}")
            if texture is None:
                png = os.path.join(tmp, name + ".png")
                write_png(png, rgb)
                task = unreal.AssetImportTask()
                task.set_editor_property("filename", png)
                task.set_editor_property("destination_path", folder)
                task.set_editor_property("destination_name", name)
                task.set_editor_property("automated", True)
                task.set_editor_property("replace_existing", True)
                _asset_tools().import_asset_tasks([task])
                texture = _load(f"{folder}/{name}")
                if texture is None:
                    raise RuntimeError(f"could not create the default texture {name}")
                texture.set_editor_property("srgb", srgb)
                texture.set_editor_property(
                    "compression_settings", getattr(unreal.TextureCompressionSettings, compression))
                unreal.EditorAssetLibrary.save_loaded_asset(texture, only_if_is_dirty=False)
            textures[key] = texture
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return textures


# channel, material input, output pin, sampler type, default texture
_MASTER_LAYOUT = [
    ("baseColor", "MP_BASE_COLOR", "RGB", "SAMPLERTYPE_COLOR", "white"),
    ("metallic", "MP_METALLIC", "R", "SAMPLERTYPE_MASKS", "black_mask"),
    ("roughness", "MP_ROUGHNESS", "R", "SAMPLERTYPE_MASKS", "white_mask"),
    ("normal", "MP_NORMAL", "RGB", "SAMPLERTYPE_NORMAL", "flat_normal"),
    ("emission", "MP_EMISSIVE_COLOR", "RGB", "SAMPLERTYPE_COLOR", "black"),
    ("ao", "MP_AMBIENT_OCCLUSION", "R", "SAMPLERTYPE_MASKS", "white_mask"),
    ("opacity", "MP_OPACITY_MASK", "R", "SAMPLERTYPE_MASKS", "white_mask"),
]


def create_master_material(path: str, config: Dict[str, Any], masked: bool):
    """Default Master Material: one TextureSampleParameter2D per channel
    (named after config["unreal"]["parameters"]) plugged into the matching
    material input. The masked variant adds Opacity -> Opacity Mask."""
    folder, name = path.rsplit("/", 1)
    material = _asset_tools().create_asset(name, folder, unreal.Material, unreal.MaterialFactoryNew())
    if masked:
        material.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED)
    defaults = ensure_default_textures(f"{folder}/Defaults")
    mel = unreal.MaterialEditingLibrary
    params = config["unreal"]["parameters"]
    row = 0
    for channel, material_input, pin, sampler, default in _MASTER_LAYOUT:
        if channel == "opacity" and not masked:
            continue
        expression = mel.create_material_expression(
            material, unreal.MaterialExpressionTextureSampleParameter2D, -500, row * 280 - 700)
        expression.set_editor_property("parameter_name", params[channel])
        expression.set_editor_property("sampler_type", getattr(unreal.MaterialSamplerType, sampler))
        expression.set_editor_property("texture", defaults[default])
        mel.connect_material_property(expression, pin, getattr(unreal.MaterialProperty, material_input))
        row += 1
    mel.recompile_material(material)
    unreal.EditorAssetLibrary.save_loaded_asset(material, only_if_is_dirty=False)
    _log(f"[TextureAutoloader] Created Master Material {path}")
    return material


def get_or_create_material_instance(name: str, folder: str, parent):
    path = f"{folder}/{name}"
    instance = _load(path)
    if instance is None:
        instance = _asset_tools().create_asset(
            name, folder, unreal.MaterialInstanceConstant,
            unreal.MaterialInstanceConstantFactoryNew())
    if not isinstance(instance, unreal.MaterialInstanceConstant):
        raise RuntimeError(f"{path} exists and is not a Material Instance")
    unreal.MaterialEditingLibrary.set_material_instance_parent(instance, parent)
    return instance


def _package_folder(asset) -> str:
    return asset.get_path_name().rsplit("/", 1)[0]


# ══════════════════════════════════════════════════════════════
#  APPLY
# ══════════════════════════════════════════════════════════════

class _Session:
    """What a batch shares between slots: the masters, their parameter
    names, textures already imported and MIs already built this run."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.masters: Dict[bool, Any] = {}
        self.master_params: Dict[bool, set] = {}
        self.textures: Dict[str, Any] = {}
        self.instances: Dict[str, Tuple[Any, Dict[str, Any]]] = {}

    def master(self, masked: bool):
        if masked not in self.masters:
            section = self.config["unreal"]
            path = section["master_material_masked" if masked else "master_material"]
            material = _load(path)
            if material is None:
                if not section.get("create_master_materials", True):
                    raise RuntimeError(f"Master Material {path} doesn't exist")
                material = create_master_material(path, self.config, masked)
            self.masters[masked] = material
            self.master_params[masked] = {
                str(p) for p in unreal.MaterialEditingLibrary.get_texture_parameter_names(material)}
        return self.masters[masked]

    def texture(self, file_path: str, tex_base: str, channel: str):
        if file_path not in self.textures:
            destination = f"{self.config['unreal']['texture_folder']}/{asset_name(tex_base, '')}"
            self.textures[file_path] = import_texture(file_path, destination, channel, self.config)
        return self.textures[file_path]


def apply_slot(session: _Session, mesh, slot_index: int, tex_base: str,
               channel_files: Dict[str, str]) -> Dict[str, Any]:
    """Builds (or reuses) the Material Instance of `tex_base` and assigns it
    to the slot. Returns a core.new_apply_result() for the report."""
    config = session.config
    section = config["unreal"]
    params = section["parameters"]
    masked = "opacity" in channel_files and bool(section.get("master_material_masked"))
    master = session.master(masked)
    available = session.master_params[masked]

    folder = section.get("material_instance_folder") or _package_folder(mesh)
    mi_name = asset_name(tex_base, section["material_instance_prefix"])
    cache_key = f"{folder}/{mi_name}"

    if cache_key in session.instances:
        instance, result = session.instances[cache_key]
        result = {**result, "wired": dict(result["wired"])}  # same MI, same outcome
    else:
        instance = get_or_create_material_instance(mi_name, folder, master)
        result = core.new_apply_result(material=mi_name)
        mel = unreal.MaterialEditingLibrary
        for channel, file_path in channel_files.items():
            param = params.get(channel)
            if channel == "displacement" and not config.get("enable_displacement_wiring", False):
                result["skipped"][channel] = {"reason": "displacement_off"}
            elif "<UDIM>" in file_path:
                result["skipped"][channel] = {"reason": "udim_unsupported"}
            elif not param or param not in available:
                result["skipped"][channel] = {"reason": "missing_param", "target": master.get_name(),
                                              "param": param or channel}
            else:
                try:
                    texture = session.texture(file_path, tex_base, channel)
                    # The bool this returns isn't reliable (UE 5.8 returns False
                    # even when the value is set): read the parameter back instead.
                    mel.set_material_instance_texture_parameter_value(instance, param, texture)
                    bound = mel.get_material_instance_texture_parameter_value(instance, param)
                    if bound is None or bound.get_path_name() != texture.get_path_name():
                        raise RuntimeError(f"could not set parameter '{param}'")
                    result["wired"][channel] = file_path
                except Exception as e:
                    result["failed"][channel] = str(e)
        mel.update_material_instance(instance)
        unreal.EditorAssetLibrary.save_loaded_asset(instance, only_if_is_dirty=False)
        session.instances[cache_key] = (instance, result)

    assign_slot_material(mesh, slot_index, instance)
    return result


def apply_matches(matches: List[Dict[str, Any]], refs: Dict[str, Tuple[Any, int]],
                  config: Dict[str, Any], progress_cb=None) -> Tuple[int, int]:
    session = _Session(config)
    by_key = {m["obj"]: m for m in matches}

    def apply_one(key: str, _mat_basename: str, channel_files: Dict[str, str]) -> Dict[str, Any]:
        mesh, index = refs[key]
        return apply_slot(session, mesh, index, by_key[key]["tex_base"], channel_files)

    return core.apply_auto_textures(matches, config, apply_one_fn=apply_one,
                                    progress_cb=progress_cb, log_fn=_log)


def process_folder(meshes: List[Any], folder: str, config: Optional[Dict[str, Any]] = None,
                   match_mode: Optional[str] = None, recursive: bool = False,
                   naming_preset: Optional[str] = None,
                   language: str = core.DEFAULT_LANGUAGE) -> Tuple[List[Dict[str, Any]], str]:
    """Scan + match + apply with no dialogs (scripting, tests). Returns
    (matches, report)."""
    config = merge_unreal_section(config or load_config())
    config = core.apply_naming_preset(config, naming_preset or config.get("naming_preset"),
                                      warn_fn=_warn)
    tex_map = core.scan_texture_folder(folder, config["suffix_strip_list"],
                                       set(config["texture_extensions"]), recursive)
    matches, refs = match_meshes(meshes, tex_map, config, match_mode or config["match_mode"])
    apply_matches(matches, refs, config)
    report = core.build_report(matches, language, tex_map=tex_map)
    _log(report)
    return matches, report


# ══════════════════════════════════════════════════════════════
#  UI — native details dialog + preview/report message boxes
# ══════════════════════════════════════════════════════════════

_SETTINGS_CLASS = None


def _settings_class():
    """The settings object shown in the details dialog. Defined on first
    use (not at import) so the module can be imported outside the editor,
    and only once per session (a uclass can't be redefined)."""
    global _SETTINGS_CLASS
    if _SETTINGS_CLASS is None:
        @unreal.uclass()
        class TextureAutoloaderSettings(unreal.Object):
            texture_folder = unreal.uproperty(unreal.DirectoryPath, meta={
                "DisplayName": "Texture folder",
                "ToolTip": "Folder with the textures exported from Substance."})
            recursive = unreal.uproperty(bool, meta={
                "DisplayName": "Include subfolders"})
            match_by_slot_name = unreal.uproperty(bool, meta={
                "DisplayName": "Match by Material Slot",
                "ToolTip": "On: each Material Slot looks for its own texture set "
                           "(<mesh>_<slot>, <slot>). Off: every slot gets the set that "
                           "matches the mesh name."})
            sensitivity = unreal.uproperty(float, meta={
                "DisplayName": "Sensitivity", "ClampMin": "0.0", "ClampMax": "1.0",
                "ToolTip": "Higher = stricter name matching."})
            naming_preset = unreal.uproperty(str, meta={
                "DisplayName": "Naming preset",
                "ToolTip": "Suffix convention (texture_autoloader_config.json › naming_presets)."})
            language = unreal.uproperty(str, meta={
                "DisplayName": "Language (en / es)"})

        _SETTINGS_CLASS = TextureAutoloaderSettings
    return _SETTINGS_CLASS


def _message(message: str, buttons=None) -> Any:
    return unreal.EditorDialog.show_message(
        TITLE, message, buttons or unreal.AppMsgType.OK,
        default_value=unreal.AppReturnType.NO)


def run() -> None:
    """Menu entry point: settings dialog -> preview -> apply -> report."""
    config = load_config()
    state = core.load_state(_app_dir())
    language = state.get("language", config.get("language", core.DEFAULT_LANGUAGE))

    meshes = get_selected_meshes()
    if not meshes:
        _message(core.tr(language, "msg_select_meshes_unreal"))
        return

    values = ask_settings(len(meshes), config, state)
    if values is not None:
        run_with_settings(meshes, values, config, state)


def ask_settings(mesh_count: int, config: Dict[str, Any],
                 state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The settings dialog, prefilled from the last run. Returns the chosen
    values, or None if cancelled (always None in -unattended mode)."""
    settings = _settings_class()()
    folder_path = unreal.DirectoryPath()
    folder_path.set_editor_property("path", state.get("last_folder", ""))
    settings.set_editor_property("texture_folder", folder_path)
    settings.set_editor_property("recursive", bool(state.get("last_recursive", False)))
    settings.set_editor_property(
        "match_by_slot_name", state.get("last_match_mode", config["match_mode"]) == "material_id")
    settings.set_editor_property(
        "sensitivity", float(state.get("last_threshold", config["match_threshold"])))
    settings.set_editor_property(
        "naming_preset", state.get("last_naming_preset", config.get("naming_preset", "default")))
    settings.set_editor_property(
        "language", state.get("language", config.get("language", core.DEFAULT_LANGUAGE)))
    if not unreal.EditorDialog.show_object_details_view(f"{TITLE} — {mesh_count} mesh(es)",
                                                        settings):
        return None
    return {
        "folder": settings.get_editor_property("texture_folder").get_editor_property("path"),
        "recursive": bool(settings.get_editor_property("recursive")),
        "match_mode": ("material_id" if settings.get_editor_property("match_by_slot_name")
                       else "object_name"),
        "threshold": float(settings.get_editor_property("sensitivity")),
        "naming_preset": settings.get_editor_property("naming_preset").strip() or core.DEFAULT_PRESET_ID,
        "language": settings.get_editor_property("language").strip().lower() or core.DEFAULT_LANGUAGE,
    }


def run_with_settings(meshes: List[Any], values: Dict[str, Any], config: Dict[str, Any],
                      state: Dict[str, Any], confirm=None, show=None) -> Optional[str]:
    """Everything after the settings dialog: remember the choices, match,
    ask to confirm the preview, apply with a progress bar, show the report.
    `confirm(text) -> bool` and `show(text)` default to Unreal message boxes
    (tests pass their own). Returns the report, or None if nothing ran."""
    language = values["language"]
    confirm = confirm or (lambda text: _message(text, unreal.AppMsgType.YES_NO)
                          == unreal.AppReturnType.YES)
    show = show or _message
    folder = values["folder"]

    state.update({"last_folder": folder, "last_recursive": values["recursive"],
                  "last_match_mode": values["match_mode"], "last_threshold": values["threshold"],
                  "last_naming_preset": values["naming_preset"], "language": language})
    if folder:
        state["recent_folders"] = core.push_recent_folder(state.get("recent_folders", []), folder)
    core.save_state(_app_dir(), state)

    if not folder or not os.path.isdir(folder):
        show(core.tr(language, "msg_folder_missing", folder=folder or "(empty)"))
        return None

    config = core.apply_naming_preset(dict(config, match_threshold=values["threshold"]),
                                      values["naming_preset"], warn_fn=_warn)
    tex_map = core.scan_texture_folder(folder, config["suffix_strip_list"],
                                       set(config["texture_extensions"]), values["recursive"])
    matches, refs = match_meshes(meshes, tex_map, config, values["match_mode"])
    preview = core.build_report(matches, language, tex_map=tex_map, preview=True)
    if not confirm(preview + "\n\n" + core.tr(language, "msg_apply_question")):
        return None

    with unreal.ScopedSlowTask(len(matches), core.tr(language, "progress_applying")) as task:
        task.make_dialog(True)

        def progress(i: int, total: int, key: str) -> bool:
            if key:
                task.enter_progress_frame(1, core.tr(language, "progress_label", obj=key,
                                                     current=i + 1, total=total))
            return task.should_cancel()

        apply_matches(matches, refs, config, progress_cb=progress)

    report = core.build_report(matches, language, tex_map=tex_map)
    _log(report)
    show(report)
    return report


# ══════════════════════════════════════════════════════════════
#  MENUS
# ══════════════════════════════════════════════════════════════

def register_menus() -> None:
    """Adds "Texture Autoloader…" to the Content Browser's right-click
    menu and to Tools. Called from init_unreal.py at editor startup."""
    command = (f"import sys\n"
               f"sys.path.insert(0, {_THIS_DIR!r}) if {_THIS_DIR!r} not in sys.path else None\n"
               f"import texture_autoloader_unreal\n"
               f"texture_autoloader_unreal.run()\n")
    menus = unreal.ToolMenus.get()
    for menu_name, section in (("ContentBrowser.AssetContextMenu", "TextureAutoloader"),
                               ("LevelEditor.MainMenu.Tools", "TextureAutoloader")):
        menu = menus.extend_menu(menu_name)
        menu.add_section(section, TITLE)
        entry = unreal.ToolMenuEntry(name="TextureAutoloader.Run",
                                     type=unreal.MultiBlockType.MENU_ENTRY)
        entry.set_label(f"{TITLE}…")
        entry.set_tool_tip("Match textures from a folder to the selected meshes' Material Slots "
                           "and build their Material Instances.")
        entry.set_string_command(unreal.ToolMenuStringCommandType.PYTHON, "", command)
        menu.add_menu_entry(section, entry)
    menus.refresh_all_widgets()
