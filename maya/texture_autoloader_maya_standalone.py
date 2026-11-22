"""
Texture Autoloader — single-file build (maya)
================================================
Author: Manuel Castellani

Paste this whole file into Maya's Script Editor (Python tab) and run it.

GENERATED FILE — do not edit. It is produced from the modular build by
build_standalone.py:

    advanced/core/texture_autoloader_core.py   (shared logic)
  + advanced/maya/texture_autoloader_maya.py

Edit those and run `python build_standalone.py`. Editing this file directly
means the change is lost on the next build — and that is exactly how the
hand-copied versions of this file drifted away from the tested ones.

Everything below is the same code as the modular build, inlined: the shared
core first, then the maya front-end. The only changes are mechanical — no
sibling core/ folder to import, and the core's helpers that the front-end
overrides are prefixed with _core_ so both can coexist in one namespace.
"""

import os
import re
import json
import difflib
import logging
import logging.handlers
from typing import Optional, List, Dict, Tuple, Callable, Any
import html
import sys
from typing import Optional, List, Dict, Tuple, Any
import maya.cmds as cmds
import maya.OpenMayaUI as omui
# Compatibilidad Qt (PySide2 para Maya 2022-2024, PySide6 para Maya 2025+)
try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from shiboken6 import wrapInstance
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets
    from shiboken2 import wrapInstance


# ══════════════════════════════════════════════════════════════
#  SHARED CORE — inlined from advanced/core/texture_autoloader_core.py
# ══════════════════════════════════════════════════════════════



# ══════════════════════════════════════════════════════════════
#  i18n — tabla de traducciones compartida entre Maya y Blender
#  (así las dos UIs nunca quedan desincronizadas entre sí)
# ══════════════════════════════════════════════════════════════

DEFAULT_LANGUAGE = "en"

TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "en": {
        "app_title": "TEXTURE AUTOLOADER",
        "app_subtitle": "SUBSTANCE  ·  AUTO-LOADER",
        "footer": "Manuel Castellani  ·  Texture Autoloader",
        "section_manual": "MANUAL",
        "section_manual_desc": "Select an object and choose the texture files one by one.",
        "btn_manual_apply": "SELECT FILES AND APPLY",
        "section_autoloader": "AUTO-LOADER",
        "section_autoloader_desc": (
            "Scan a folder, match meshes to texture sets by name, and apply in "
            "batch. Double-click an object to reassign the whole set; double-click "
            "a channel to replace just that file. The checkbox enables/disables "
            "the channel."
        ),
        "recent_label": "RECENT",
        "recent_placeholder": "— Recent folders —",
        "btn_browse": "FOLDER",
        "btn_recursive": "RECURSIVE",
        "no_folder_selected": "No folder selected",
        "sensitivity_label": "SENSITIVITY",
        "sensitivity_tooltip": "Higher = stricter.",
        "match_by_label": "MATCH BY",
        "match_by_object_name": "OBJECT NAME",
        "match_by_material_id": "MATERIAL ID",
        "match_mode_info_object_name": (
            "Compares the object's name (no prefixes or LOD suffix) against the "
            "texture set. Doesn't require the mesh to have a material assigned."
        ),
        "match_mode_info_material_id": (
            "Compares the material already assigned to the mesh against the "
            "texture set. Falls back to the object's name if it has no material "
            "of its own."
        ),
        "btn_smart_match": "◉  SMART MATCH",
        "preview_label": "PREVIEW  (double-click = reassign / replace)",
        "btn_remove_selected": "REMOVE SELECTED",
        "btn_apply_all": "▶  APPLY TO ALL MATCHES",
        "no_match": "NO MATCH",
        "udim_tag": "  (UDIM)",
        "overridden_tag": "  (manually replaced)",
        "match_status": "{matched} / {total} objects matched",
        "msg_select_object": "Select an object first.",
        "msg_select_meshes": "Select one or more meshes first.",
        "msg_load_folder_first": "Load a texture folder first.",
        "msg_run_smart_match_first": "Run Smart Match first.",
        "msg_select_to_remove": "Select one or more objects in the preview to remove them.",
        "msg_folder_missing": "Folder no longer exists: {folder}",
        "scan_info": "{sets} set(s)    ·    {files} texture(s) found",
        "dialog_existing_materials_title": "Existing materials",
        "dialog_existing_materials_body": (
            "{count} object(s) already have a material from this tool assigned. "
            "The old network will be replaced before wiring the new one.\n\n"
            "Continue?"
        ),
        "dialog_reassign_title": "Reassign texture set",
        "dialog_reassign_none": "— Unassigned —",
        "progress_title": "Auto-Loader",
        "progress_applying": "Applying textures...",
        "progress_cancel": "Cancel",
        "progress_label": "Applying: {obj}  ({current}/{total})",
        "done_title": "Auto-Loader  ·  Done",
        "done_body_applied": "Applied",
        "done_body_skipped": "Skipped",
        "select_folder_dialog": "Select texture folder",
        "select_files_dialog": "Select Substance textures",
        "lang_button": "ES",
        "lang_button_tooltip": "Switch UI language to Spanish",
        # ── Report ──
        "report_title": "TEXTURE AUTOLOADER — REPORT",
        "report_title_preview": "TEXTURE AUTOLOADER — PREVIEW",
        "report_no_set": "no texture set matched",
        "report_no_match": "no match",
        "report_error": "error",
        "report_reason_disabled": "disabled in the preview",
        "report_reason_displacement_off": (
            "not wired, displacement is opt-in (enable_displacement_wiring)"),
        "report_reason_no_target": "{target} has no input for this channel",
        "report_reason_udim_unsupported": "UDIM isn't supported here yet",
        "report_reason_not_wired": "not wired",
        "report_reason_duplicate": "ignored, another {map_id} file is used",
        "report_reason_unknown": "not used",
        "report_status_cancelled": "not applied (batch cancelled)",
        "report_status_no_channels": "not applied (all channels disabled)",
        "report_unused_sets": "Texture sets with no object: {sets}",
        "report_summary": (
            "{applied}/{total} object(s) applied  ·  {ok} ✔  ·  {fail} ✘  ·  {skip} –"),
        "done_body_report_hint": "Full report under “Show Details…” and in the Script Editor.",
        "btn_show_report": "SHOW LAST REPORT",
        "report_in_text_editor": "Full report in the Text Editor: “{name}”",
        # ── Settings: naming presets ──
        "section_settings": "SETTINGS",
        "naming_preset_label": "NAMING PRESET",
        "naming_preset_tooltip": (
            "Suffix convention used to recognize each map. Add your own under "
            "\"naming_presets\" in texture_autoloader_config.json."),
        "preset_default": "Default (config file)",
        # ── Blender tooltips ──
        #  Blender freezes an operator's bl_description when the addon is
        #  registered, so these are served through each operator's
        #  description() classmethod to follow the panel's language.
        "tip_toggle_language": "Switch the panel between English and Spanish",
        "tip_browse_folder": "Pick the folder with the textures exported from Substance",
        "tip_select_recent": "Load this folder again",
        "tip_scan_folder": "Scan the selected folder for texture sets",
        "tip_smart_match": "Match the selected mesh objects to the scanned texture sets",
        "tip_toggle_channel": "Enable or disable this map for this object",
        "tip_remove_match": "Remove this object from the batch without deleting "
                            "anything in the scene",
        "tip_reassign_match": "Use this texture set for the object instead",
        "tip_open_reassign_menu": "Choose another texture set for this object",
        "tip_apply_all": "Wire a Principled BSDF for every matched object in the batch",
        "tip_show_report": "Show the ✔/✘ report of the last run",
        "tip_manual_apply": "Pick texture files by hand and apply them to the active object",
        # ── Settings: render engine (Maya) ──
        "render_engine_label": "RENDER ENGINE",
        "render_engine_title": "Render engine",
        "render_engine_tooltip": (
            "Shader created for each object. Redshift and V-Ray need their plugin loaded."),
        "msg_engine_plugin_not_loaded": (
            "{engine} needs the '{plugin}' plugin, which isn't loaded.\n\nLoad it now?"),
        "msg_engine_plugin_load_failed": "Could not load '{plugin}': {error}",
        "report_reason_missing_attr": "{target} has no '{attr}' attribute (other renderer version?)",
        # ── Unreal ──
        "report_reason_missing_param": "{target} has no texture parameter '{param}'",
        "msg_select_meshes_unreal": (
            "Select one or more Static Meshes or Skeletal Meshes in the Content Browser first."),
        "msg_apply_question": "Create / update the Material Instances and assign them?",
    },
    "es": {
        "app_title": "TEXTURE AUTOLOADER",
        "app_subtitle": "SUBSTANCE   ·   AUTO-LOADER",
        "footer": "Manuel Castellani  ·  Texture Autoloader",
        "section_manual": "MANUAL",
        "section_manual_desc": "Seleccioná un objeto y elegí los archivos de textura individualmente.",
        "btn_manual_apply": "SELECCIONAR ARCHIVOS  Y  APLICAR",
        "section_autoloader": "AUTO-LOADER",
        "section_autoloader_desc": (
            "Escaneá una carpeta, empareja meshes por nombre y aplicá en batch. "
            "Doble click en un objeto reasigna el set completo; doble click en un "
            "canal reemplaza sólo ese archivo. El checkbox activa/desactiva el "
            "canal."
        ),
        "recent_label": "RECIENTES",
        "recent_placeholder": "— Carpetas recientes —",
        "btn_browse": "CARPETA",
        "btn_recursive": "RECURSIVO",
        "no_folder_selected": "Ninguna carpeta seleccionada",
        "sensitivity_label": "SENSIBILIDAD",
        "sensitivity_tooltip": "Más alto = más estricto.",
        "match_by_label": "MATCHEAR POR",
        "match_by_object_name": "NOMBRE DE OBJETO",
        "match_by_material_id": "MATERIAL ID",
        "match_mode_info_object_name": (
            "Compara el nombre del objeto (sin prefijos ni LOD) contra el set de "
            "texturas. No necesita que el mesh tenga un material asignado."
        ),
        "match_mode_info_material_id": (
            "Compara el material ya asignado al mesh contra el set de texturas. "
            "Si no tiene material propio, usa el nombre del objeto como respaldo."
        ),
        "btn_smart_match": "◉   SMART MATCH",
        "preview_label": "PREVIEW  (doble click = reasignar / reemplazar)",
        "btn_remove_selected": "QUITAR SELECCIONADOS",
        "btn_apply_all": "▶  APLICAR A TODOS LOS MATCHES",
        "no_match": "SIN COINCIDENCIA",
        "udim_tag": "  (UDIM)",
        "overridden_tag": "  (reemplazado a mano)",
        "match_status": "{matched} / {total} objetos emparejados",
        "msg_select_object": "Seleccioná un objeto primero.",
        "msg_select_meshes": "Seleccioná uno o más meshes primero.",
        "msg_load_folder_first": "Cargá una carpeta de texturas primero.",
        "msg_run_smart_match_first": "Ejecutá Smart Match primero.",
        "msg_select_to_remove": "Seleccioná uno o más objetos del preview para quitarlos.",
        "msg_folder_missing": "La carpeta ya no existe: {folder}",
        "scan_info": "{sets} set(s)    ·    {files} textura(s) encontradas",
        "dialog_existing_materials_title": "Materiales existentes",
        "dialog_existing_materials_body": (
            "{count} objeto(s) ya tienen un material de esta herramienta asignado. "
            "Se va a reemplazar la red vieja antes de crear la nueva.\n\n"
            "¿Continuar?"
        ),
        "dialog_reassign_title": "Reasignar set de texturas",
        "dialog_reassign_none": "— Sin asignar —",
        "progress_title": "Auto-Loader",
        "progress_applying": "Aplicando texturas...",
        "progress_cancel": "Cancelar",
        "progress_label": "Aplicando: {obj}  ({current}/{total})",
        "done_title": "Auto-Loader  ·  Completado",
        "done_body_applied": "Aplicados",
        "done_body_skipped": "Omitidos",
        "select_folder_dialog": "Seleccionar carpeta de texturas",
        "select_files_dialog": "Seleccionar Texturas de Substance",
        "lang_button": "EN",
        "lang_button_tooltip": "Cambiar el idioma de la interfaz a inglés",
        # ── Reporte ──
        "report_title": "TEXTURE AUTOLOADER — REPORTE",
        "report_title_preview": "TEXTURE AUTOLOADER — VISTA PREVIA",
        "report_no_set": "ningún set de texturas coincide",
        "report_no_match": "sin match",
        "report_error": "error",
        "report_reason_disabled": "desactivado en el preview",
        "report_reason_displacement_off": (
            "no se cablea, el displacement es opcional (enable_displacement_wiring)"),
        "report_reason_no_target": "{target} no tiene un input para este canal",
        "report_reason_udim_unsupported": "UDIM todavía no está soportado acá",
        "report_reason_not_wired": "no se cableó",
        "report_reason_duplicate": "ignorado, se usa otro archivo de {map_id}",
        "report_reason_unknown": "no se usó",
        "report_status_cancelled": "no se aplicó (se canceló el batch)",
        "report_status_no_channels": "no se aplicó (todos los canales desactivados)",
        "report_unused_sets": "Sets de texturas sin objeto: {sets}",
        "report_summary": (
            "{applied}/{total} objeto(s) aplicados  ·  {ok} ✔  ·  {fail} ✘  ·  {skip} –"),
        "done_body_report_hint": "Reporte completo en “Show Details…” y en el Script Editor.",
        "btn_show_report": "VER ÚLTIMO REPORTE",
        "report_in_text_editor": "Reporte completo en el Text Editor: “{name}”",
        # ── Configuración: presets de nombres ──
        "section_settings": "CONFIGURACIÓN",
        "naming_preset_label": "PRESET DE NOMBRES",
        "naming_preset_tooltip": (
            "Convención de sufijos para reconocer cada mapa. Sumá la tuya en "
            "\"naming_presets\" dentro de texture_autoloader_config.json."),
        "preset_default": "Por defecto (archivo de config)",
        # ── Tooltips de Blender ──
        #  Blender congela el bl_description del operator al registrar el
        #  addon, así que estos se sirven desde el classmethod description()
        #  de cada operator para que sigan el idioma del panel.
        "tip_toggle_language": "Cambiar el panel entre inglés y español",
        "tip_browse_folder": "Elegir la carpeta con las texturas exportadas de Substance",
        "tip_select_recent": "Volver a cargar esta carpeta",
        "tip_scan_folder": "Escanear la carpeta elegida buscando sets de texturas",
        "tip_smart_match": "Emparejar los meshes seleccionados con los sets escaneados",
        "tip_toggle_channel": "Activar o desactivar este mapa para este objeto",
        "tip_remove_match": "Quitar este objeto del batch, sin borrar nada de la escena",
        "tip_reassign_match": "Usar este set de texturas para el objeto",
        "tip_open_reassign_menu": "Elegir otro set de texturas para este objeto",
        "tip_apply_all": "Cablear un Principled BSDF para cada objeto emparejado del batch",
        "tip_show_report": "Ver el reporte ✔/✘ de la última corrida",
        "tip_manual_apply": "Elegir archivos de textura a mano y aplicarlos al objeto activo",
        # ── Configuración: motor de render (Maya) ──
        "render_engine_label": "MOTOR DE RENDER",
        "render_engine_title": "Motor de render",
        "render_engine_tooltip": (
            "Shader que se crea para cada objeto. Redshift y V-Ray necesitan su plugin cargado."),
        "msg_engine_plugin_not_loaded": (
            "{engine} necesita el plugin '{plugin}', que no está cargado.\n\n¿Cargarlo ahora?"),
        "msg_engine_plugin_load_failed": "No se pudo cargar '{plugin}': {error}",
        "report_reason_missing_attr": "{target} no tiene el atributo '{attr}' (¿otra versión del renderer?)",
        # ── Unreal ──
        "report_reason_missing_param": "{target} no tiene el parámetro de textura '{param}'",
        "msg_select_meshes_unreal": (
            "Seleccioná primero uno o más Static Meshes o Skeletal Meshes en el Content Browser."),
        "msg_apply_question": "¿Crear / actualizar los Material Instances y asignarlos?",
    },
}


def tr(language: str, key: str, **kwargs) -> str:
    """Devuelve el string traducido para `key` en `language`, con fallback al
    idioma por defecto y, en último caso, a la propia key (nunca revienta
    por una traducción faltante). `**kwargs` permite placeholders tipo
    "{count}" con `str.format`."""
    lang_table = TRANSLATIONS.get(language, TRANSLATIONS[DEFAULT_LANGUAGE])
    text = lang_table.get(key, TRANSLATIONS[DEFAULT_LANGUAGE].get(key, key))
    return text.format(**kwargs) if kwargs else text


def apply_text_overrides(overrides: Dict[str, Dict[str, str]]) -> None:
    """Lets a front-end replace strings that describe ITS own interaction.

    The table above is shared so the two UIs never drift apart on anything
    that is genuinely the same, but a few strings aren't: the Auto-Loader
    description tells you to double-click a row, which is the Qt tree in Maya
    and does not exist in Blender's panel. Each front-end calls this once at
    import with the wording that matches what the user is actually looking
    at. Each DCC runs in its own Python process, so patching the table in
    place is safe."""
    for language, strings in overrides.items():
        if language in TRANSLATIONS:
            TRANSLATIONS[language].update(strings)


def other_language(language: str) -> str:
    """El otro idioma disponible — usado para rotular el botón de idioma
    con la bandera/etiqueta del idioma AL QUE SE VA A CAMBIAR, no del
    actual (por eso el botón dice "ES" cuando la UI está en inglés)."""
    return "es" if language == "en" else "en"


# ══════════════════════════════════════════════════════════════
#  ARCHIVOS DE SOPORTE — config / state / log
#  Cada front-end (Maya, Blender) resuelve su propio `app_dir` (la
#  carpeta donde vive SU script) y se lo pasa a estas funciones. El
#  core nunca decide sólo esa carpeta: eso es lo que lo mantiene testeable
#  sin tocar disco fuera de un directorio temporal y reusable entre
#  aplicaciones que corren en procesos de Python completamente separados.
# ══════════════════════════════════════════════════════════════

CONFIG_FILENAME = "texture_autoloader_config.json"
STATE_FILENAME = "texture_autoloader_state.json"
LOG_FILENAME = "texture_autoloader.log"

DEFAULT_CONFIG: Dict[str, Any] = {
    "mesh_prefixes": ["SM_", "SK_", "M_", "T_", "MI_", "FX_"],
    "match_threshold": 0.60,
    # Default matching mode. "object_name" compares the normalized object
    # name against the texture set (as always). "material_id" compares
    # the name of the material ALREADY ASSIGNED to the mesh (if it has a
    # real one) — useful when the studio's Substance export convention
    # names Texture Sets after the material (Skin, Metal, Cloth) instead
    # of the scene object's name. If the object has no material of its
    # own yet, it automatically falls back to matching by object name —
    # it's never left unmatched just for lacking a material.
    "match_mode": "object_name",
    "language": DEFAULT_LANGUAGE,
    "texture_extensions": [".png", ".jpg", ".jpeg", ".tga", ".tiff",
                            ".tif", ".exr", ".hdr", ".bmp"],
    # Set this to false in texture_autoloader_config.json if your naming
    # convention produces UDIM false positives (e.g. you keep several
    # resolutions of the same map in the same folder).
    "enable_udim_detection": True,
    # Displacement DEFORMS the actual render geometry (unlike bump, which
    # is a pure shading trick). Wiring a height/displacement map blindly,
    # without a hand-tuned displacement scale or mesh subdivision, leaves
    # the object looking "bloated". Off by default — the map is detected
    # and reported, but not wired, until this is turned on deliberately
    # and the scale is tuned by hand on the generated displacement node.
    "enable_displacement_wiring": False,
    # Broad list used ONLY to strip the map-type suffix from the asset
    # name when grouping files in scan_texture_folder.
    "suffix_strip_list": [
        "basecolor", "base_color", "albedo", "diffuse", "diff", "color", "col",
        "normal", "norm", "nrm", "nml",
        "roughness", "rough", "rgh",
        "metallic", "metalness", "metal", "met",
        "ambientocclusion", "ambient_occlusion", "mixed_ao", "occlusion", "occ", "ao",
        "emissive", "emission", "emit",
        "height", "disp", "displacement",
        "opacity", "alpha", "mask",
    ],
    # Order matters: evaluated in sequence, the first type whose substring
    # matches a file claims it. "raw" = True forces a non-color-managed
    # (linear/raw) colorspace for that map.
    "map_types": [
        {"id": "baseColor", "match": ["basecolor", "base_color", "_color", "_diff", "_albedo"],
         "color_space": "sRGB", "raw": False},
        {"id": "roughness", "match": ["_roughness", "_rough"],
         "color_space": "Raw", "raw": True},
        {"id": "metallic", "match": ["_metallic", "_metal"],
         "color_space": "Raw", "raw": True},
        {"id": "normal", "match": ["_normal", "_norm", "_nrm"],
         "color_space": "Raw", "raw": True},
        {"id": "emission", "match": ["_emission", "_emissive", "_emit"],
         "color_space": "sRGB", "raw": False},
        {"id": "ao", "match": ["_ao", "_ambientocclusion", "_mixed_ao", "_occlusion"],
         "color_space": "Raw", "raw": True},
        {"id": "displacement", "match": ["_displacement", "_disp", "_height"],
         "color_space": "Raw", "raw": True},
        {"id": "opacity", "match": ["_opacity", "_alpha", "_mask"],
         "color_space": "Raw", "raw": True},
    ],
    # Naming presets: named conventions to pick from in the UI instead of
    # editing map_types by hand. "default" always exists and IS the
    # map_types / suffix_strip_list above (a config customized the old way
    # keeps working as-is). In a preset, each channel lists "suffixes":
    # what the file name ENDS with, before resolution/UDIM tags — "BC"
    # matches Rock_BC.png, Rock_BC_4k.png and Rock_BC.1001.png, but not
    # Car_Rim_BC... as roughness just because it contains "_R". Color
    # space / raw are optional (sensible defaults per channel).
    "naming_preset": "default",
    # The example also keeps Substance's standard names, so picking it for a
    # regular export never turns BaseColor / Normal / Roughness into ✘.
    "naming_presets": {
        "short_suffixes": {
            "label": "Short suffixes (_BC _N _R _M _AO _E _H _O) + standard names",
            "map_types": [
                {"id": "baseColor", "suffixes": ["BC", "D", "BaseColor", "Base_Color", "Albedo",
                                                 "Diffuse"]},
                {"id": "normal", "suffixes": ["N", "NRM", "Normal"]},
                {"id": "roughness", "suffixes": ["R", "Rough", "Roughness"]},
                {"id": "metallic", "suffixes": ["M", "Metal", "Metallic", "Metalness"]},
                {"id": "ao", "suffixes": ["AO", "AmbientOcclusion", "Occlusion"]},
                {"id": "emission", "suffixes": ["E", "Emissive", "Emission"]},
                {"id": "displacement", "suffixes": ["H", "Height", "Disp", "Displacement"]},
                {"id": "opacity", "suffixes": ["O", "Opacity", "Alpha"]},
            ],
        },
    },
}


def deep_merge_defaults(loaded: Dict[str, Any], defaults: Dict[str, Any]) -> Dict[str, Any]:
    """Fills in keys missing from `loaded` with the ones from `defaults`
    (a partial or old-version config never breaks the tool)."""
    merged = dict(defaults)
    merged.update({k: v for k, v in loaded.items() if k in defaults})
    return merged


def load_config(app_dir: str, warn_fn: Optional[Callable[[str], None]] = None,
                defaults: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """`defaults` lets a front-end add keys of its own (e.g. Maya's render
    engine, Unreal's master material) on top of DEFAULT_CONFIG without the
    core — or the other front-ends' config files — having to know them."""
    defaults = defaults or DEFAULT_CONFIG
    path = os.path.join(app_dir, CONFIG_FILENAME)
    if not os.path.exists(path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(defaults, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
        return dict(defaults)
    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        return deep_merge_defaults(loaded, defaults)
    except Exception as e:
        if warn_fn:
            warn_fn(f"[TextureAutoloader] Could not read {path} ({e}) — using default config.")
        return dict(defaults)


# ══════════════════════════════════════════════════════════════
#  NAMING PRESETS — convenciones de sufijos con nombre, elegibles
#  desde la UI (ver "naming_presets" en DEFAULT_CONFIG).
# ══════════════════════════════════════════════════════════════

DEFAULT_PRESET_ID = "default"

# Color space / raw per channel, for presets that only list suffixes.
_MAP_TYPE_DEFAULTS: Dict[str, Dict[str, Any]] = {
    mt["id"]: {"color_space": mt["color_space"], "raw": mt["raw"]}
    for mt in DEFAULT_CONFIG["map_types"]
}


def list_naming_presets(config: Dict[str, Any],
                        language: str = DEFAULT_LANGUAGE) -> List[Tuple[str, str]]:
    """[(preset_id, label)], "default" first."""
    presets = [(DEFAULT_PRESET_ID, tr(language, "preset_default"))]
    for preset_id, preset in (config.get("naming_presets") or {}).items():
        if preset_id != DEFAULT_PRESET_ID and isinstance(preset, dict):
            presets.append((preset_id, preset.get("label") or preset_id))
    return presets


def normalize_map_types(map_types: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fills in what a hand-written preset may leave out: color space and
    raw (per-channel defaults), and empty "match"/"suffixes" lists."""
    normalized = []
    for mt in map_types:
        full = dict(_MAP_TYPE_DEFAULTS.get(mt["id"], {"color_space": "Raw", "raw": True}))
        full.update({"match": [], "suffixes": []})
        full.update(mt)
        normalized.append(full)
    return normalized


def apply_naming_preset(config: Dict[str, Any], preset_id: Optional[str],
                        warn_fn: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Copy of `config` whose map_types / suffix_strip_list come from the
    chosen preset — the rest of the pipeline (scan, match, apply) only
    ever sees a regular config. Unknown preset -> default, with a warning."""
    effective = dict(config)
    preset_id = preset_id or DEFAULT_PRESET_ID
    preset = (config.get("naming_presets") or {}).get(preset_id)
    if preset_id != DEFAULT_PRESET_ID and not isinstance(preset, dict):
        if warn_fn:
            warn_fn(f"[TextureAutoloader] Unknown naming preset '{preset_id}' — using the default.")
        preset_id, preset = DEFAULT_PRESET_ID, None
    effective["naming_preset"] = preset_id
    if preset_id == DEFAULT_PRESET_ID or not preset.get("map_types"):
        effective["map_types"] = normalize_map_types(config["map_types"])
        return effective

    map_types = normalize_map_types(preset["map_types"])
    effective["map_types"] = map_types
    effective["suffix_strip_list"] = preset.get("suffix_strip_list") or sorted({
        token.strip("_-.")
        for mt in map_types for token in mt["suffixes"] + mt["match"]
        if token.strip("_-.")})
    return effective


def state_path(app_dir: str) -> str:
    return os.path.join(app_dir, STATE_FILENAME)


def load_state(app_dir: str) -> Dict[str, Any]:
    """Personal session state (last folder used, threshold, match mode,
    language, etc.) — deliberately separate from config.json, so a
    personal preference never mixes with the studio's naming convention,
    which usually does make sense to share between artists."""
    path = state_path(app_dir)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(app_dir: str, state: Dict[str, Any]) -> None:
    try:
        with open(state_path(app_dir), "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
#  LOGGING — leaves a persistent, on-disk trail of what got applied
#  and when (texture_autoloader.log, next to config/state). Best-effort:
#  if it can't write to disk (permissions, a dead network drive), the
#  tool keeps working, just without that file trail.
# ══════════════════════════════════════════════════════════════

_logger_instances: Dict[str, "logging.Logger"] = {}


def get_logger(app_dir: str) -> "logging.Logger":
    """Returns (creating if needed) a rotating-file logger scoped to
    `app_dir`. Keyed by app_dir so the Maya and Blender front-ends —
    which normally live in different folders and, more importantly, run
    in entirely separate Python processes — never share or clobber each
    other's log file even if this module were ever imported twice in the
    same interpreter."""
    if app_dir in _logger_instances:
        return _logger_instances[app_dir]

    logger_name = f"TextureAutoloader.{abs(hash(app_dir))}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    try:
        log_path = os.path.join(app_dir, LOG_FILENAME)
        # delay=True: el archivo se crea recién con el primer mensaje, no al
        # crear el handler — así un app_dir que nunca loguea nada no queda
        # con un .log vacío (y los loggers de dos app_dir distintos no
        # dejan rastro el uno en la carpeta del otro).
        handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8", delay=True)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        logger.addHandler(handler)
    except Exception:
        pass  # no file logging, but the tool doesn't fall over because of it

    _logger_instances[app_dir] = logger
    return logger


# ══════════════════════════════════════════════════════════════
#  DEPENDENCIA OPCIONAL (rapidfuzz)
# ══════════════════════════════════════════════════════════════

def ensure_rapidfuzz() -> Tuple[Optional[Any], bool]:
    """
    Tries to import rapidfuzz. If it isn't installed, the internal
    difflib-based fallback is used instead — no attempt is made to
    install it.

    Earlier versions of this tool (as "Arnold Node Wrangler" v4.0) tried
    a silent background `pip install rapidfuzz` the first time they ran.
    That was removed: on a locked-down studio network or under strict
    security policy, a pipeline tool making an unrequested network call
    (even to PyPI) is a reasonable reason to get rejected by TD/IT, and
    the artist never saw it coming because it happened silently. If you
    want rapidfuzz's more accurate matching, install it yourself once:
        "<path to mayapy or Blender's python>" -m pip install rapidfuzz
    Without it, difflib does the same job with somewhat less precision
    on long/typo-heavy names — it is never a blocker.
    """
    try:
        from rapidfuzz import fuzz
        return fuzz, True
    except ImportError:
        return None, False


_FUZZ, HAS_RAPIDFUZZ = ensure_rapidfuzz()


# ══════════════════════════════════════════════════════════════
#  PURE STRING / MATCHING LOGIC — no DCC calls anywhere below
# ══════════════════════════════════════════════════════════════

_EXTS = set(DEFAULT_CONFIG["texture_extensions"])

# El separador incluye el punto porque Substance y Mari exportan los tiles
# UDIM como "Wall_BaseColor.1001.png": sin el punto, cada tile quedaba
# agrupado como un set distinto y el UDIM nunca llegaba a colapsarse.
_TRAILING_MOD = re.compile(
    r'[._\-](opengl|directx|dx|gl|tangent|world|object|space|'
    r'1k|2k|4k|8k|hi|lo|hd|sd|udim|\d{4})$', re.I)

# Bounded to real UDIM tile numbers (1001-1999 = up to 10x10 tiles,
# covers virtually any production case). A wider range (up to 9999) used
# to catch resolution suffixes like _2048/_4096/_8192 and confuse them
# with UDIM tiles, breaking the render (see _RESOLUTION_DENYLIST).
_UDIM_RE = re.compile(r'^(?P<prefix>.*)(?P<sep>[._-])(?P<tile>1[0-9]{3})$')

# Numeric resolution suffixes that are NOT UDIM tiles even though they
# fall in the range above (e.g. two exports "_BaseColor_1024" and
# "_BaseColor_2048" in the same folder). If two files of the same map
# type differ only in one of these numbers, they're treated as
# duplicates, not as UDIM tiles.
_RESOLUTION_DENYLIST = {512, 1024, 2048, 4096, 8192, 16384}


def _strip_trailing_modifiers(stem: str) -> str:
    prev = None
    while prev != stem:
        prev = stem
        stem = _TRAILING_MOD.sub('', stem)
    return stem


def _split_tex_name(filename: str, suffix_strip_list: List[str]) -> Tuple[str, bool]:
    """(asset base name, whether a known map-type suffix was stripped)."""
    stem = _strip_trailing_modifiers(os.path.splitext(filename)[0])
    for sfx in sorted(suffix_strip_list, key=len, reverse=True):
        pattern = re.compile(rf'[_\-]{re.escape(sfx)}$', re.I)
        if pattern.search(stem):
            return pattern.sub('', stem).strip('-_'), True
    return stem.strip('-_'), False


def tex_base_name(filename: str, suffix_strip_list: List[str]) -> str:
    """Strips extension, modifiers, and map-type suffix -> the asset's base name."""
    return _split_tex_name(filename, suffix_strip_list)[0]


def _owning_set(base: str, set_names: List[str]) -> Optional[str]:
    """The longest known set name that `base` starts with, followed by a
    separator ("Rock" for "Rock_Curvature"), or None."""
    lowered = base.lower()
    owners = [s for s in set_names
              if lowered.startswith(s.lower() + "_") or lowered.startswith(s.lower() + "-")]
    return max(owners, key=len) if owners else None


def mesh_base_name(obj: str, mesh_prefixes: List[str]) -> str:
    """Logical mesh name: no studio prefix, no LOD, no trailing index."""
    n = obj.split("|")[-1]  # Maya long-name safe; harmless no-op for Blender names
    for p in mesh_prefixes:
        if n.upper().startswith(p.upper()):
            n = n[len(p):]
            break
    n = re.sub(r'Shape$', '', n)
    n = re.sub(r'_LOD\d$', '', n)
    n = re.sub(r'_[A-Z]$', '', n)
    n = re.sub(r'_\d+$', '', n)
    return n


# "txa" is this tool's own Blender material suffix (M_<name>_TXA): without it,
# re-running Smart Match in Material ID mode compared "Rock_TXA" instead of
# "Rock" against the texture sets.
_MATERIAL_SUFFIX_RE = re.compile(r'[_]?(mat|material|shader|sg|txa)$', re.I)


def material_base_name(material: str, mesh_prefixes: List[str]) -> str:
    """Logical material name for comparing against texture sets: strips
    studio prefixes (the same ones as mesh_prefixes, since a material
    sometimes inherits the asset's prefix, e.g. "M_Character_Skin") and
    typical shader suffixes ("_MAT", "_Material", "_Shader", "_SG") when
    present."""
    n = material
    for p in mesh_prefixes:
        if n.upper().startswith(p.upper()):
            n = n[len(p):]
            break
    prev = None
    while prev != n:
        prev = n
        n = _MATERIAL_SUFFIX_RE.sub('', n)
    return n.strip('-_')


_WORD_SEP_RE = re.compile(r'[._\-\s]+')

# Scores for the two kinds of evidence in similarity(). Full-word containment
# is strong evidence (an artist's naming convention), a bare substring is weak.
_WORD_MATCH_SCORE = 0.90
_SUBSTRING_FLOOR = 0.60
_SUBSTRING_RANGE = 0.30


def _flat_name(name: str) -> str:
    return _WORD_SEP_RE.sub('', name).lower()


def _name_words(name: str) -> set:
    return {w for w in _WORD_SEP_RE.split(name.lower()) if w}


def _fuzzy_ratio(a: str, b: str) -> float:
    if HAS_RAPIDFUZZ:
        return _FUZZ.WRatio(a, b) / 100.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def similarity(a: str, b: str) -> float:
    """
    0..1 similarity between two names, tolerant of typos.

    The number is shown as confidence in the UI, so the kinds of evidence are
    kept apart instead of collapsing into one flat bonus:

      - same name ignoring separators and case -> 1.0
      - every WORD of one name is a word of the other ("Cabeza" vs
        "Modelado2_Cabeza", "Hero" vs "SK_Hero_Body") -> at least 0.90, since
        that is how artists actually name texture sets
      - one name merely CONTAINS the other ("Boca" inside
        "Modelado2_TornilloBoca") -> trusted only in proportion to how much of
        the longer name it covers, never above 0.90

    This used to give a flat 0.85 to anything in a substring relationship (and
    rapidfuzz's partial ratio inflates those pairs to 0.90 on its own), so a
    wrong match looked as confident as a right one, two candidates tied, and
    the sensitivity slider had no effect between those values. Everything that
    is neither of the above still falls back to the fuzzy ratio, which is what
    catches typos ("brazos" vs "Braxos").
    """
    flat_a, flat_b = _flat_name(a), _flat_name(b)
    if not flat_a or not flat_b:
        return 0.0
    if flat_a == flat_b:
        return 1.0

    score = _fuzzy_ratio(flat_a, flat_b)
    words_a, words_b = _name_words(a), _name_words(b)
    if words_a and words_b and (words_a <= words_b or words_b <= words_a):
        return max(score, _WORD_MATCH_SCORE)
    if flat_a in flat_b or flat_b in flat_a:
        short, long = sorted((flat_a, flat_b), key=len)
        return min(score, _SUBSTRING_FLOOR + _SUBSTRING_RANGE * (len(short) / len(long)))
    return score


def scan_texture_folder(folder: str, suffix_strip_list: List[str],
                         extensions: Optional[set] = None,
                         recursive: bool = False) -> Dict[str, List[str]]:
    """Returns { tex_base: [filepath, filepath, ...] }.

    A file whose map-type suffix isn't in `suffix_strip_list`
    ("Rock_Curvature.png") joins the longest known set its name starts
    with ("Rock") instead of becoming a texture set of its own — that way
    it shows up as "no match" in that set's report, next to the maps that
    did get wired, rather than as a phantom set nobody asked for."""
    exts = extensions or _EXTS
    result: Dict[str, List[str]] = {}
    unknown_suffix: List[Tuple[str, str]] = []
    walker = os.walk(folder) if recursive else [(folder, [], os.listdir(folder))]
    for root, _dirs, files in walker:
        for fname in files:
            if os.path.splitext(fname)[1].lower() not in exts:
                continue
            base, known = _split_tex_name(fname, suffix_strip_list)
            path = os.path.join(root, fname)
            if known:
                result.setdefault(base, []).append(path)
            else:
                unknown_suffix.append((base, path))
    for base, path in unknown_suffix:
        owner = _owning_set(base, list(result))
        result.setdefault(owner or base, []).append(path)
    return result


def compute_matches(obj_names: List[str], tex_bases: List[str],
                     threshold: float) -> List[Tuple[str, Optional[str], float]]:
    """
    Pairs each logical object name with the best tex_base by similarity.

    Ties are broken deterministically: fewer extra words first (so "Cabeza"
    prefers "Modelado2_Cabeza" over "Modelado2_CabezaExtra"), then shorter
    name, then alphabetical. Picking the first candidate instead meant the
    winner depended on the order the folder happened to list the files in.
    """
    results = []
    for obj_base in obj_names:
        ranked = sorted(
            ((similarity(obj_base, tb), len(_name_words(tb)), len(tb), tb.lower(), tb)
             for tb in tex_bases),
            key=lambda c: (-c[0], c[1], c[2], c[3]))
        best_score, best_base = (ranked[0][0], ranked[0][4]) if ranked else (0.0, None)
        results.append((obj_base, best_base if best_score >= threshold else None, best_score))
    return results


MAX_RECENT_FOLDERS = 5


def push_recent_folder(recent: List[str], folder: str) -> List[str]:
    """Moves `folder` to the front of the recent-folders list (no
    duplicates), trimming to the max allowed."""
    updated = [folder] + [f for f in recent if f != folder]
    return updated[:MAX_RECENT_FOLDERS]


def classify_map_type(file_path: str, map_types: List[Dict[str, Any]]) -> Optional[str]:
    """Map type id of a file, or None.

    1. "suffixes" (naming presets): what the name ENDS with, once the
       resolution/UDIM/API tags are stripped ("Rock_BC_4k.1001.png" ends
       with "BC"). The longest matching suffix wins, so "Base_Color"
       beats "Color".
    2. "match" (the default convention): substring anywhere in the file
       name, first type in the list wins — the original behavior."""
    fname = os.path.basename(file_path)
    stem = _strip_trailing_modifiers(os.path.splitext(fname)[0]).lower()
    best_id, best_len = None, 0
    for mt in map_types:
        for sfx in mt.get("suffixes", []):
            s = sfx.lower()
            if len(s) > best_len and (stem == s or re.search(rf'[._\-]{re.escape(s)}$', stem)):
                best_id, best_len = mt["id"], len(s)
    if best_id:
        return best_id

    fname_lower = fname.lower()
    for mt in map_types:
        if any(s.lower() in fname_lower for s in mt.get("match", [])):
            return mt["id"]
    return None


def bucket_files_by_type(file_paths: List[str],
                          map_types: List[Dict[str, Any]]
                          ) -> Tuple[Dict[str, List[str]], List[str]]:
    """Groups files by map type (see classify_map_type). Returns
    (buckets, files_with_no_recognized_type)."""
    buckets: Dict[str, List[str]] = {}
    unmatched: List[str] = []
    for file_path in file_paths:
        matched_id = classify_map_type(file_path, map_types)
        if matched_id:
            buckets.setdefault(matched_id, []).append(file_path)
        else:
            unmatched.append(file_path)
    return buckets, unmatched


def collapse_udim_set(file_paths: List[str],
                       warn_fn: Optional[Callable[[str], None]] = None) -> Tuple[str, bool]:
    """
    If several files of the same map type differ only by a 4-digit tile
    number (1001-1999), collapses them into a single path with a <UDIM>
    token. If no recognizable UDIM pattern is found (or the number is a
    known resolution suffix), returns the first file and warns via
    `warn_fn` if provided.
    """
    if len(file_paths) <= 1:
        return file_paths[0], False

    groups: Dict[Tuple[str, str, str, str], List[str]] = {}
    ungrouped: List[str] = []
    for fp in file_paths:
        d, fname = os.path.split(fp)
        stem, ext = os.path.splitext(fname)
        m = _UDIM_RE.match(stem)
        if not m or int(m.group("tile")) in _RESOLUTION_DENYLIST:
            ungrouped.append(fp)
            continue
        key = (d, m.group("prefix"), m.group("sep"), ext)
        groups.setdefault(key, []).append(fp)

    udim_groups = {k: v for k, v in groups.items() if len(v) >= 2}
    if not udim_groups:
        if warn_fn:
            warn_fn(
                f"[TextureAutoloader] {len(file_paths)} files match the same map "
                f"type and don't look like UDIM tiles — using only: "
                f"{os.path.basename(file_paths[0])}")
        return file_paths[0], False

    key = max(udim_groups, key=lambda k: len(udim_groups[k]))
    d, prefix, sep, ext = key
    representative = os.path.join(d, f"{prefix}{sep}<UDIM>{ext}")
    return representative, True


def get_udim_tile_files(representative_path: str, all_files: List[str]) -> Dict[int, str]:
    """Given a "<UDIM>"-templated representative path and the full list of
    files that were bucketed into the same map type, returns
    {tile_number: filepath} for every real tile on disk. Used by the
    Blender front-end to register each tile of a UDIM image (Blender's
    tiled-image API needs the explicit tile numbers, unlike Maya/Arnold
    which resolves the <UDIM> token by convention at render time)."""
    d, fname = os.path.split(representative_path)
    prefix, _sep, rest = fname.partition("<UDIM>")
    ext = os.path.splitext(rest)[1]
    tiles: Dict[int, str] = {}
    for fp in all_files:
        fd, ffname = os.path.split(fp)
        if fd != d or not ffname.startswith(prefix) or not ffname.endswith(ext):
            continue
        stem = ffname[len(prefix):-len(ext)] if ext else ffname[len(prefix):]
        digits = re.match(r'^(\d{4})', stem)
        if digits:
            tiles[int(digits.group(1))] = fp
    return tiles


def resolve_channel_files(buckets: Dict[str, List[str]], config: Dict[str, Any],
                           warn_fn: Optional[Callable[[str], None]] = None
                           ) -> Dict[str, Tuple[str, bool]]:
    """For each map type with files, resolves the representative file
    (collapsing UDIM tiles when enabled). Returns {map_id: (filepath, is_udim)}."""
    resolved: Dict[str, Tuple[str, bool]] = {}
    for map_id, files in buckets.items():
        if config.get("enable_udim_detection", True):
            representative, is_udim = collapse_udim_set(files, warn_fn=warn_fn)
        else:
            representative, is_udim = files[0], False
            if len(files) > 1 and warn_fn:
                warn_fn(
                    f"[TextureAutoloader] {len(files)} files match the map "
                    f"'{map_id}' — UDIM detection is disabled, using only: "
                    f"{os.path.basename(files[0])}")
        resolved[map_id] = (representative, is_udim)
    return resolved


def build_match_entry(obj: str, tex_base: Optional[str], score: float,
                       tex_map: Dict[str, List[str]], config: Dict[str, Any],
                       warn_fn: Optional[Callable[[str], None]] = None
                       ) -> Dict[str, Any]:
    """Builds the per-object data structure used by the channel tree/list
    in the UI: which map types were detected for the matched set, with
    which file, and whether they're enabled (all enabled by default).

    Also keeps what did NOT make it into a channel, for the report:
    `unrecognized` (files of the set whose map type isn't known) and, per
    channel, `ignored` (other files of the same type that lost to the one
    in use — e.g. a second resolution of the same map)."""
    files = tex_map.get(tex_base, []) if tex_base else []
    entry = build_entry_from_files(obj, tex_base, files, config, warn_fn=warn_fn)
    entry["score"] = score
    return entry


def build_entry_from_files(obj: str, tex_base: Optional[str], file_paths: List[str],
                            config: Dict[str, Any],
                            warn_fn: Optional[Callable[[str], None]] = None
                            ) -> Dict[str, Any]:
    """Same structure as build_match_entry, from an explicit file list —
    what the front-ends' manual mode (files picked by hand) uses so that it
    gets the same report as the Auto-Loader."""
    channels: Dict[str, Dict[str, Any]] = {}
    unrecognized: List[str] = []
    if file_paths:
        buckets, unrecognized = bucket_files_by_type(file_paths, config["map_types"])
        resolved = resolve_channel_files(buckets, config, warn_fn=warn_fn)
        for map_id, (filepath, is_udim) in resolved.items():
            typed_files = buckets[map_id]
            used = (set(get_udim_tile_files(filepath, typed_files).values())
                    if is_udim else {filepath})
            channels[map_id] = {
                "enabled": True,
                "file": filepath,
                "is_udim": is_udim,
                "overridden": False,
                "ignored": [f for f in typed_files if f not in used],
            }
    return {
        "obj": obj,
        "tex_base": tex_base,
        "score": 1.0 if tex_base else 0.0,
        "channels": channels,
        "unrecognized": list(unrecognized),
    }


def _core_match_objects_to_textures(object_entries: List[Tuple[str, Optional[str]]],
                               tex_map: Dict[str, List[str]],
                               config: Dict[str, Any],
                               match_mode: str = "object_name",
                               warn_fn: Optional[Callable[[str], None]] = None
                               ) -> List[Dict[str, Any]]:
    """
    DCC-agnostic matching. `object_entries` is a list of
    (object_name, assigned_material_name_or_None) tuples — it is the
    CALLER's job (the Maya or Blender wrapper) to figure out which
    objects are meshes and what material (if any) is really assigned to
    each one; this function never touches a scene.

    match_mode:
      - "object_name" (default): compares the object's normalized name
        (see mesh_base_name) against the texture set, as always.
      - "material_id": compares the name of the material ALREADY
        ASSIGNED to the mesh (normalized with material_base_name), if it
        has a real one (the caller is expected to have already filtered
        out default/placeholder materials — e.g. Maya's lambert1). If
        the entry's material is None, falls back to object_name for that
        object in particular — it's never left unmatched just for
        lacking a material.
    """
    mesh_prefixes = config["mesh_prefixes"]

    named_entries: List[Tuple[str, str]] = []
    for name, assigned_material in object_entries:
        base = None
        if match_mode == "material_id" and assigned_material:
            base = material_base_name(assigned_material, mesh_prefixes)
        if not base:
            base = mesh_base_name(name, mesh_prefixes)
        named_entries.append((name, base))

    return match_names_to_textures(named_entries, tex_map, config, warn_fn=warn_fn)


def match_names_to_textures(named_entries: List[Tuple[str, Any]],
                             tex_map: Dict[str, List[str]],
                             config: Dict[str, Any],
                             warn_fn: Optional[Callable[[str], None]] = None
                             ) -> List[Dict[str, Any]]:
    """Lower-level matching for front-ends that decide by themselves which
    name stands for each thing to match: `named_entries` is a list of
    (key, logical_name) pairs, and each resulting entry carries "obj" =
    key. The Unreal port uses it to match Material Slots (one mesh can
    need several texture sets), not whole objects.

    logical_name can also be a list of candidate names, most specific
    first: the best score over all of them wins, and on a tie the earlier
    candidate keeps it. A slot "Body" on SM_Hero tries "Hero_Body" before
    "Body", so a folder with Hero_Body and Villain_Body maps it right."""
    tex_bases = list(tex_map.keys())
    threshold = config["match_threshold"]
    entries = []
    for key, names in named_entries:
        candidates = [names] if isinstance(names, str) else list(names)
        best_base, best_score = None, 0.0
        for _name, tex_base, score in compute_matches(candidates, tex_bases, 0.0):
            if tex_base is not None and score > best_score:
                best_base, best_score = tex_base, score
        if best_score < threshold:
            best_base = None
        entries.append(build_match_entry(key, best_base, best_score, tex_map, config,
                                         warn_fn=warn_fn))
    return entries


def new_apply_result(material: Optional[str] = None) -> Dict[str, Any]:
    """What a front-end's apply function returns for one object, so the
    report can say what happened to each channel:

      wired   {map_id: file}               — connected / bound
      skipped {map_id: {"reason": ..., **}} — deliberately not used;
              reason is a "report_reason_<reason>" translation key and the
              other keys are its placeholders
      failed  {map_id: "error message"}    — tried and failed
    """
    return {"material": material, "wired": {}, "skipped": {}, "failed": {}}


def _core_apply_auto_textures(matches: List[Dict[str, Any]],
                         config: Dict[str, Any],
                         apply_one_fn: Callable[[str, str, Dict[str, str]], Optional[Dict[str, Any]]],
                         progress_cb: Optional[Callable[[int, int, str], bool]] = None,
                         log_fn: Optional[Callable[[str], None]] = None
                         ) -> Tuple[int, int]:
    """
    For each matched object, applies only the enabled channels (respects
    the checkboxes/overrides from the UI). `apply_one_fn(obj, mat_basename,
    channel_files)` is supplied by the DCC wrapper and does the actual
    scene work (create the shader, wire the textures); if it returns a
    new_apply_result() dict, the report uses it. `progress_cb(i, total,
    obj)` may return True to cancel the batch partway through.

    Each match gets a "status" ("applied", "no_match", "no_channels",
    "error" or "cancelled") and, when applied, a "result". An exception
    while applying one object is recorded as that object's error and the
    batch moves on to the next one instead of aborting halfway.
    """
    applied = skipped = 0
    total = len(matches)
    for m in matches:
        m["status"] = "cancelled"
        m.pop("result", None)
        m.pop("error", None)
    for i, m in enumerate(matches):
        if progress_cb and progress_cb(i, total, m["obj"]):
            break
        if not m["tex_base"]:
            m["status"] = "no_match"
            skipped += 1
            continue
        channel_files = {mid: ch["file"] for mid, ch in m["channels"].items() if ch["enabled"]}
        if not channel_files:
            m["status"] = "no_channels"
            skipped += 1
            continue
        if log_fn:
            log_fn(f"[TextureAutoloader] Applying {len(channel_files)} channel(s) to: {m['obj']}")
        try:
            result = apply_one_fn(
                m["obj"], mesh_base_name(m["obj"], config["mesh_prefixes"]), channel_files)
        except Exception as e:
            m["status"] = "error"
            m["error"] = str(e) or e.__class__.__name__
            skipped += 1
            if log_fn:
                log_fn(f"[TextureAutoloader] ERROR applying {m['obj']}: {m['error']}")
            continue
        m["status"] = "applied"
        if isinstance(result, dict):
            m["result"] = result
        applied += 1
    if progress_cb:
        progress_cb(total, total, "")
    if log_fn:
        log_fn(
            f"[TextureAutoloader] Auto-Loader batch complete — {applied} object(s) applied, "
            f"{skipped} skipped out of {total} total.")
    return applied, skipped


# ══════════════════════════════════════════════════════════════
#  REPORT — texto plano post-ejecución (✔ / ✘ / –), compartido por
#  Maya, Blender y Unreal. Sin thumbnails a propósito: un reporte de
#  texto dice qué pasó con cada archivo sin sumar complejidad de UI.
# ══════════════════════════════════════════════════════════════

REPORT_OK = "✔"      # wired / bound
REPORT_FAIL = "✘"    # found but not used: no match, no target, error
REPORT_SKIP = "–"    # intentionally not used: disabled, opt-in, duplicate

# Skip reasons that are a deliberate choice (shown as "–", not as a
# failure). Anything else a front-end skips — e.g. a renderer or master
# material with no input for that channel — is something to fix, so ✘.
_INTENTIONAL_SKIP_REASONS = {"displacement_off"}


def _report_file_label(file_path: str, is_udim: bool = False) -> str:
    name = os.path.basename(file_path)
    return name + ("  (UDIM)" if is_udim and "<UDIM>" not in name else "")


def _reason_text(language: str, skipped: Any) -> str:
    if isinstance(skipped, dict):
        args = {k: v for k, v in skipped.items() if k != "reason"}
        return tr(language, f"report_reason_{skipped.get('reason', 'unknown')}", **args)
    return str(skipped)


def build_report(matches: List[Dict[str, Any]], language: str = DEFAULT_LANGUAGE,
                 tex_map: Optional[Dict[str, List[str]]] = None,
                 preview: bool = False) -> str:
    """Plain-text report of a batch, one block per object:

        SM_Rock  →  Rock  (95%)  ·  M_Rock_MAT
          ✔ Rock_BaseColor.png → baseColor
          – Rock_Height.png → displacement: not wired, displacement is opt-in
          ✘ no match: Rock_Curvature.png

    With preview=True (before applying) channels are listed as planned
    ("•") instead of ✔/✘. If `tex_map` is given, texture sets that no
    object used are listed at the end."""
    L = language
    lines = [tr(L, "report_title_preview" if preview else "report_title"), ""]
    counts = {"ok": 0, "fail": 0, "skip": 0}

    def add(symbol: str, text: str, kind: str) -> None:
        lines.append(f"    {symbol} {text}")
        counts[kind] += 1

    for m in matches:
        name = m["obj"].split("|")[-1]
        if not m.get("tex_base"):
            lines.append(f"{name}  →  {REPORT_FAIL} {tr(L, 'report_no_set')}")
            counts["fail"] += 1
            continue

        result = m.get("result") or {}
        header = f"{name}  →  {m['tex_base']}  ({m.get('score', 0.0):.0%})"
        if result.get("material"):
            header += f"  ·  {result['material']}"
        lines.append(header)

        status = m.get("status")
        if not preview and status in ("cancelled", "no_channels", "error"):
            if status == "error":
                add(REPORT_FAIL, f"{tr(L, 'report_error')}: {m.get('error', '')}", "fail")
            else:
                add(REPORT_SKIP, tr(L, f"report_status_{status}"), "skip")
            continue

        wired = result.get("wired", {})
        failed = result.get("failed", {})
        skipped = result.get("skipped", {})
        for map_id, ch in m["channels"].items():
            label = f"{_report_file_label(ch['file'], ch.get('is_udim', False))} → {map_id}"
            if not ch["enabled"]:
                add(REPORT_SKIP, f"{label}: {tr(L, 'report_reason_disabled')}", "skip")
            elif preview:
                lines.append(f"    • {label}")
            elif map_id in wired:
                add(REPORT_OK, label, "ok")
            elif map_id in failed:
                add(REPORT_FAIL, f"{label}: {tr(L, 'report_error')}: {failed[map_id]}", "fail")
            elif map_id in skipped:
                reason = skipped[map_id]
                intentional = (isinstance(reason, dict)
                               and reason.get("reason") in _INTENTIONAL_SKIP_REASONS)
                add(REPORT_SKIP if intentional else REPORT_FAIL,
                    f"{label}: {_reason_text(L, reason)}", "skip" if intentional else "fail")
            elif result:
                add(REPORT_FAIL, f"{label}: {tr(L, 'report_reason_not_wired')}", "fail")
            else:
                # The front-end didn't report per-channel results: all we
                # know is that the object was applied with these channels.
                add(REPORT_OK, label, "ok")
            for ignored in ch.get("ignored", []):
                add(REPORT_SKIP, f"{os.path.basename(ignored)}: "
                    f"{tr(L, 'report_reason_duplicate', map_id=map_id)}", "skip")
        for f in m.get("unrecognized", []):
            add(REPORT_FAIL, f"{tr(L, 'report_no_match')}: {os.path.basename(f)}", "fail")

    if tex_map:
        used = {m.get("tex_base") for m in matches}
        unused = [f"{name} ({len(files)})" for name, files in sorted(tex_map.items())
                  if name not in used]
        if unused:
            lines += ["", tr(L, "report_unused_sets", sets=", ".join(unused))]

    lines.append("")
    if preview:
        matched = sum(1 for m in matches if m.get("tex_base"))
        lines.append(tr(L, "match_status", matched=matched, total=len(matches)))
    else:
        applied = sum(1 for m in matches if m.get("status") == "applied")
        lines.append(tr(L, "report_summary", applied=applied, total=len(matches),
                        ok=counts["ok"], fail=counts["fail"], skip=counts["skip"]))
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
#  MAYA FRONT-END — inlined from advanced/maya/texture_autoloader_maya.py
# ══════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════
#  Dónde van config / state / log. Pegado en el Script Editor no hay
#  __file__, así que se usa la carpeta de preferencias del usuario de
#  Maya (un script pegado no tiene carpeta propia). Si en cambio este
#  archivo se importa como módulo, se usan los que estén a su lado.
# ══════════════════════════════════════════════════════════════

def _resolve_this_dir() -> str:
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        return os.path.join(cmds.internalVar(userAppDir=True), "TextureAutoloader")


# ══════════════════════════════════════════════════════════════
#  Bootstrap: hace importable el core compartido (carpeta hermana
#  "core/", ver la estructura del repo) sin depender de que el usuario
#  haya agregado nada a su Maya script path a mano.
#
#  __file__ sólo existe cuando este archivo se IMPORTA como módulo
#  (import texture_autoloader_maya as ta). Si en cambio pegás todo el
#  contenido del .py directo en el Script Editor y le das a Run, Maya
#  compila ese texto con el nombre falso "<maya console>" y __file__ no
#  se define nunca — de ahí el "NameError: name '__file__' is not
#  defined". Para que la herramienta funcione en los dos casos (import
#  correcto, o pegado directo en el Script Editor), _resolve_repo_dirs()
#  intenta __file__ primero y, si no existe, pide UNA vez por sesión la
#  carpeta TextureAutoloader/advanced con un file picker y se acuerda de
#  esa elección para el resto de la sesión de Maya.
# ══════════════════════════════════════════════════════════════


_MODULE_FILENAME = "texture_autoloader_maya.py"


def _find_module_dir(picked: str) -> Optional[str]:
    """La carpeta elegida en el diálogo tiene que ser la que contiene este
    archivo. Se aceptan también las equivocaciones fáciles — la raíz del
    build modular (advanced/ o dcc_mejoras/) o su carpeta core/ — porque
    elegir core/ "funcionaba" (el core se importaba igual) pero dejaba
    config/state/log guardados en la carpeta equivocada."""
    for candidate in (picked, os.path.join(picked, "maya"),
                      os.path.join(os.path.dirname(picked.rstrip("/\\")), "maya")):
        if os.path.isfile(os.path.join(candidate, _MODULE_FILENAME)):
            return os.path.normpath(candidate)
    return None


def _app_dir() -> str:
    """Carpeta donde vive ESTE script — es la que se le pasa al core para
    config.json/state.json/log, igual que en versiones anteriores
    ("junto al script")."""
    try:
        base = _resolve_this_dir()
    except RuntimeError:
        base = os.path.join(cmds.internalVar(userAppDir=True), "TextureAutoloader")
    try:
        os.makedirs(base, exist_ok=True)
    except Exception:
        base = os.path.expanduser("~")
    return base


def _warn(message: str) -> None:
    """Advierte en la consola de Maya Y deja constancia en
    texture_autoloader.log — para que una corrida desatendida deje
    rastro aunque nadie haya estado mirando la consola en el momento."""
    cmds.warning(message)
    try:
        get_logger(_app_dir()).warning(message)
    except Exception:
        pass


def _log_print(message: str) -> None:
    """Como print(), pero además registra el mensaje en
    texture_autoloader.log a nivel INFO."""
    print(message)
    try:
        get_logger(_app_dir()).info(message)
    except Exception:
        pass


if not HAS_RAPIDFUZZ:
    _warn(
        "[TextureAutoloader] rapidfuzz is not installed — using the internal "
        "difflib fallback for fuzzy matching. This is not an error: it only "
        "lowers precision a bit on very different-looking names.")


# ══════════════════════════════════════════════════════════════
#  MAYA / ARNOLD — WIRING
# ══════════════════════════════════════════════════════════════


_MAT_NAME_RE = re.compile(r'^M_.+_MAT\d*$')

# Nombres de materiales/shading groups "de fábrica" de Maya — no aportan
# información real para el matching por Material ID.
_DEFAULT_SHADERS = {"lambert1", "standardSurface1", "particleCloud1"}
_DEFAULT_SHADING_GROUPS = {"initialShadingGroup", "initialParticleSE"}


def create_texture_node(file_path: str, node_name_prefix: str) -> str:
    """Crea un nodo de archivo y su respectivo place2dTexture, configurando el mapeo UV."""
    place2d = cmds.shadingNode('place2dTexture', asUtility=True,
                                name=f"{node_name_prefix}_place2d")
    file_node = cmds.shadingNode('file', asTexture=True, isColorManaged=True,
                                  name=f"{node_name_prefix}_file")

    cmds.setAttr(f"{file_node}.fileTextureName", file_path, type="string")

    connections = ['coverage', 'translateFrame', 'rotateFrame', 'mirrorU', 'mirrorV',
                   'stagger', 'wrapU', 'wrapV', 'repeatUV', 'offset', 'rotateUV',
                   'noiseUV', 'vertexUvOne', 'vertexUvTwo', 'vertexUvThree',
                   'vertexCameraOne']
    for conn in connections:
        cmds.connectAttr(f"{place2d}.{conn}", f"{file_node}.{conn}", force=True)

    cmds.connectAttr(f"{place2d}.outUV", f"{file_node}.uvCoord")
    cmds.connectAttr(f"{place2d}.outUvFilterSize", f"{file_node}.uvFilterSize")
    return file_node


def apply_color_space(file_node: str, color_space: str, is_raw: bool = False) -> None:
    """Aplica configuraciones profesionales de Color Management al nodo."""
    try:
        if is_raw:
            cmds.setAttr(f"{file_node}.ignoreColorSpaceFileRules", True)
        cmds.setAttr(f"{file_node}.colorSpace", color_space, type="string")
    except Exception:
        _warn(f"No se pudo establecer el color space '{color_space}' en {file_node}.")


def _find_autoloader_shader(obj: str) -> Optional[str]:
    """Devuelve el nombre del shader M_..._MAT asignado al objeto, si existe
    (patrón propio de esta herramienta, usado para detectar y limpiar
    re-ejecuciones). Para detectar CUALQUIER material asignado, usar
    `_get_assigned_material_name`."""
    shapes = cmds.listRelatives(obj, shapes=True, fullPath=True) or [obj]
    for shp in shapes:
        sgs = cmds.listConnections(shp, type='shadingEngine') or []
        for sg in sgs:
            for shader in (cmds.listConnections(f"{sg}.surfaceShader") or []):
                if _MAT_NAME_RE.match(shader):
                    return shader
    return None


def has_autoloader_material(obj: str) -> bool:
    return _find_autoloader_shader(obj) is not None


def _get_assigned_material_name(obj: str) -> Optional[str]:
    """Devuelve el nombre del material (shader) actualmente asignado al
    objeto, sin importar quién lo puso ahí. Ignora los materiales por
    defecto de Maya (lambert1, etc.)."""
    shapes = cmds.listRelatives(obj, shapes=True, fullPath=True) or [obj]
    for shp in shapes:
        sgs = cmds.listConnections(shp, type='shadingEngine') or []
        for sg in sgs:
            if sg in _DEFAULT_SHADING_GROUPS:
                continue
            for shader in (cmds.listConnections(f"{sg}.surfaceShader") or []):
                if shader in _DEFAULT_SHADERS:
                    continue
                return shader
    return None


def _cleanup_existing_material(obj: str) -> int:
    """Si el objeto ya tiene un material generado por esta herramienta, lo
    borra junto con su historia de nodos antes de crear la red nueva."""
    shader = _find_autoloader_shader(obj)
    if not shader:
        return 0
    try:
        sgs = cmds.listConnections(f"{shader}.outColor", type='shadingEngine') or []
        history = cmds.listHistory(shader, pruneDagObjects=True) or []
        to_delete = (set(history) | {shader} | set(sgs)) - {
            'lambert1', 'initialShadingGroup', 'initialParticleSE'}
        removed = 0
        for node in to_delete:
            if cmds.objExists(node):
                try:
                    cmds.delete(node)
                    removed += 1
                except Exception:
                    pass
        if removed:
            get_logger(_app_dir()).info(
                f"[TextureAutoloader] Cleaned up {obj.split('|')[-1]}: "
                f"{removed} node(s) from the previous material removed before rewiring.")
        return removed
    except Exception as e:
        _warn(f"No se pudo limpiar el material anterior de {obj}: {e}")
        return 0


# ══════════════════════════════════════════════════════════════
#  MOTORES DE RENDER — una plantilla por motor: qué shader crear y a
#  qué input va cada canal. Agregar un motor = agregar una entrada acá;
#  el resto del cableado (nodos file, UDIM, color space, AO, reporte)
#  es el mismo para todos.
#
#  Por canal:
#    attr       input del shader al que llega el canal
#    out        salida del nodo file: "color" (outColor), "alpha"
#               (outAlpha) o "luminance" (outAlpha con alphaIsLuminance,
#               para inputs float con mapas sin canal alpha)
#    set        atributos del shader que se setean al cablear el canal
#    node, node_kw, node_in, node_out, node_set
#               nodo intermedio entre el file y el shader (normal map,
#               displacement): el file entra por node_in y node_out va a
#               `attr` — o, con
#    sg_attr    ...a ese atributo del shading group (displacement)
#    multiply_into
#               AO: se multiplica sobre el input de ese canal (baseColor)
#
#  Las entradas de Redshift y V-Ray siguen los nombres de nodos y
#  atributos documentados por cada renderer, pero no se pudieron probar
#  en la máquina de desarrollo (sólo tiene Arnold). Cada atributo se
#  verifica antes de conectar: si en tu versión del renderer un nombre no
#  existe, el canal sale como ✘ en el reporte en vez de romper el batch.
# ══════════════════════════════════════════════════════════════

ENGINE_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "arnold": {
        "label": "Arnold  ·  aiStandardSurface",
        "plugin": "mtoa",
        "shader": "aiStandardSurface",
        "channels": {
            "baseColor": {"attr": "baseColor", "out": "color"},
            "roughness": {"attr": "specularRoughness", "out": "luminance"},
            "metallic": {"attr": "metalness", "out": "luminance"},
            "emission": {"attr": "emissionColor", "out": "color", "set": {"emission": 1.0}},
            "opacity": {"attr": "opacity", "out": "color"},
            "normal": {"attr": "normalCamera", "node": "bump2d", "node_kw": {"asUtility": True},
                       "node_in": "bumpValue", "out": "alpha", "node_out": "outNormal",
                       "node_set": {"bumpInterp": 1}},  # 1 = tangent-space normals
            "displacement": {"node": "displacementShader", "node_kw": {"asShader": True},
                             "node_in": "displacement", "out": "luminance",
                             "node_out": "displacement", "sg_attr": "displacementShader"},
            "ao": {"multiply_into": "baseColor"},
        },
    },
    "redshift": {
        "label": "Redshift  ·  RedshiftStandardMaterial",
        "plugin": "redshift4maya",
        "shader": "RedshiftStandardMaterial",
        "channels": {
            "baseColor": {"attr": "base_color", "out": "color"},
            "roughness": {"attr": "refl_roughness", "out": "luminance"},
            "metallic": {"attr": "metalness", "out": "luminance"},
            "emission": {"attr": "emission_color", "out": "color", "set": {"emission_weight": 1.0}},
            "opacity": {"attr": "opacity_color", "out": "color"},
            "normal": {"attr": "bump_input", "node": "RedshiftBumpMap", "node_kw": {"asUtility": True},
                       "node_in": "input", "out": "color", "node_out": "out",
                       "node_set": {"inputType": 1}},  # 1 = tangent-space normal
            "displacement": {"node": "RedshiftDisplacement", "node_kw": {"asShader": True},
                             "node_in": "texMap", "out": "color",
                             "node_out": "out", "sg_attr": "displacementShader"},
            "ao": {"multiply_into": "baseColor"},
        },
    },
    "vray": {
        "label": "V-Ray  ·  VRayMtl",
        "plugin": "vrayformaya",
        "shader": "VRayMtl",
        # Metalness workflow: white reflection, GGX, glossiness read as roughness.
        "shader_set": {"reflectionColor": (1.0, 1.0, 1.0), "brdfType": 3, "useRoughness": 1},
        "channels": {
            "baseColor": {"attr": "color", "out": "color"},
            "roughness": {"attr": "reflectionGlossiness", "out": "luminance"},
            "metallic": {"attr": "metalness", "out": "luminance"},
            "emission": {"attr": "illumColor", "out": "color"},
            "opacity": {"attr": "opacityMap", "out": "color"},
            "normal": {"attr": "bumpMap", "out": "color",
                       "set": {"bumpMapType": 1}},  # 1 = normal map in tangent space
            "displacement": {"node": "displacementShader", "node_kw": {"asShader": True},
                             "node_in": "displacement", "out": "luminance",
                             "node_out": "displacement", "sg_attr": "displacementShader"},
            "ao": {"multiply_into": "baseColor"},
        },
    },
}

DEFAULT_ENGINE = "arnold"

# Config de disco de la versión de Maya: la del core + el motor por defecto.
MAYA_DEFAULT_CONFIG: Dict[str, Any] = dict(DEFAULT_CONFIG, render_engine=DEFAULT_ENGINE)


def _load_config() -> Dict[str, Any]:
    return load_config(_app_dir(), warn_fn=_warn, defaults=MAYA_DEFAULT_CONFIG)


def engine_plugin_loaded(engine: str) -> bool:
    try:
        return bool(cmds.pluginInfo(ENGINE_TEMPLATES[engine]["plugin"], query=True, loaded=True))
    except Exception:
        return False


def _has_attr(node: str, attr: str) -> bool:
    try:
        return bool(cmds.attributeQuery(attr, node=node, exists=True))
    except Exception:
        return False


def _set_attrs(node: str, values: Dict[str, Any]) -> None:
    for attr, value in values.items():
        if not _has_attr(node, attr):
            continue
        if isinstance(value, (tuple, list)):
            cmds.setAttr(f"{node}.{attr}", *value, type="double3")
        else:
            cmds.setAttr(f"{node}.{attr}", value)


def _connect_file(file_node: str, dest: str, out: str) -> None:
    if out == "luminance":
        cmds.setAttr(f"{file_node}.alphaIsLuminance", True)
    if out in ("alpha", "luminance"):
        try:
            cmds.connectAttr(f"{file_node}.outAlpha", dest, force=True)
        except Exception:
            cmds.connectAttr(f"{file_node}.outColorR", dest, force=True)
    else:
        cmds.connectAttr(f"{file_node}.outColor", dest, force=True)


def _wire_channel(engine: str, map_id: str, file_node: str, mat_name: str, sg_name: str,
                  stem: str) -> Optional[Dict[str, Any]]:
    """Cablea un nodo file ya creado según la plantilla del motor.
    Devuelve None si quedó cableado, o el motivo (para el reporte) si el
    motor no tiene dónde conectarlo."""
    template = ENGINE_TEMPLATES[engine]
    spec = template["channels"].get(map_id)
    if spec is None or "multiply_into" in spec:
        return {"reason": "no_target", "target": template["shader"]}

    source = None
    if "node" in spec:
        helper = cmds.shadingNode(spec["node"], name=f"{stem}_{spec['node']}", **spec["node_kw"])
        missing = [a for a in (spec["node_in"], spec["node_out"]) if not _has_attr(helper, a)]
        if missing:
            cmds.delete(helper)
            return {"reason": "missing_attr", "target": spec["node"], "attr": missing[0]}
        _set_attrs(helper, spec.get("node_set", {}))
        _connect_file(file_node, f"{helper}.{spec['node_in']}", spec["out"])
        if "sg_attr" in spec:
            cmds.connectAttr(f"{helper}.{spec['node_out']}", f"{sg_name}.{spec['sg_attr']}",
                             force=True)
            return None
        source = f"{helper}.{spec['node_out']}"

    if not _has_attr(mat_name, spec["attr"]):
        return {"reason": "missing_attr", "target": template["shader"], "attr": spec["attr"]}
    _set_attrs(mat_name, spec.get("set", {}))
    if source:
        cmds.connectAttr(source, f"{mat_name}.{spec['attr']}", force=True)
    else:
        _connect_file(file_node, f"{mat_name}.{spec['attr']}", spec["out"])
    return None


def get_selected_mesh() -> Optional[str]:
    selection = cmds.ls(selection=True)
    if not selection:
        _warn("No hay ningún objeto seleccionado.")
        return None
    return selection[0]


def load_textures_and_apply(config: Optional[Dict[str, Any]] = None,
                            language: str = DEFAULT_LANGUAGE,
                            engine: Optional[str] = None) -> Optional[str]:
    """Modo manual: aplica archivos elegidos a mano al objeto seleccionado.
    Devuelve el reporte ✔/✘ (o None si se canceló la selección)."""
    config = config or _load_config()
    selected_obj = get_selected_mesh()
    if not selected_obj:
        return None
    file_paths = cmds.fileDialog2(
        fileMode=4, dialogStyle=2,
        caption=tr(language, "select_files_dialog"),
        fileFilter="Images (*.png *.jpg *.jpeg *.tga *.exr *.tif *.tiff)"
    )
    if not file_paths:
        return None

    label = tex_base_name(os.path.basename(file_paths[0]), config["suffix_strip_list"])
    entry = build_entry_from_files(selected_obj, label, file_paths, config, warn_fn=_warn)
    channel_files = {mid: ch["file"] for mid, ch in entry["channels"].items()}
    cmds.undoInfo(openChunk=True)
    try:
        entry["result"] = process_textures(
            None, selected_obj, mat_basename=mesh_base_name(selected_obj, config["mesh_prefixes"]),
            config=config, channel_files=channel_files, engine=engine)
        entry["status"] = "applied"
    except Exception as e:
        entry["status"], entry["error"] = "error", str(e)
        _warn(f"[TextureAutoloader] {selected_obj}: {e}")
    finally:
        cmds.undoInfo(closeChunk=True)

    report = build_report([entry], language)
    _log_print(report)
    return report


def process_textures(file_paths: Optional[List[str]], selected_obj: str,
                      mat_basename: Optional[str] = None,
                      config: Optional[Dict[str, Any]] = None,
                      channel_files: Optional[Dict[str, str]] = None,
                      engine: Optional[str] = None) -> Dict[str, Any]:
    """
    Crea un shader NUEVO del motor elegido (ver ENGINE_TEMPLATES; por
    defecto el "render_engine" del config, Arnold), lo asigna al objeto y
    conecta las texturas por tipo de mapa. Si el objeto ya tenía un
    material generado por esta herramienta, lo limpia primero.

    Devuelve un new_apply_result(): qué canal quedó cableado, cuál
    se salteó y por qué, y cuál falló — de ahí sale el reporte ✔/✘.
    """
    config = config or _load_config()
    map_types = config["map_types"]
    engine = engine or config.get("render_engine", DEFAULT_ENGINE)
    if engine not in ENGINE_TEMPLATES:
        raise ValueError(f"unknown render engine '{engine}' "
                         f"(available: {', '.join(ENGINE_TEMPLATES)})")
    template = ENGINE_TEMPLATES[engine]
    if not engine_plugin_loaded(engine):
        raise RuntimeError(f"{template['label']} needs the '{template['plugin']}' plugin, "
                           f"which is not loaded")

    _cleanup_existing_material(selected_obj)

    name = f"M_{mat_basename}_MAT" if mat_basename else "M_Substance_01_MAT"
    mat_name = cmds.shadingNode(template["shader"], asShader=True, name=name)
    _set_attrs(mat_name, template.get("shader_set", {}))
    sg_name = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                         name=f"{mat_name}SG")
    cmds.connectAttr(f"{mat_name}.outColor", f"{sg_name}.surfaceShader", force=True)

    try:
        cmds.sets(selected_obj, forceElement=sg_name)
    except Exception as e:
        raise RuntimeError(f"could not assign the material to {selected_obj}: {e}")

    result = new_apply_result(material=mat_name)

    if channel_files is not None:
        resolved: Dict[str, Tuple[str, bool]] = {
            mid: (fp, "<UDIM>" in fp) for mid, fp in channel_files.items()}
        unmatched: List[str] = []
    else:
        buckets, unmatched = bucket_files_by_type(file_paths or [], map_types)
        resolved = resolve_channel_files(buckets, config, warn_fn=_warn)

    created_nodes: Dict[str, str] = {}
    skipped_displacement = 0
    for mt in map_types:
        if mt["id"] not in resolved:
            continue
        representative, is_udim = resolved[mt["id"]]

        if mt["id"] == "displacement" and not config.get("enable_displacement_wiring", False):
            skipped_displacement += 1
            result["skipped"]["displacement"] = {"reason": "displacement_off"}
            continue

        if mt["id"] != "ao" and mt["id"] not in template["channels"]:
            # Un map type agregado a mano en el config (algo que el README
            # invita a hacer) para el que este motor no tiene regla: se
            # reporta y NO se crea el nodo, en vez de dejar un file +
            # place2dTexture sueltos en la escena.
            result["skipped"][mt["id"]] = {"reason": "no_target",
                                           "target": template["shader"]}
            continue

        try:
            stem = os.path.splitext(os.path.basename(representative))[0]
            fn = create_texture_node(representative, f"{stem}_{mt['id']}")
            if is_udim:
                try:
                    cmds.setAttr(f"{fn}.uvTilingMode", 3)  # UDIM (Mari)
                except Exception:
                    pass
            apply_color_space(fn, mt["color_space"], is_raw=mt["raw"])
            if mt["id"] == "ao":
                created_nodes["ao"] = fn  # se multiplica sobre baseColor más abajo
                continue
            skip = _wire_channel(engine, mt["id"], fn, mat_name, sg_name, stem)
            if skip:
                result["skipped"][mt["id"]] = skip
                continue
            if mt["id"] == "baseColor":
                created_nodes["baseColor"] = fn
            result["wired"][mt["id"]] = representative
        except Exception as e:
            _warn(f"Error procesando mapa '{mt['id']}': {e}")
            result["failed"][mt["id"]] = str(e)

    # Post-proceso: AO × BaseColor (multiplyDivide: lo entienden los tres motores)
    if "ao" in created_nodes:
        target = template["channels"]["ao"]["multiply_into"]
        base_attr = template["channels"][target]["attr"]
        try:
            ao_node = created_nodes["ao"]
            mult = cmds.shadingNode('multiplyDivide', asUtility=True,
                                     name="AO_BaseColor_Multiply")
            if "baseColor" in created_nodes:
                bc = created_nodes["baseColor"]
                cmds.disconnectAttr(f"{bc}.outColor", f"{mat_name}.{base_attr}")
                cmds.connectAttr(f"{bc}.outColor", f"{mult}.input1", force=True)
            else:
                cmds.setAttr(f"{mult}.input1X", 1.0)
                cmds.setAttr(f"{mult}.input1Y", 1.0)
                cmds.setAttr(f"{mult}.input1Z", 1.0)
            cmds.connectAttr(f"{ao_node}.outColor", f"{mult}.input2", force=True)
            cmds.connectAttr(f"{mult}.output", f"{mat_name}.{base_attr}", force=True)
            result["wired"]["ao"] = resolved["ao"][0]
        except Exception as e:
            _warn(f"Error configurando multiplicador de AO: {e}")
            result["failed"]["ao"] = str(e)

    if skipped_displacement:
        _warn(
            f"[TextureAutoloader] {skipped_displacement} displacement/height map(s) "
            f"detected on {selected_obj.split('|')[-1]} but NOT wired (turn on "
            f"'enable_displacement_wiring' in texture_autoloader_config.json if you "
            f"want them — requires hand-tuning the displacementShader scale).")

    if unmatched:
        names = ", ".join(os.path.basename(f) for f in unmatched)
        _warn(
            f"[TextureAutoloader] {len(unmatched)} unrecognized file(s), NOT wired, "
            f"on {selected_obj.split('|')[-1]}: {names}")

    get_logger(_app_dir()).info(
        f"[TextureAutoloader] Material '{mat_name}' applied to {selected_obj.split('|')[-1]} "
        f"with {len(result['wired'])} channel(s) wired "
        f"({', '.join(sorted(result['wired'])) or 'none'}).")

    return result


# ── Auto-Loader: scan + match + apply ──────────────────────────

def scan_folder(folder: str, config: Dict[str, Any], recursive: bool = False) -> Dict[str, List[str]]:
    return scan_texture_folder(folder, config["suffix_strip_list"],
                                     set(config["texture_extensions"]), recursive)


def match_objects_to_textures(objects: List[str], tex_map: Dict[str, List[str]],
                               config: Dict[str, Any],
                               match_mode: str = "object_name") -> List[Dict[str, Any]]:
    """Maya-aware wrapper: filtra a meshes válidos y resuelve el material
    asignado a cada uno (si corresponde), y delega el matching puro al
    core compartido."""
    object_entries: List[Tuple[str, Optional[str]]] = []
    for obj in objects:
        sh = cmds.listRelatives(obj, shapes=True) or []
        if sh and cmds.nodeType(sh[0]) == "mesh":
            assigned = _get_assigned_material_name(obj) if match_mode == "material_id" else None
            object_entries.append((obj, assigned))
        else:
            _warn(f"[TextureAutoloader] '{obj}' no es un mesh — se omite del matching.")

    return _core_match_objects_to_textures(
        object_entries, tex_map, config, match_mode=match_mode, warn_fn=_warn)


def apply_auto_textures(matches: List[Dict[str, Any]],
                         config: Dict[str, Any],
                         progress_cb=None,
                         engine: Optional[str] = None) -> Tuple[int, int]:
    def _apply_one(obj: str, mat_basename: str, channel_files: Dict[str, str]) -> Dict[str, Any]:
        return process_textures(None, obj, mat_basename=mat_basename,
                                config=config, channel_files=channel_files, engine=engine)

    return _core_apply_auto_textures(
        matches, config, apply_one_fn=_apply_one, progress_cb=progress_cb, log_fn=_log_print)


# ══════════════════════════════════════════════════════════════
#  UI  —  PySide / Qt  (dark theme, bilingual EN/ES)
# ══════════════════════════════════════════════════════════════

def _maya_main_window() -> Optional["QtWidgets.QWidget"]:
    ptr = omui.MQtUtil.mainWindow()
    if ptr is None:
        return None
    return wrapInstance(int(ptr), QtWidgets.QWidget)


_STYLESHEET = """
/* ── Base ─────────────────────────────────────────────────── */
QDialog#TextureAutoloaderDialog,
QWidget#TextureAutoloaderRoot {
    background-color: #0E0F12;
    color: #ECEDF2;
    font-family: "Segoe UI", "Inter", "Helvetica Neue", sans-serif;
    font-size: 13px;
}

/* ── Header — gradiente índigo/violeta profundo ───────────── */
QFrame#Header {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 #12162A, stop:0.5 #1B2242, stop:1 #241B3D);
    border-top-left-radius: 14px;
    border-top-right-radius: 14px;
    border: none;
}
QFrame#HeaderAccent {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #22D3EE, stop:0.5 #8B5CF6, stop:1 #EC4899);
    max-height: 3px;
    min-height: 3px;
    border: none;
}
QLabel#HeaderTitle {
    color: #F5F6FA;
    font-size: 25px;
    font-weight: 800;
    letter-spacing: 4px;
    background: transparent;
}
QLabel#HeaderSubtitle {
    color: #9AA3F5;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 3px;
    background: transparent;
}
QPushButton#BtnLanguage {
    background-color: rgba(255,255,255,0.08);
    color: #ECEDF2;
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 12px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 4px 10px;
    max-height: 22px;
}
QPushButton#BtnLanguage:hover {
    background-color: rgba(255,255,255,0.16);
}

/* ── Cards ─────────────────────────────────────────────────── */
QFrame.Card {
    background-color: #16171D;
    border: 1px solid #24252E;
    border-radius: 14px;
}
QLabel.SectionTag {
    color: #22D3EE;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 2px;
    background: transparent;
}
QLabel.SectionTagAmber {
    color: #F5A623;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 2px;
    background: transparent;
}
QLabel.SectionDesc {
    color: #9297A8;
    font-size: 13px;
    background: transparent;
}
QLabel.MutedSmall {
    color: #6B7280;
    font-size: 12px;
    background: transparent;
}
QLabel.StatusInfo {
    color: #8B5CF6;
    font-size: 13px;
    font-weight: 600;
    background: transparent;
}
QLabel.FolderPath {
    color: #C7C9D6;
    font-size: 12px;
    background: #101116;
    border: 1px solid #24252E;
    border-radius: 8px;
    padding: 8px 12px;
}

/* ── Botones ───────────────────────────────────────────────── */
QPushButton {
    border: none;
    border-radius: 8px;
    padding: 10px 14px;
    font-weight: 700;
    font-size: 13px;
    letter-spacing: 1px;
    background-color: #21222B;
    color: #ECEDF2;
}
QPushButton:hover { background-color: #2A2C38; }
QPushButton:pressed { background-color: #191A21; }
QPushButton:disabled { color: #575A66; }

QPushButton#BtnApply {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #7C3AED, stop:1 #22D3EE);
    color: #0B0C10;
    padding: 15px;
    font-size: 15px;
    letter-spacing: 3px;
}
QPushButton#BtnApply:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #8B4CFB, stop:1 #33E4FF); }

QPushButton#BtnMatch {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1F2937, stop:1 #312047);
    border: 1px solid #3A3D4D;
    color: #C4B5FD;
    padding: 13px;
    font-size: 14px;
    letter-spacing: 2px;
}
QPushButton#BtnManual {
    background-color: #1B1C24;
    border: 1px solid #2A2C38;
    color: #ECEDF2;
    padding: 13px;
    font-size: 14px;
    letter-spacing: 2px;
}
QPushButton#BtnBrowse {
    background-color: #21222B;
    padding: 8px 16px;
    font-size: 12px;
}
QPushButton#BtnRecursive {
    background-color: #21222B;
    padding: 8px 14px;
    font-size: 12px;
}
QPushButton#BtnRecursive:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #22D3EE, stop:1 #8B5CF6);
    color: #0B0C10;
}
QPushButton#BtnMatchMode {
    background-color: #21222B;
    padding: 8px 14px;
    font-size: 12px;
}
QPushButton#BtnMatchMode:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #EC4899, stop:1 #F5A623);
    color: #0B0C10;
}

/* ── Slider de sensibilidad ────────────────────────────────── */
QSlider::groove:horizontal {
    height: 6px;
    background: #21222B;
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #22D3EE, stop:1 #8B5CF6);
    border-radius: 3px;
}
QSlider::handle:horizontal {
    width: 14px;
    height: 14px;
    margin: -4px 0;
    border-radius: 7px;
    background: #ECEDF2;
    border: 2px solid #8B5CF6;
}

/* ── Árbol de matches / canales ───────────────────────────────── */
QTreeWidget {
    background-color: #101116;
    border: 1px solid #24252E;
    border-radius: 10px;
    color: #C7C9D6;
    font-family: "Consolas", "Menlo", monospace;
    font-size: 13px;
    padding: 6px;
    outline: 0;
}
QTreeWidget::item { padding: 5px 4px; }
QTreeWidget::item:hover { background-color: #1B1C24; }
QTreeWidget::item:selected { background-color: #24263A; color: #C4B5FD; }
QTreeWidget::branch:hover { background-color: #1B1C24; }

QScrollBar:vertical { background: #101116; width: 10px; }
QScrollBar::handle:vertical { background: #2A2C38; border-radius: 5px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #3A3D4D; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }

/* ── Combo de carpetas recientes ──────────────────────────────── */
QComboBox {
    background-color: #21222B;
    border: 1px solid #2A2C38;
    border-radius: 8px;
    padding: 6px 8px;
    color: #ECEDF2;
    font-size: 12px;
}
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background-color: #1B1C24;
    color: #ECEDF2;
    border: 1px solid #2A2C38;
    selection-background-color: #24263A;
    selection-color: #C4B5FD;
    outline: 0;
}
QLineEdit { background: transparent; color: #ECEDF2; border: none; }

/* ── Diálogos hijos ────────────────────────────────────────── */
QMessageBox, QProgressDialog, QInputDialog, QFileDialog {
    background-color: #16171D;
    color: #ECEDF2;
}
QProgressBar {
    background-color: #21222B;
    border: none;
    border-radius: 6px;
    text-align: center;
    color: #ECEDF2;
    height: 16px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #22D3EE, stop:1 #8B5CF6);
    border-radius: 6px;
}

QLabel#Footer {
    color: #575A66;
    font-size: 11px;
    letter-spacing: 1px;
    background: transparent;
}
"""


class TextureAutoloaderDialog(QtWidgets.QDialog):

    _instance: Optional["TextureAutoloaderDialog"] = None

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent or _maya_main_window())
        self.setObjectName("TextureAutoloaderDialog")
        self.setWindowTitle("Texture Autoloader")
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Window)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        self.setMinimumWidth(600)
        self._apply_initial_size()

        self.config: Dict[str, Any] = _load_config()
        self.state: Dict[str, Any] = load_state(_app_dir())
        self.folder: Optional[str] = None
        self.tex_map: Dict[str, List[str]] = {}
        self.matches: List[Dict[str, Any]] = []
        self.match_mode: str = "object_name"
        self.language: str = self.state.get(
            "language", self.config.get("language", DEFAULT_LANGUAGE))
        self.naming_preset: str = apply_naming_preset(
            self.config,
            self.state.get("last_naming_preset",
                           self.config.get("naming_preset", DEFAULT_PRESET_ID)),
            warn_fn=_warn)["naming_preset"]
        engine = self.state.get("last_render_engine",
                                self.config.get("render_engine", DEFAULT_ENGINE))
        self.render_engine: str = engine if engine in ENGINE_TEMPLATES else DEFAULT_ENGINE

        self._build_ui()
        self.setStyleSheet(_STYLESHEET)

        self.btn_recursive.setChecked(bool(self.state.get("last_recursive", False)))
        recent = self.state.get("recent_folders") or (
            [self.state["last_folder"]] if self.state.get("last_folder") else [])
        self._refresh_recent_combo([f for f in recent if os.path.isdir(f)])

        default_threshold = self.config.get("match_threshold", 0.60)
        threshold_pct = int(round(self.state.get("last_threshold", default_threshold) * 100))
        self.sld_threshold.setValue(threshold_pct)

        default_mode = self.config.get("match_mode", "object_name")
        self.match_mode = self.state.get("last_match_mode", default_mode)
        if self.match_mode == "material_id":
            self.btn_match_material.setChecked(True)
        else:
            self.btn_match_object.setChecked(True)

        self._retranslate_ui()

    # ── Tamaño de la ventana ──────────────────────────────────

    #  Alto "cómodo" (todo visible sin scrollear) y mínimo real. El mínimo
    #  tiene que entrar en una pantalla de 1080p con barra de tareas: antes
    #  era 1100 px y la ventana abría en 1220, así que en un monitor de 1080
    #  (o en un portátil) no se podía encoger y el botón de aplicar quedaba
    #  abajo, fuera de la pantalla. El contenido ya vive en un QScrollArea,
    #  así que achicar sólo agrega scroll, no esconde nada.
    PREFERRED_HEIGHT = 1220
    MINIMUM_HEIGHT = 560

    def _available_height(self) -> int:
        """Alto usable de la pantalla donde está la ventana (sin la barra de
        tareas). Si Qt no lo puede decir, asume 1080p."""
        try:
            screen = self.screen() if hasattr(self, "screen") else None
            if screen is None:
                app = QtWidgets.QApplication.instance()
                screen = app.primaryScreen() if app else None
            if screen is not None:
                return screen.availableGeometry().height()
        except Exception:
            pass
        return 1032

    def _apply_initial_size(self) -> None:
        available = self._available_height()
        self.setMinimumHeight(min(self.MINIMUM_HEIGHT, available))
        self.resize(640, max(min(self.PREFERRED_HEIGHT, available - 48),
                             min(self.MINIMUM_HEIGHT, available)))

    # ── i18n ──────────────────────────────────────────────────

    def _t(self, key: str, **kwargs) -> str:
        return tr(self.language, key, **kwargs)

    def _cfg(self) -> Dict[str, Any]:
        """Config efectivo: el de disco + el preset de nombres elegido
        (y el threshold del slider, que vive en self.config)."""
        return apply_naming_preset(self.config, self.naming_preset)

    def _on_toggle_language(self) -> None:
        self.language = other_language(self.language)
        self.state["language"] = self.language
        self._persist_state()
        self._retranslate_ui()

    def _retranslate_ui(self) -> None:
        """Vuelve a poner todos los textos visibles según self.language.
        Se llama una vez en __init__ y cada vez que se toca el botón de
        idioma — no hace falta reconstruir ningún widget."""
        L = self.language
        self.setWindowTitle(self._t("app_title").title())
        self.lbl_header_title.setText(self._t("app_title"))
        self.lbl_header_subtitle.setText(self._t("app_subtitle"))
        self.btn_language.setText(tr(other_language(L), "lang_button"))
        self.btn_language.setToolTip(self._t("lang_button_tooltip"))

        self.lbl_settings_tag.setText("◇  " + self._t("section_settings"))
        self.lbl_render_engine.setText(self._t("render_engine_label"))
        self.combo_render_engine.setToolTip(self._t("render_engine_tooltip"))
        self.lbl_naming_preset.setText(self._t("naming_preset_label"))
        self.combo_naming_preset.setToolTip(self._t("naming_preset_tooltip"))
        self._refresh_naming_preset_combo()

        self.lbl_manual_tag.setText("◆  " + self._t("section_manual"))
        self.lbl_manual_desc.setText(self._t("section_manual_desc"))
        self.btn_manual_apply.setText(self._t("btn_manual_apply"))

        self.lbl_auto_tag.setText("✦  " + self._t("section_autoloader"))
        self.lbl_auto_desc.setText(self._t("section_autoloader_desc"))
        self.lbl_recent.setText(self._t("recent_label"))
        self.combo_recent.setItemText(0, self._t("recent_placeholder"))
        self.btn_browse.setText(self._t("btn_browse"))
        self.btn_recursive.setText(
            self._t("btn_recursive") + ("  ✓" if self.btn_recursive.isChecked() else ""))
        if not self.folder:
            self.lbl_folder.setText(self._t("no_folder_selected"))

        self.lbl_sensitivity.setText(self._t("sensitivity_label"))
        self.sld_threshold.setToolTip(self._t("sensitivity_tooltip"))
        self.lbl_match_by.setText(self._t("match_by_label"))
        self.btn_match_object.setText(self._t("match_by_object_name"))
        self.btn_match_material.setText(self._t("match_by_material_id"))
        self._update_match_mode_info()

        self.btn_match.setText(self._t("btn_smart_match"))
        self.lbl_preview.setText(self._t("preview_label"))
        self.btn_remove.setText(self._t("btn_remove_selected"))
        self.btn_apply.setText(self._t("btn_apply_all"))
        self.lbl_footer.setText(self._t("footer"))
        self._refresh_match_status()

    # ── Construcción de la UI ────────────────────────────────

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        root.addWidget(self._build_header())

        content = QtWidgets.QWidget()
        content.setObjectName("TextureAutoloaderRoot")
        c_layout = QtWidgets.QVBoxLayout(content)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setSpacing(14)

        c_layout.addWidget(self._build_settings_card())
        c_layout.addWidget(self._build_manual_card())
        c_layout.addWidget(self._build_autoloader_card(), 1)
        c_layout.addWidget(self._build_footer())

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    def _build_header(self) -> QtWidgets.QWidget:
        header = QtWidgets.QFrame()
        header.setObjectName("Header")
        header.setFixedHeight(112)

        outer = QtWidgets.QVBoxLayout(header)
        outer.setContentsMargins(0, 10, 12, 16)
        outer.setSpacing(6)

        lang_row = QtWidgets.QHBoxLayout()
        lang_row.addStretch(1)
        self.btn_language = QtWidgets.QPushButton("ES")
        self.btn_language.setObjectName("BtnLanguage")
        self.btn_language.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_language.setFixedWidth(40)
        self.btn_language.clicked.connect(self._on_toggle_language)
        lang_row.addWidget(self.btn_language)
        outer.addLayout(lang_row)

        self.lbl_header_title = QtWidgets.QLabel("TEXTURE AUTOLOADER")
        self.lbl_header_title.setObjectName("HeaderTitle")
        self.lbl_header_title.setAlignment(QtCore.Qt.AlignCenter)

        self.lbl_header_subtitle = QtWidgets.QLabel("SUBSTANCE   ·   AUTO-LOADER")
        self.lbl_header_subtitle.setObjectName("HeaderSubtitle")
        self.lbl_header_subtitle.setAlignment(QtCore.Qt.AlignCenter)

        accent = QtWidgets.QFrame()
        accent.setObjectName("HeaderAccent")
        accent.setFixedHeight(3)

        outer.addWidget(self.lbl_header_title)
        outer.addWidget(self.lbl_header_subtitle)
        outer.addWidget(accent)

        return header

    def _settings_row(self, lay: QtWidgets.QVBoxLayout, combo: QtWidgets.QComboBox
                      ) -> QtWidgets.QLabel:
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        label = QtWidgets.QLabel()
        label.setProperty("class", "MutedSmall")
        label.setStyleSheet("letter-spacing:2px; font-weight:700;")
        label.setFixedWidth(170)
        combo.setEditable(False)
        combo.setCursor(QtCore.Qt.PointingHandCursor)
        row.addWidget(label)
        row.addWidget(combo, 1)
        lay.addLayout(row)
        return label

    def _build_settings_card(self) -> QtWidgets.QFrame:
        """Opciones que afectan tanto al modo manual como al Auto-Loader."""
        card = QtWidgets.QFrame()
        card.setProperty("class", "Card")
        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(8)

        self.lbl_settings_tag = QtWidgets.QLabel()
        self.lbl_settings_tag.setProperty("class", "SectionTag")
        lay.addWidget(self.lbl_settings_tag)

        self.combo_render_engine = QtWidgets.QComboBox()
        for engine_id, template in ENGINE_TEMPLATES.items():
            self.combo_render_engine.addItem(template["label"], engine_id)
        self.combo_render_engine.setCurrentIndex(
            max(self.combo_render_engine.findData(self.render_engine), 0))
        self.combo_render_engine.activated.connect(self._on_render_engine_activated)
        self.lbl_render_engine = self._settings_row(lay, self.combo_render_engine)

        self.combo_naming_preset = QtWidgets.QComboBox()
        self.combo_naming_preset.activated.connect(self._on_naming_preset_activated)
        self.lbl_naming_preset = self._settings_row(lay, self.combo_naming_preset)
        return card

    def _build_manual_card(self) -> QtWidgets.QFrame:
        card = QtWidgets.QFrame()
        card.setProperty("class", "Card")
        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 18)
        lay.setSpacing(10)

        self.lbl_manual_tag = QtWidgets.QLabel("◆  MANUAL")
        self.lbl_manual_tag.setProperty("class", "SectionTag")
        lay.addWidget(self.lbl_manual_tag)

        self.lbl_manual_desc = QtWidgets.QLabel()
        self.lbl_manual_desc.setProperty("class", "SectionDesc")
        self.lbl_manual_desc.setWordWrap(True)
        lay.addWidget(self.lbl_manual_desc)

        self.btn_manual_apply = QtWidgets.QPushButton()
        self.btn_manual_apply.setObjectName("BtnManual")
        self.btn_manual_apply.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_manual_apply.clicked.connect(self._on_manual_apply)
        lay.addWidget(self.btn_manual_apply)
        return card

    def _build_autoloader_card(self) -> QtWidgets.QFrame:
        card = QtWidgets.QFrame()
        card.setProperty("class", "Card")
        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 18)
        lay.setSpacing(10)

        self.lbl_auto_tag = QtWidgets.QLabel("✦  AUTO-LOADER")
        self.lbl_auto_tag.setProperty("class", "SectionTagAmber")
        lay.addWidget(self.lbl_auto_tag)

        self.lbl_auto_desc = QtWidgets.QLabel()
        self.lbl_auto_desc.setProperty("class", "SectionDesc")
        self.lbl_auto_desc.setWordWrap(True)
        lay.addWidget(self.lbl_auto_desc)

        recent_row = QtWidgets.QHBoxLayout()
        recent_row.setSpacing(8)
        self.lbl_recent = QtWidgets.QLabel("RECENT")
        self.lbl_recent.setProperty("class", "MutedSmall")
        self.lbl_recent.setStyleSheet("letter-spacing:2px; font-weight:700;")
        self.combo_recent = QtWidgets.QComboBox()
        self.combo_recent.setEditable(False)
        self.combo_recent.setFixedWidth(230)
        self.combo_recent.addItem("—")
        self.combo_recent.activated.connect(self._on_recent_activated)
        recent_row.addWidget(self.lbl_recent)
        recent_row.addWidget(self.combo_recent)
        recent_row.addStretch(1)
        lay.addLayout(recent_row)

        folder_row = QtWidgets.QHBoxLayout()
        folder_row.setSpacing(8)
        self.lbl_folder = QtWidgets.QLabel()
        self.lbl_folder.setObjectName("FolderPath")
        self.lbl_folder.setMinimumHeight(36)
        self.btn_browse = QtWidgets.QPushButton()
        self.btn_browse.setObjectName("BtnBrowse")
        self.btn_browse.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_browse.clicked.connect(self._on_browse)
        self.btn_recursive = QtWidgets.QPushButton()
        self.btn_recursive.setObjectName("BtnRecursive")
        self.btn_recursive.setCheckable(True)
        self.btn_recursive.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_recursive.toggled.connect(self._on_toggle_recursive)
        folder_row.addWidget(self.lbl_folder, 1)
        folder_row.addWidget(self.btn_browse)
        folder_row.addWidget(self.btn_recursive)
        lay.addLayout(folder_row)

        self.lbl_scan_info = QtWidgets.QLabel("")
        self.lbl_scan_info.setProperty("class", "StatusInfo")
        lay.addWidget(self.lbl_scan_info)

        threshold_row = QtWidgets.QHBoxLayout()
        threshold_row.setSpacing(8)
        self.lbl_sensitivity = QtWidgets.QLabel("SENSITIVITY")
        self.lbl_sensitivity.setProperty("class", "MutedSmall")
        self.lbl_sensitivity.setStyleSheet("letter-spacing:2px; font-weight:700;")
        self.sld_threshold = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.sld_threshold.setMinimum(0)
        self.sld_threshold.setMaximum(100)
        self.sld_threshold.setSingleStep(5)
        self.sld_threshold.setCursor(QtCore.Qt.PointingHandCursor)
        self.sld_threshold.valueChanged.connect(self._on_threshold_changed)
        self.lbl_threshold_pct = QtWidgets.QLabel("60%")
        self.lbl_threshold_pct.setFixedWidth(38)
        self.lbl_threshold_pct.setProperty("class", "StatusInfo")
        threshold_row.addWidget(self.lbl_sensitivity)
        threshold_row.addWidget(self.sld_threshold, 1)
        threshold_row.addWidget(self.lbl_threshold_pct)
        lay.addLayout(threshold_row)

        self.lbl_match_by = QtWidgets.QLabel("MATCH BY")
        self.lbl_match_by.setProperty("class", "MutedSmall")
        self.lbl_match_by.setStyleSheet("letter-spacing:2px; font-weight:700;")
        lay.addWidget(self.lbl_match_by)

        match_mode_row = QtWidgets.QHBoxLayout()
        match_mode_row.setSpacing(6)
        self.btn_match_object = QtWidgets.QPushButton()
        self.btn_match_object.setObjectName("BtnMatchMode")
        self.btn_match_object.setCheckable(True)
        self.btn_match_object.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_match_material = QtWidgets.QPushButton()
        self.btn_match_material.setObjectName("BtnMatchMode")
        self.btn_match_material.setCheckable(True)
        self.btn_match_material.setCursor(QtCore.Qt.PointingHandCursor)
        self.grp_match_mode = QtWidgets.QButtonGroup(self)
        self.grp_match_mode.setExclusive(True)
        self.grp_match_mode.addButton(self.btn_match_object)
        self.grp_match_mode.addButton(self.btn_match_material)
        self.grp_match_mode.buttonClicked.connect(self._on_match_mode_clicked)
        match_mode_row.addWidget(self.btn_match_object, 1)
        match_mode_row.addWidget(self.btn_match_material, 1)
        lay.addLayout(match_mode_row)

        self.lbl_match_mode_info = QtWidgets.QLabel()
        self.lbl_match_mode_info.setWordWrap(True)
        self.lbl_match_mode_info.setStyleSheet(
            "color:#9297A8; font-size:11px; background:#101116; "
            "border:1px solid #24252E; border-radius:6px; padding:6px 10px;")
        lay.addWidget(self.lbl_match_mode_info)

        lay.addSpacing(2)

        self.btn_match = QtWidgets.QPushButton()
        self.btn_match.setObjectName("BtnMatch")
        self.btn_match.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_match.clicked.connect(self._on_smart_match)
        lay.addWidget(self.btn_match)

        self.lbl_preview = QtWidgets.QLabel()
        self.lbl_preview.setProperty("class", "MutedSmall")
        self.lbl_preview.setStyleSheet("letter-spacing:2px; font-weight:700;")
        lay.addWidget(self.lbl_preview)

        self.tree_matches = QtWidgets.QTreeWidget()
        self.tree_matches.setHeaderHidden(True)
        self.tree_matches.setColumnCount(1)
        self.tree_matches.setMinimumHeight(220)
        self.tree_matches.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tree_matches.setRootIsDecorated(True)
        self.tree_matches.setIndentation(26)
        self.tree_matches.setExpandsOnDoubleClick(False)
        self.tree_matches.itemChanged.connect(self._on_tree_item_changed)
        self.tree_matches.itemDoubleClicked.connect(self._on_item_double_clicked)
        lay.addWidget(self.tree_matches, 1)

        remove_row = QtWidgets.QHBoxLayout()
        remove_row.addStretch(1)
        self.btn_remove = QtWidgets.QPushButton()
        self.btn_remove.setObjectName("BtnBrowse")
        self.btn_remove.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_remove.clicked.connect(self._on_remove_selected)
        remove_row.addWidget(self.btn_remove)
        lay.addLayout(remove_row)

        self.lbl_match_status = QtWidgets.QLabel("")
        self.lbl_match_status.setProperty("class", "SectionDesc")
        self.lbl_match_status.setStyleSheet("font-size:12px;")
        lay.addWidget(self.lbl_match_status)

        lay.addSpacing(4)

        self.btn_apply = QtWidgets.QPushButton()
        self.btn_apply.setObjectName("BtnApply")
        self.btn_apply.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_apply.clicked.connect(self._on_apply_auto)
        lay.addWidget(self.btn_apply)

        return card

    def _build_footer(self) -> QtWidgets.QLabel:
        self.lbl_footer = QtWidgets.QLabel()
        self.lbl_footer.setObjectName("Footer")
        self.lbl_footer.setAlignment(QtCore.Qt.AlignCenter)
        return self.lbl_footer

    # ── Helpers del árbol de matches ─────────────────────────

    def _row_color_and_text(self, obj: str, tex_base: Optional[str],
                             score: float) -> Tuple[str, QtGui.QColor]:
        short_obj = obj.split("|")[-1]
        pct = f"{score:.0%}"
        if tex_base:
            n_files = len(self.tex_map.get(tex_base, []))
            text = f"  {pct:>5}   {short_obj}   →   {tex_base}   [{n_files} files]"
            if score >= 0.85:
                color = QtGui.QColor("#2FAE6B")
            elif score >= 0.70:
                color = QtGui.QColor("#3C7FD0")
            else:
                color = QtGui.QColor("#C98A1E")
        else:
            text = f"  {pct:>5}   {short_obj}   →   {self._t('no_match')}"
            color = QtGui.QColor("#8A93A0")
        return text, color

    def _make_channel_item(self, parent: QtWidgets.QTreeWidgetItem, match_idx: int,
                            map_id: str, ch: Dict[str, Any]) -> QtWidgets.QTreeWidgetItem:
        fname = os.path.basename(ch["file"])
        tag = self._t("overridden_tag") if ch["overridden"] else (
            self._t("udim_tag") if ch["is_udim"] else "")
        child = QtWidgets.QTreeWidgetItem([f"      {map_id:<12}  {fname}{tag}"])
        child.setData(0, QtCore.Qt.UserRole, (match_idx, map_id))
        child.setFlags(child.flags() | QtCore.Qt.ItemIsUserCheckable)
        child.setCheckState(0, QtCore.Qt.Checked if ch["enabled"] else QtCore.Qt.Unchecked)
        if not ch["enabled"]:
            child.setForeground(0, QtGui.QColor("#575A66"))
        parent.addChild(child)
        return child

    def _populate_tree(self) -> None:
        self.tree_matches.blockSignals(True)
        self.tree_matches.clear()
        for idx, m in enumerate(self.matches):
            text, color = self._row_color_and_text(m["obj"], m["tex_base"], m["score"])
            top = QtWidgets.QTreeWidgetItem([text])
            top.setForeground(0, color)
            top.setData(0, QtCore.Qt.UserRole, idx)
            for map_id, ch in m["channels"].items():
                self._make_channel_item(top, idx, map_id, ch)
            self.tree_matches.addTopLevelItem(top)
        self.tree_matches.blockSignals(False)
        self._refresh_match_status()

    def _refresh_match_status(self) -> None:
        matched = sum(1 for m in self.matches if m["tex_base"])
        self.lbl_match_status.setText(
            "  " + self._t("match_status", matched=matched, total=len(self.matches)))

    # ── Estado de sesión ──────────────────────────────────────

    def _persist_state(self) -> None:
        save_state(_app_dir(), self.state)

    # ── Handlers ─────────────────────────────────────────────

    def _on_manual_apply(self) -> None:
        if not self._ensure_engine_ready():
            return
        report = load_textures_and_apply(self._cfg(), self.language, engine=self.render_engine)
        if report:
            self._show_report_dialog(report)

    def _on_browse(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, self._t("select_folder_dialog"))
        if not folder:
            return
        self._set_folder(folder)

    def _on_toggle_recursive(self, checked: bool) -> None:
        self.btn_recursive.setText(self._t("btn_recursive") + ("  ✓" if checked else ""))
        self.state["last_recursive"] = checked
        self._persist_state()
        if self.folder:
            self._set_folder(self.folder)

    def _on_threshold_changed(self, value: int) -> None:
        self.lbl_threshold_pct.setText(f"{value}%")
        self.config["match_threshold"] = value / 100.0
        self.state["last_threshold"] = value / 100.0
        self._persist_state()

    def _on_match_mode_clicked(self, button: QtWidgets.QAbstractButton) -> None:
        self.match_mode = "material_id" if button is self.btn_match_material else "object_name"
        self.state["last_match_mode"] = self.match_mode
        self._persist_state()
        self._update_match_mode_info()

    def _on_render_engine_activated(self, index: int) -> None:
        engine = self.combo_render_engine.itemData(index)
        if engine in ENGINE_TEMPLATES:
            self.render_engine = engine
            self.state["last_render_engine"] = engine
            self._persist_state()

    def _ensure_engine_ready(self) -> bool:
        """Redshift / V-Ray necesitan su plugin cargado para crear el
        shader: si no lo está, ofrece cargarlo antes de tocar la escena."""
        if engine_plugin_loaded(self.render_engine):
            return True
        template = ENGINE_TEMPLATES[self.render_engine]
        resp = QtWidgets.QMessageBox.question(
            self, self._t("render_engine_title"),
            self._t("msg_engine_plugin_not_loaded", engine=template["label"],
                    plugin=template["plugin"]),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
            QtWidgets.QMessageBox.Yes)
        if resp != QtWidgets.QMessageBox.Yes:
            return False
        try:
            cmds.loadPlugin(template["plugin"])
        except Exception as e:
            _warn(self._t("msg_engine_plugin_load_failed", plugin=template["plugin"], error=e))
            return False
        return engine_plugin_loaded(self.render_engine)

    def _refresh_naming_preset_combo(self) -> None:
        self.combo_naming_preset.blockSignals(True)
        self.combo_naming_preset.clear()
        for preset_id, label in list_naming_presets(self.config, self.language):
            self.combo_naming_preset.addItem(label, preset_id)
        index = self.combo_naming_preset.findData(self.naming_preset)
        self.combo_naming_preset.setCurrentIndex(max(index, 0))
        self.combo_naming_preset.blockSignals(False)

    def _on_naming_preset_activated(self, index: int) -> None:
        preset_id = self.combo_naming_preset.itemData(index)
        if not preset_id or preset_id == self.naming_preset:
            return
        self.naming_preset = preset_id
        self.state["last_naming_preset"] = preset_id
        self._persist_state()
        # El agrupamiento en sets depende de los sufijos: re-escanear.
        if self.folder:
            self._set_folder(self.folder)

    def _update_match_mode_info(self) -> None:
        key = "match_mode_info_material_id" if self.match_mode == "material_id" \
            else "match_mode_info_object_name"
        self.lbl_match_mode_info.setText(self._t(key))

    def _set_folder(self, folder: str) -> None:
        if not os.path.isdir(folder):
            _warn(f"[TextureAutoloader] {self._t('msg_folder_missing', folder=folder)}")
            return

        self.folder = folder
        recursive = self.btn_recursive.isChecked()

        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            self.tex_map = scan_folder(folder, self._cfg(), recursive)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        total_files = sum(len(v) for v in self.tex_map.values())
        short = ("…" + folder[-44:]) if len(folder) > 47 else folder
        self.lbl_folder.setText(short)
        self.lbl_folder.setToolTip(folder)
        self.lbl_scan_info.setText(
            "  " + self._t("scan_info", sets=len(self.tex_map), files=total_files))
        self.matches = []
        self.tree_matches.clear()
        self.lbl_match_status.setText("")
        _log_print(f"[TextureAutoloader] Loaded {len(self.tex_map)} set(s) from: {folder}")

        recent = push_recent_folder(self.state.get("recent_folders", []), folder)
        self.state["recent_folders"] = recent
        self.state["last_recursive"] = recursive
        self._persist_state()
        self._refresh_recent_combo(recent)

    def _refresh_recent_combo(self, recent: List[str]) -> None:
        self.combo_recent.blockSignals(True)
        self.combo_recent.clear()
        self.combo_recent.addItem(self._t("recent_placeholder"))
        self.combo_recent.addItems(recent)
        self.combo_recent.setCurrentIndex(0)
        self.combo_recent.blockSignals(False)

    def _on_recent_activated(self, index: int) -> None:
        if index <= 0:
            return
        path = self.combo_recent.itemText(index)
        if path:
            self._set_folder(path)

    def _on_smart_match(self) -> None:
        sel = cmds.ls(sl=True) or []
        if not sel:
            _warn(self._t("msg_select_meshes"))
            return
        if not self.tex_map:
            _warn(self._t("msg_load_folder_first"))
            return

        self.matches = match_objects_to_textures(sel, self.tex_map, self._cfg(),
                                                  match_mode=self.match_mode)
        self._populate_tree()
        matched = sum(1 for m in self.matches if m["tex_base"])
        _log_print(f"[TextureAutoloader] Smart Match ({self.match_mode}): "
                   f"{matched}/{len(self.matches)}")

    def _on_tree_item_changed(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        data = item.data(0, QtCore.Qt.UserRole)
        if not isinstance(data, tuple):
            return
        match_idx, map_id = data
        enabled = item.checkState(0) == QtCore.Qt.Checked
        self.matches[match_idx]["channels"][map_id]["enabled"] = enabled
        item.setForeground(0, QtGui.QColor("#C7C9D6") if enabled else QtGui.QColor("#575A66"))

    def _on_item_double_clicked(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        data = item.data(0, QtCore.Qt.UserRole)
        if isinstance(data, tuple):
            self._on_edit_channel(*data)
        else:
            self._on_edit_match(data)

    def _on_edit_match(self, match_idx: int) -> None:
        m = self.matches[match_idx]
        none_label = self._t("dialog_reassign_none")
        options = [none_label] + list(self.tex_map.keys())
        current = m["tex_base"] if m["tex_base"] in self.tex_map else none_label

        choice, ok = QtWidgets.QInputDialog.getItem(
            self, self._t("dialog_reassign_title"),
            f"{m['obj'].split('|')[-1]}:", options,
            options.index(current), editable=False)
        if not ok:
            return

        new_base = None if choice == none_label else choice
        self.matches[match_idx] = build_match_entry(
            m["obj"], new_base, 1.0 if new_base else 0.0, self.tex_map, self._cfg(), warn_fn=_warn)
        self._populate_tree()

    def _on_edit_channel(self, match_idx: int, map_id: str) -> None:
        m = self.matches[match_idx]
        ch = m["channels"].get(map_id)
        if not ch:
            return
        start_dir = os.path.dirname(ch["file"]) if ch.get("file") else (self.folder or "")
        new_file, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self, f"{map_id}", start_dir,
            "Images (*.png *.jpg *.jpeg *.tga *.exr *.tif *.tiff *.hdr *.bmp)")
        if not new_file:
            return
        ch["file"] = new_file
        ch["is_udim"] = False
        ch["overridden"] = True
        self._populate_tree()

    def _on_remove_selected(self) -> None:
        selected_idxs = set()
        for item in self.tree_matches.selectedItems():
            data = item.data(0, QtCore.Qt.UserRole)
            idx = data[0] if isinstance(data, tuple) else data
            if idx is not None:
                selected_idxs.add(idx)
        if not selected_idxs:
            _warn(self._t("msg_select_to_remove"))
            return
        self.matches = [m for i, m in enumerate(self.matches) if i not in selected_idxs]
        self._populate_tree()

    def _on_apply_auto(self) -> None:
        if not self.matches:
            _warn(self._t("msg_run_smart_match_first"))
            return
        if not self._ensure_engine_ready():
            return

        conflicts = [m["obj"] for m in self.matches
                     if m["tex_base"] and has_autoloader_material(m["obj"])]
        if conflicts:
            resp = QtWidgets.QMessageBox.question(
                self, self._t("dialog_existing_materials_title"),
                self._t("dialog_existing_materials_body", count=len(conflicts)),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Yes)
            if resp != QtWidgets.QMessageBox.Yes:
                return

        progress = QtWidgets.QProgressDialog(
            self._t("progress_applying"), self._t("progress_cancel"), 0, len(self.matches), self)
        progress.setWindowTitle(self._t("progress_title"))
        progress.setWindowModality(QtCore.Qt.WindowModal)
        progress.setMinimumDuration(0)

        def _cb(i: int, total: int, obj: str) -> bool:
            progress.setValue(i)
            if obj:
                progress.setLabelText(
                    self._t("progress_label", obj=obj.split('|')[-1], current=i + 1, total=total))
            QtWidgets.QApplication.processEvents()
            return progress.wasCanceled()

        cmds.undoInfo(openChunk=True)
        try:
            applied, skipped = apply_auto_textures(self.matches, self._cfg(), progress_cb=_cb,
                                                   engine=self.render_engine)
        finally:
            cmds.undoInfo(closeChunk=True)
            progress.setValue(len(self.matches))

        report = build_report(self.matches, self.language, tex_map=self.tex_map)
        _log_print(report)
        self._show_report_dialog(report, applied, skipped)

    def _show_report_dialog(self, report: str, applied: Optional[int] = None,
                            skipped: Optional[int] = None) -> None:
        """Resumen arriba; el reporte ✔/✘ completo en "Show Details…"
        (el área desplegable estándar de QMessageBox)."""
        rows = [f"<p style='font-size:13px;'><b>{self._t('done_title')}</b></p>"]
        if applied is not None:
            rows.append(f"<p>{self._t('done_body_applied')}: "
                        f"<span style='color:#2ED573;'>{applied}</span></p>")
            rows.append(f"<p>{self._t('done_body_skipped')}: "
                        f"<span style='color:#FFB547;'>{skipped}</span></p>")
        rows.append(f"<p>{html.escape(report.splitlines()[-1])}</p>")
        rows.append(f"<p style='color:#9297A8;'>{self._t('done_body_report_hint')}</p>")

        msg = QtWidgets.QMessageBox(self)
        msg.setWindowTitle(self._t("done_title"))
        msg.setText("<div style='font-family:Segoe UI; color:#E8E8EA;'>" + "".join(rows) + "</div>")
        msg.setDetailedText(report)
        msg.setStandardButtons(QtWidgets.QMessageBox.Ok)
        (msg.exec if hasattr(msg, "exec") else msg.exec_)()


def create_ui() -> TextureAutoloaderDialog:
    """Punto de entrada — abre la UI Qt y la deja como singleton."""
    if TextureAutoloaderDialog._instance is not None:
        try:
            TextureAutoloaderDialog._instance.close()
            TextureAutoloaderDialog._instance.deleteLater()
        except Exception:
            pass
        TextureAutoloaderDialog._instance = None

    dlg = TextureAutoloaderDialog()
    TextureAutoloaderDialog._instance = dlg
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return dlg


# ── Entry point ───────────────────────────────────────────────
if __name__ == "__main__":
    create_ui()

# Core helpers the front-end overrides, kept callable as _core_<name>:
#   apply_auto_textures, match_objects_to_textures
