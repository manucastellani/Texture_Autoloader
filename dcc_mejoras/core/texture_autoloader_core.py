"""
Texture Autoloader — Core (DCC-agnostic)
=========================================
Author: Manuel Castellani

This module contains every part of Texture Autoloader that does NOT
depend on Maya, Blender, or any specific UI toolkit: string/name
normalization, fuzzy matching, UDIM collapsing, map-type bucketing,
config/state persistence and logging. Both `maya/texture_autoloader_maya.py`
and `blender/texture_autoloader_blender.py` import this module and only
add the pieces that are genuinely specific to their host application: the
actual shading-node wiring (aiStandardSurface vs. Principled BSDF) and the
UI framework (Qt vs. Blender's own).

Design rule enforced throughout this file: nothing in here imports
`maya`, `bpy`, `PySide`, or any GUI library. Anything that needs to know
"is this a mesh" or "what material is assigned to this object" is passed
in by the caller as plain data (see `match_objects_to_textures`) instead
of this module reaching into the scene itself. That is what makes the
same matching/naming logic usable, unmodified, from two completely
different applications.

---------------------------------------------------------------------
Historia / changelog (heredado de las versiones anteriores del proyecto,
que vivía como una única herramienta de Maya llamada "Arnold Node
Wrangler"; ver maya/texture_autoloader_maya.py para el detalle completo
de las versiones v1 a v4.1 previas al split multi-DCC):

  - v5.0 (este release): split en core (DCC-agnostic) + maya + blender.
    Renombrado de "Arnold Node Wrangler" a "Texture Autoloader" (nombre
    más claro sobre qué hace la herramienta y ya no atado a un único
    renderer). UI bilingüe (EN/ES) con botón de idioma. Logging
    persistente a archivo y fin del auto-install silencioso de
    rapidfuzz (heredado de v4.1, ver el changelog de maya/ para el
    detalle). Suite de tests separada en tests de core (sin stubs,
    100% DCC-agnóstico) y tests de maya (con stubs de maya.cmds/Qt).
---------------------------------------------------------------------
"""

import os
import re
import json
import difflib
import logging
import logging.handlers
from typing import Optional, List, Dict, Tuple, Callable, Any


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
    "naming_presets": {
        "short_suffixes": {
            "label": "Short suffixes (_BC _N _R _M _AO _E _H _O)",
            "map_types": [
                {"id": "baseColor", "suffixes": ["BC", "Albedo", "D"]},
                {"id": "normal", "suffixes": ["N", "NRM"]},
                {"id": "roughness", "suffixes": ["R", "Rough"]},
                {"id": "metallic", "suffixes": ["M", "Metal"]},
                {"id": "ao", "suffixes": ["AO"]},
                {"id": "emission", "suffixes": ["E", "Emissive"]},
                {"id": "displacement", "suffixes": ["H", "Height", "Disp"]},
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


_MATERIAL_SUFFIX_RE = re.compile(r'[_]?(mat|material|shader|sg)$', re.I)


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


def similarity(a: str, b: str) -> float:
    """0..1 similarity between two names, tolerant of typos and substrings."""
    a = a.lower().replace("_", "").replace("-", "").replace(" ", "")
    b = b.lower().replace("_", "").replace("-", "").replace(" ", "")
    if HAS_RAPIDFUZZ:
        score = _FUZZ.WRatio(a, b) / 100.0
    else:
        score = difflib.SequenceMatcher(None, a, b).ratio()
    if a in b or b in a:
        score = max(score, 0.85)
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
    """Pairs each logical object name with the best tex_base by similarity."""
    results = []
    for obj_base in obj_names:
        best_base, best_score = None, 0.0
        for tb in tex_bases:
            s = similarity(obj_base, tb)
            if s > best_score:
                best_score, best_base = s, tb
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


def match_objects_to_textures(object_entries: List[Tuple[str, Optional[str]]],
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


def match_names_to_textures(named_entries: List[Tuple[str, str]],
                             tex_map: Dict[str, List[str]],
                             config: Dict[str, Any],
                             warn_fn: Optional[Callable[[str], None]] = None
                             ) -> List[Dict[str, Any]]:
    """Lower-level matching for front-ends that decide by themselves which
    name stands for each thing to match: `named_entries` is a list of
    (key, logical_name) pairs, and each resulting entry carries "obj" =
    key. The Unreal port uses it to match Material Slots (one mesh can
    need several texture sets), not whole objects."""
    pure_results = compute_matches([name for _key, name in named_entries],
                                   list(tex_map.keys()), config["match_threshold"])
    return [build_match_entry(key, tex_base, score, tex_map, config, warn_fn=warn_fn)
            for (key, _name), (_base, tex_base, score) in zip(named_entries, pure_results)]


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


def apply_auto_textures(matches: List[Dict[str, Any]],
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
