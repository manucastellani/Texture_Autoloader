"""
Texture Autoloader — Blender (STANDALONE, single-file build)
====================================================================
Author: Manuel Castellani

This is a self-contained, single-file build meant to be installed via
Edit > Preferences > Add-ons > Install..., pointing at THIS file alone
— no sibling `core/` folder required.

Why this file exists separately from `texture_autoloader_blender.py`:
that other version imports a shared `core/` module so the exact same
matching logic and translation table also power the Maya version in
this repo, with one automated test suite instead of two. That's the
right architecture to develop and test against — but Blender's
"Install..." for a single .py file copies only that file into Blender's
own addons folder; it does not bring along a sibling `core/` folder.
Installed that way, the modular version fails immediately with
`RuntimeError: Error: No module named 'texture_autoloader_core'`,
because the folder it expects to sit next to no longer exists on disk
after installation.

This standalone build trades that shared architecture for the simplest
possible install story: point Blender's addon installer at this one
file, enable it, done. Keeping this file's logic in sync with
core/texture_autoloader_core.py is a manual step when one changes —
that duplication is the accepted cost of a true single-file addon. If
you're extending the matching logic, do it in core/ first (it has an
automated test suite) and port the change here and to the Maya
standalone build.

Once enabled, the panel lives in the 3D Viewport's Sidebar (press N),
under the "Texture Autoloader" tab.
"""

bl_info = {
    "name": "Texture Autoloader (Standalone)",
    "author": "Manuel Castellani",
    "version": (5, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Texture Autoloader",
    "description": "Scans a folder, matches meshes to Substance texture sets by name, "
                    "and wires a Principled BSDF per object. Single-file build.",
    "category": "Material",
}

import os
import re
import json
import glob
import difflib
import logging
import logging.handlers
import textwrap
from typing import Optional, List, Dict, Tuple, Any, Callable

import bpy
from bpy.props import (
    StringProperty, BoolProperty, FloatProperty, EnumProperty, IntProperty,
)
from bpy.types import Operator, Panel, PropertyGroup, Menu


# ══════════════════════════════════════════════════════════════
#  ARCHIVOS DE SOPORTE — config / state / log
#  A diferencia del problema en Maya (donde __file__ no existe si se
#  pega texto suelto), acá __file__ SÍ está definido porque Blender
#  siempre carga los addons desde un archivo real en disco. El único
#  problema real es que la carpeta hermana "core/" no viaja junto con
#  este archivo cuando se instala como addon de un solo archivo — por
#  eso este build la elimina por completo, en vez de intentar ubicarla.
# ══════════════════════════════════════════════════════════════

def _app_dir() -> str:
    try:
        base = os.path.dirname(os.path.abspath(__file__))
        os.makedirs(base, exist_ok=True)
        return base
    except Exception:
        return os.path.expanduser("~")


CONFIG_FILENAME = "texture_autoloader_config.json"
STATE_FILENAME = "texture_autoloader_state.json"
LOG_FILENAME = "texture_autoloader.log"

_logger_instance: Optional["logging.Logger"] = None


def get_logger() -> "logging.Logger":
    global _logger_instance
    if _logger_instance is not None:
        return _logger_instance

    logger = logging.getLogger("TextureAutoloaderBlenderStandalone")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    try:
        log_path = os.path.join(_app_dir(), LOG_FILENAME)
        handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        logger.addHandler(handler)
    except Exception:
        pass
    _logger_instance = logger
    return logger


def _warn(message: str) -> None:
    print(f"[Texture Autoloader] WARNING: {message}")
    try:
        get_logger().warning(message)
    except Exception:
        pass


def _log_print(message: str) -> None:
    print(message)
    try:
        get_logger().info(message)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
#  i18n — misma tabla que core/texture_autoloader_core.py
# ══════════════════════════════════════════════════════════════

DEFAULT_LANGUAGE = "en"

TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "en": {
        "app_title": "TEXTURE AUTOLOADER",
        "app_subtitle": "SUBSTANCE  ·  AUTO-LOADER",
        "footer": "Manuel Castellani  ·  Texture Autoloader (standalone)",
        "section_manual": "MANUAL",
        "section_manual_desc": "Select an object and choose the texture files one by one.",
        "btn_manual_apply": "SELECT FILES AND APPLY",
        "section_autoloader": "AUTO-LOADER",
        "section_autoloader_desc": (
            "Scan a folder, match meshes to texture sets by name, and apply in "
            "batch. Use the reassign menu to change an object's whole set; toggle "
            "a channel button to enable/disable just that map."
        ),
        "recent_label": "RECENT",
        "recent_placeholder": "— Recent folders —",
        "btn_browse": "SCAN FOLDER",
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
        "preview_label": "PREVIEW",
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
    },
    "es": {
        "app_title": "TEXTURE AUTOLOADER",
        "app_subtitle": "SUBSTANCE   ·   AUTO-LOADER",
        "footer": "Manuel Castellani  ·  Texture Autoloader (standalone)",
        "section_manual": "MANUAL",
        "section_manual_desc": "Seleccioná un objeto y elegí los archivos de textura individualmente.",
        "btn_manual_apply": "SELECCIONAR ARCHIVOS  Y  APLICAR",
        "section_autoloader": "AUTO-LOADER",
        "section_autoloader_desc": (
            "Escaneá una carpeta, empareja meshes por nombre y aplicá en batch. "
            "Usá el menú de reasignar para cambiar el set completo de un objeto; "
            "el botón de cada canal lo activa/desactiva."
        ),
        "recent_label": "RECIENTES",
        "recent_placeholder": "— Carpetas recientes —",
        "btn_browse": "ESCANEAR CARPETA",
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
        "preview_label": "PREVIEW",
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
    },
}


def tr(language: str, key: str, **kwargs) -> str:
    lang_table = TRANSLATIONS.get(language, TRANSLATIONS[DEFAULT_LANGUAGE])
    text = lang_table.get(key, TRANSLATIONS[DEFAULT_LANGUAGE].get(key, key))
    return text.format(**kwargs) if kwargs else text


def other_language(language: str) -> str:
    return "es" if language == "en" else "en"


def _t(key: str, **kwargs) -> str:
    scene = bpy.context.scene
    language = getattr(scene.texture_autoloader, "language", DEFAULT_LANGUAGE) \
        if hasattr(scene, "texture_autoloader") else DEFAULT_LANGUAGE
    return tr(language, key, **kwargs)


# ══════════════════════════════════════════════════════════════
#  CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════

DEFAULT_CONFIG: Dict[str, Any] = {
    "mesh_prefixes": ["SM_", "SK_", "M_", "T_", "MI_", "FX_"],
    "match_threshold": 0.60,
    "match_mode": "object_name",
    "language": DEFAULT_LANGUAGE,
    "texture_extensions": [".png", ".jpg", ".jpeg", ".tga", ".tiff",
                            ".tif", ".exr", ".hdr", ".bmp"],
    "enable_udim_detection": True,
    "enable_displacement_wiring": False,
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
    "map_types": [
        {"id": "baseColor", "match": ["basecolor", "base_color", "_color", "_diff", "_albedo"],
         "color_space": "sRGB", "raw": False},
        {"id": "roughness", "match": ["_roughness", "_rough"],
         "color_space": "Non-Color", "raw": True},
        {"id": "metallic", "match": ["_metallic", "_metal"],
         "color_space": "Non-Color", "raw": True},
        {"id": "normal", "match": ["_normal", "_norm", "_nrm"],
         "color_space": "Non-Color", "raw": True},
        {"id": "emission", "match": ["_emission", "_emissive", "_emit"],
         "color_space": "sRGB", "raw": False},
        {"id": "ao", "match": ["_ao", "_ambientocclusion", "_mixed_ao", "_occlusion"],
         "color_space": "Non-Color", "raw": True},
        {"id": "displacement", "match": ["_displacement", "_disp", "_height"],
         "color_space": "Non-Color", "raw": True},
        {"id": "opacity", "match": ["_opacity", "_alpha", "_mask"],
         "color_space": "Non-Color", "raw": True},
    ],
}


def _deep_merge_defaults(loaded: Dict[str, Any], defaults: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(defaults)
    merged.update({k: v for k, v in loaded.items() if k in defaults})
    return merged


def load_config(warn_fn: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    warn = warn_fn or _warn
    path = os.path.join(_app_dir(), CONFIG_FILENAME)
    if not os.path.exists(path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
        return dict(DEFAULT_CONFIG)
    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        return _deep_merge_defaults(loaded, DEFAULT_CONFIG)
    except Exception as e:
        warn(f"[TextureAutoloader] Could not read {path} ({e}) — using default config.")
        return dict(DEFAULT_CONFIG)


def _state_path() -> str:
    return os.path.join(_app_dir(), STATE_FILENAME)


def load_state() -> Dict[str, Any]:
    path = _state_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state: Dict[str, Any]) -> None:
    try:
        with open(_state_path(), "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _config() -> Dict[str, Any]:
    return load_config(warn_fn=_warn)


# ══════════════════════════════════════════════════════════════
#  DEPENDENCIA OPCIONAL (rapidfuzz)
# ══════════════════════════════════════════════════════════════

def _ensure_rapidfuzz() -> Tuple[Optional[Any], bool]:
    try:
        from rapidfuzz import fuzz
        return fuzz, True
    except ImportError:
        return None, False


_FUZZ, HAS_RAPIDFUZZ = _ensure_rapidfuzz()
if not HAS_RAPIDFUZZ:
    _warn(
        "[TextureAutoloader] rapidfuzz is not installed in Blender's Python — "
        "using the internal difflib fallback for fuzzy matching. This is not "
        "an error, it only lowers precision a bit on very different-looking names.")


# ══════════════════════════════════════════════════════════════
#  PURO — SIN bpy
# ══════════════════════════════════════════════════════════════

_EXTS = set(DEFAULT_CONFIG["texture_extensions"])

_TRAILING_MOD = re.compile(
    r'[_\-](opengl|directx|dx|gl|tangent|world|object|space|'
    r'1k|2k|4k|8k|hi|lo|hd|sd|udim|\d{4})$', re.I)

_UDIM_RE = re.compile(r'^(?P<prefix>.*)(?P<sep>[._-])(?P<tile>1[0-9]{3})$')

_RESOLUTION_DENYLIST = {512, 1024, 2048, 4096, 8192, 16384}


def _strip_trailing_modifiers(stem: str) -> str:
    prev = None
    while prev != stem:
        prev = stem
        stem = _TRAILING_MOD.sub('', stem)
    return stem


def _tex_base_name(filename: str, suffix_strip_list: List[str]) -> str:
    stem = _strip_trailing_modifiers(os.path.splitext(filename)[0])
    for sfx in sorted(suffix_strip_list, key=len, reverse=True):
        pattern = re.compile(rf'[_\-]{sfx}$', re.I)
        if pattern.search(stem):
            stem = pattern.sub('', stem)
            break
    return stem.strip('-_')


def _mesh_base_name(obj: str, mesh_prefixes: List[str]) -> str:
    n = obj.split("|")[-1]
    for p in mesh_prefixes:
        if n.upper().startswith(p.upper()):
            n = n[len(p):]
            break
    n = re.sub(r'Shape$', '', n)
    n = re.sub(r'_LOD\d$', '', n)
    n = re.sub(r'_[A-Z]$', '', n)
    n = re.sub(r'_\d+$', '', n)
    return n


_MATERIAL_SUFFIX_RE = re.compile(r'[_]?(mat|material|shader|sg|txa)$', re.I)


def _material_base_name(material: str, mesh_prefixes: List[str]) -> str:
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


def _similarity(a: str, b: str) -> float:
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
    exts = extensions or _EXTS
    result: Dict[str, List[str]] = {}
    walker = os.walk(folder) if recursive else [(folder, [], os.listdir(folder))]
    for root, _dirs, files in walker:
        for fname in files:
            if os.path.splitext(fname)[1].lower() not in exts:
                continue
            base = _tex_base_name(fname, suffix_strip_list)
            result.setdefault(base, []).append(os.path.join(root, fname))
    return result


def _compute_matches(obj_names: List[str], tex_bases: List[str],
                      threshold: float) -> List[Tuple[str, Optional[str], float]]:
    results = []
    for obj_base in obj_names:
        best_base, best_score = None, 0.0
        for tb in tex_bases:
            s = _similarity(obj_base, tb)
            if s > best_score:
                best_score, best_base = s, tb
        results.append((obj_base, best_base if best_score >= threshold else None, best_score))
    return results


MAX_RECENT_FOLDERS = 5


def push_recent_folder(recent: List[str], folder: str) -> List[str]:
    updated = [folder] + [f for f in recent if f != folder]
    return updated[:MAX_RECENT_FOLDERS]


def bucket_files_by_type(file_paths: List[str],
                          map_types: List[Dict[str, Any]]
                          ) -> Tuple[Dict[str, List[str]], List[str]]:
    buckets: Dict[str, List[str]] = {}
    unmatched: List[str] = []
    for file_path in file_paths:
        fname_lower = os.path.basename(file_path).lower()
        matched_id = None
        for mt in map_types:
            if any(s in fname_lower for s in mt["match"]):
                matched_id = mt["id"]
                break
        if matched_id:
            buckets.setdefault(matched_id, []).append(file_path)
        else:
            unmatched.append(file_path)
    return buckets, unmatched


def _collapse_udim_set(file_paths: List[str],
                        warn_fn: Optional[Callable[[str], None]] = None) -> Tuple[str, bool]:
    warn = warn_fn or _warn
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
        warn(
            f"[TextureAutoloader] {len(file_paths)} files match the same map "
            f"type and don't look like UDIM tiles — using only: "
            f"{os.path.basename(file_paths[0])}")
        return file_paths[0], False

    key = max(udim_groups, key=lambda k: len(udim_groups[k]))
    d, prefix, sep, ext = key
    representative = os.path.join(d, f"{prefix}{sep}<UDIM>{ext}")
    return representative, True


def resolve_channel_files(buckets: Dict[str, List[str]], config: Dict[str, Any],
                           warn_fn: Optional[Callable[[str], None]] = None
                           ) -> Dict[str, Tuple[str, bool]]:
    warn = warn_fn or _warn
    resolved: Dict[str, Tuple[str, bool]] = {}
    for map_id, files in buckets.items():
        if config.get("enable_udim_detection", True):
            representative, is_udim = _collapse_udim_set(files, warn_fn=warn)
        else:
            representative, is_udim = files[0], False
            if len(files) > 1:
                warn(
                    f"[TextureAutoloader] {len(files)} files match the map "
                    f"'{map_id}' — UDIM detection is disabled, using only: "
                    f"{os.path.basename(files[0])}")
        resolved[map_id] = (representative, is_udim)
    return resolved


def build_match_entry(obj: str, tex_base: Optional[str], score: float,
                       tex_map: Dict[str, List[str]], config: Dict[str, Any],
                       warn_fn: Optional[Callable[[str], None]] = None
                       ) -> Dict[str, Any]:
    channels: Dict[str, Dict[str, Any]] = {}
    if tex_base and tex_base in tex_map:
        buckets, _unmatched = bucket_files_by_type(tex_map[tex_base], config["map_types"])
        resolved = resolve_channel_files(buckets, config, warn_fn=warn_fn)
        for map_id, (filepath, is_udim) in resolved.items():
            channels[map_id] = {
                "enabled": True,
                "file": filepath,
                "is_udim": is_udim,
                "overridden": False,
            }
    return {
        "obj": obj,
        "tex_base": tex_base,
        "score": score,
        "channels": channels,
    }


def match_objects_to_textures(object_entries: List[Tuple[str, Optional[str]]],
                               tex_map: Dict[str, List[str]], config: Dict[str, Any],
                               match_mode: str = "object_name",
                               warn_fn: Optional[Callable[[str], None]] = None
                               ) -> List[Dict[str, Any]]:
    mesh_prefixes = config["mesh_prefixes"]
    threshold = config["match_threshold"]

    obj_names: List[str] = []
    obj_bases: List[str] = []
    for obj_name, assigned_material in object_entries:
        base = None
        if match_mode == "material_id" and assigned_material:
            base = _material_base_name(assigned_material, mesh_prefixes)
        if not base:
            base = _mesh_base_name(obj_name, mesh_prefixes)
        obj_names.append(obj_name)
        obj_bases.append(base)

    pure_results = _compute_matches(obj_bases, list(tex_map.keys()), threshold)

    return [build_match_entry(obj, tex_base, score, tex_map, config, warn_fn=warn_fn)
            for obj, (_base, tex_base, score) in zip(obj_names, pure_results)]


def apply_auto_textures(matches: List[Dict[str, Any]], config: Dict[str, Any],
                         apply_one_fn: Callable[[str, str, Dict[str, str]], None],
                         progress_cb: Optional[Callable[[int, int, str], bool]] = None,
                         log_fn: Optional[Callable[[str], None]] = None
                         ) -> Tuple[int, int]:
    log = log_fn or _log_print
    applied = skipped = 0
    total = len(matches)
    for i, m in enumerate(matches):
        if progress_cb and progress_cb(i, total, m["obj"]):
            break
        if not m["tex_base"]:
            skipped += 1
            continue
        channel_files = {mid: ch["file"] for mid, ch in m["channels"].items() if ch["enabled"]}
        if not channel_files:
            skipped += 1
            continue
        mat_basename = _mesh_base_name(m["obj"], config["mesh_prefixes"])
        log(f"[TextureAutoloader] Applying {len(channel_files)} channel(s) to: {m['obj']}")
        apply_one_fn(m["obj"], mat_basename, channel_files)
        applied += 1
    if progress_cb:
        progress_cb(total, total, "")
    log(f"[TextureAutoloader] Auto-Loader batch complete — {applied} object(s) applied, "
        f"{skipped} skipped out of {total} total.")
    return applied, skipped


# ══════════════════════════════════════════════════════════════
#  Estado de sesión (no persistido en el .blend a propósito)
# ══════════════════════════════════════════════════════════════

_TEX_MAP: Dict[str, List[str]] = {}
_MATCHES: List[Dict[str, Any]] = []


# ══════════════════════════════════════════════════════════════
#  BLENDER — WIRING (Principled BSDF)
# ══════════════════════════════════════════════════════════════

_MAT_NAME_RE = re.compile(r'^M_.+_TXA\d*$')


def _find_autoloader_material(obj: "bpy.types.Object") -> Optional["bpy.types.Material"]:
    for slot in obj.material_slots:
        if slot.material and _MAT_NAME_RE.match(slot.material.name):
            return slot.material
    return None


def has_autoloader_material(obj: "bpy.types.Object") -> bool:
    return _find_autoloader_material(obj) is not None


def _get_assigned_material_name(obj: "bpy.types.Object") -> Optional[str]:
    for slot in obj.material_slots:
        if slot.material is not None:
            return slot.material.name
    return None


def _socket(node: "bpy.types.Node", *names: str) -> Optional["bpy.types.NodeSocket"]:
    for n in names:
        if n in node.inputs:
            return node.inputs[n]
    return None


def _udim_tiles_from_disk(representative_path: str) -> Dict[int, str]:
    pattern = representative_path.replace("<UDIM>", "[0-9][0-9][0-9][0-9]")
    tiles: Dict[int, str] = {}
    for fp in glob.glob(pattern):
        m = re.search(r'(\d{4})', os.path.basename(fp))
        if m:
            tiles[int(m.group(1))] = fp
    return tiles


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
                    pass
        else:
            image = bpy.data.images.load(file_path, check_existing=True)
        try:
            image.colorspace_settings.name = colorspace
        except TypeError:
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
    mat = _find_autoloader_material(obj)
    if not mat:
        return 0
    users = mat.users
    name = mat.name
    try:
        bpy.data.materials.remove(mat, do_unlink=True)
        get_logger().info(
            f"[TextureAutoloader] Cleaned up previous material '{name}' "
            f"(had {users} user(s)) from {obj.name} before rewiring.")
        return 1
    except Exception as e:
        _warn(f"Could not remove previous material '{name}' from {obj.name}: {e}")
        return 0


def process_textures(obj_name: str, mat_basename: str, channel_files: Dict[str, str],
                      config: Dict[str, Any]) -> None:
    obj = bpy.data.objects.get(obj_name)
    if obj is None:
        _warn(f"[TextureAutoloader] Object '{obj_name}' not found in the scene — skipped.")
        return

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

    base_color_node = None
    ao_node = None
    y = 400
    skipped_displacement = 0

    for map_id, file_path in channel_files.items():
        is_udim = "<UDIM>" in file_path

        if map_id == "displacement" and not config.get("enable_displacement_wiring", False):
            skipped_displacement += 1
            continue

        if map_id == "baseColor":
            node = _add_image_node(node_tree, file_path, is_udim, "sRGB", "Base Color", -400, y)
            if node:
                base_color_node = node
                socket = _socket(bsdf, "Base Color")
                if socket:
                    node_tree.links.new(node.outputs["Color"], socket)

        elif map_id == "roughness":
            node = _add_image_node(node_tree, file_path, is_udim, "Non-Color", "Roughness", -400, y)
            if node:
                socket = _socket(bsdf, "Roughness")
                if socket:
                    node_tree.links.new(node.outputs["Color"], socket)

        elif map_id == "metallic":
            node = _add_image_node(node_tree, file_path, is_udim, "Non-Color", "Metallic", -400, y)
            if node:
                socket = _socket(bsdf, "Metallic")
                if socket:
                    node_tree.links.new(node.outputs["Color"], socket)

        elif map_id == "normal":
            node = _add_image_node(node_tree, file_path, is_udim, "Non-Color", "Normal", -600, y)
            if node:
                normal_map = node_tree.nodes.new("ShaderNodeNormalMap")
                normal_map.location = (-350, y)
                node_tree.links.new(node.outputs["Color"], normal_map.inputs["Color"])
                socket = _socket(bsdf, "Normal")
                if socket:
                    node_tree.links.new(normal_map.outputs["Normal"], socket)

        elif map_id == "emission":
            node = _add_image_node(node_tree, file_path, is_udim, "sRGB", "Emission", -400, y)
            if node:
                color_socket = _socket(bsdf, "Emission Color", "Emission")
                if color_socket:
                    node_tree.links.new(node.outputs["Color"], color_socket)
                strength_socket = _socket(bsdf, "Emission Strength")
                if strength_socket:
                    strength_socket.default_value = 1.0

        elif map_id == "ao":
            ao_node = _add_image_node(node_tree, file_path, is_udim, "Non-Color", "AO", -400, y)

        elif map_id == "opacity":
            node = _add_image_node(node_tree, file_path, is_udim, "Non-Color", "Opacity", -400, y)
            if node:
                socket = _socket(bsdf, "Alpha")
                if socket:
                    node_tree.links.new(node.outputs["Color"], socket)
                try:
                    mat.blend_method = 'HASHED'
                except (AttributeError, TypeError):
                    pass

        elif map_id == "displacement":
            node = _add_image_node(node_tree, file_path, is_udim, "Non-Color", "Displacement", -400, y)
            if node:
                disp_node = node_tree.nodes.new("ShaderNodeDisplacement")
                disp_node.location = (150, -300)
                node_tree.links.new(node.outputs["Color"], disp_node.inputs["Height"])
                node_tree.links.new(disp_node.outputs["Displacement"], output.inputs["Displacement"])

        y -= 260

    if ao_node is not None:
        mix_node = node_tree.nodes.new("ShaderNodeMix")
        mix_node.data_type = 'RGBA'
        mix_node.blend_type = 'MULTIPLY'
        mix_node.inputs["Factor"].default_value = 1.0
        mix_node.location = (-150, 400)
        if base_color_node is not None:
            node_tree.links.new(base_color_node.outputs["Color"], mix_node.inputs["A"])
        else:
            mix_node.inputs["A"].default_value = (1.0, 1.0, 1.0, 1.0)
        node_tree.links.new(ao_node.outputs["Color"], mix_node.inputs["B"])
        base_socket = _socket(bsdf, "Base Color")
        if base_socket:
            node_tree.links.new(mix_node.outputs["Result"], base_socket)

    if skipped_displacement:
        _warn(
            f"[TextureAutoloader] {skipped_displacement} displacement/height map(s) "
            f"detected on {obj.name} but NOT wired (enable "
            f"'enable_displacement_wiring' in texture_autoloader_config.json if you "
            f"want them — true displacement also needs Cycles + adaptive "
            f"subdivision to look right).")

    get_logger().info(
        f"[TextureAutoloader] Material '{mat_name}' applied to {obj.name} "
        f"with {len(channel_files)} channel(s) requested.")


# ══════════════════════════════════════════════════════════════
#  PropertyGroup
# ══════════════════════════════════════════════════════════════

def _on_language_update(self, context):
    state = load_state()
    state["language"] = self.language
    save_state(state)


def _on_threshold_update(self, context):
    state = load_state()
    state["last_threshold"] = self.threshold
    save_state(state)


def _on_match_mode_update(self, context):
    state = load_state()
    state["last_match_mode"] = self.match_mode
    save_state(state)


def _on_recursive_update(self, context):
    state = load_state()
    state["last_recursive"] = self.recursive
    save_state(state)


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
        props.language = other_language(props.language)
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
        state = load_state()
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

        folder = bpy.path.abspath(folder)

        if not folder or not os.path.isdir(folder):
            self.report({'WARNING'}, _t("msg_folder_missing", folder=folder or "(empty)"))
            return {'CANCELLED'}

        config = _config()
        _TEX_MAP = scan_texture_folder(
            folder, config["suffix_strip_list"], set(config["texture_extensions"]),
            recursive=props.recursive)
        _MATCHES = []

        total_files = sum(len(v) for v in _TEX_MAP.values())
        props.scan_info = _t("scan_info", sets=len(_TEX_MAP), files=total_files)
        props.match_status = ""

        state = load_state()
        recent = push_recent_folder(state.get("recent_folders", []), folder)
        state["recent_folders"] = recent
        state["last_recursive"] = props.recursive
        save_state(state)

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

        _MATCHES = match_objects_to_textures(
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
            _MATCHES[self.match_index] = build_match_entry(
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
            self.report(
                {'INFO'},
                _t("dialog_existing_materials_body", count=len(conflicts)).replace("\n\n", " "))

        def _apply_one(obj_name: str, mat_basename: str, channel_files: Dict[str, str]) -> None:
            process_textures(obj_name, mat_basename, channel_files, config)

        applied, skipped = apply_auto_textures(
            _MATCHES, config, apply_one_fn=_apply_one, log_fn=_log_print)

        self.report(
            {'INFO'},
            f"{_t('done_body_applied')}: {applied}    {_t('done_body_skipped')}: {skipped}")
        return {'FINISHED'}


class TEXTUREAUTOLOADER_OT_manual_apply(Operator):
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

        buckets, unmatched = bucket_files_by_type(file_paths, config["map_types"])
        resolved = resolve_channel_files(buckets, config, warn_fn=_warn)
        channel_files = {mid: fp for mid, (fp, _is_udim) in resolved.items()}

        process_textures(obj.name, obj.name, channel_files, config)
        if unmatched:
            self.report({'WARNING'}, f"{len(unmatched)} file(s) not recognized and not wired.")
        return {'FINISHED'}


# ══════════════════════════════════════════════════════════════
#  Panel — Sidebar (N-panel) del 3D Viewport
# ══════════════════════════════════════════════════════════════

def _wrapped_label(layout, text: str, width_chars: int = 46) -> None:
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
        header_row.label(text=tr(L, "app_title"), icon='TEXTURE')
        lang_row = header_row.row()
        lang_row.alignment = 'RIGHT'
        lang_row.scale_x = 0.8
        lang_row.operator(
            TEXTUREAUTOLOADER_OT_toggle_language.bl_idname,
            text=tr(other_language(L), "lang_button"))

        layout.separator()

        box = layout.box()
        box.label(text="◆  " + tr(L, "section_manual"))
        _wrapped_label(box, tr(L, "section_manual_desc"))
        box.operator(TEXTUREAUTOLOADER_OT_manual_apply.bl_idname,
                     text=tr(L, "btn_manual_apply"))

        layout.separator()

        box = layout.box()
        box.label(text="✦  " + tr(L, "section_autoloader"))
        _wrapped_label(box, tr(L, "section_autoloader_desc"))

        row = box.row(align=True)
        row.menu(TEXTUREAUTOLOADER_MT_recent_folders.bl_idname,
                 text=tr(L, "recent_label"))

        row = box.row(align=True)
        row.prop(props, "folder", text="")
        row.operator(TEXTUREAUTOLOADER_OT_browse_folder.bl_idname, text="", icon='FILE_FOLDER')
        row.prop(props, "recursive", text=tr(L, "btn_recursive"), toggle=True)

        box.operator(TEXTUREAUTOLOADER_OT_scan_folder.bl_idname,
                     text=tr(L, "btn_browse"), icon='VIEWZOOM')

        if props.scan_info:
            box.label(text=props.scan_info)

        box.prop(props, "threshold", text=tr(L, "sensitivity_label"), slider=True)

        box.label(text=tr(L, "match_by_label"))
        row = box.row(align=True)
        row.prop_enum(props, "match_mode", "object_name", text=tr(L, "match_by_object_name"))
        row.prop_enum(props, "match_mode", "material_id", text=tr(L, "match_by_material_id"))

        info_key = "match_mode_info_material_id" if props.match_mode == "material_id" \
            else "match_mode_info_object_name"
        _wrapped_label(box, tr(L, info_key))

        box.operator(TEXTUREAUTOLOADER_OT_smart_match.bl_idname,
                     text=tr(L, "btn_smart_match"), icon='SHADING_RENDERED')

        if _MATCHES:
            box.label(text=tr(L, "preview_label"))
            preview_col = box.column(align=True)
            for idx, m in enumerate(_MATCHES):
                row = preview_col.box().column(align=True)
                header = row.row(align=True)
                obj_short = m["obj"]
                tex_label = m["tex_base"] if m["tex_base"] else tr(L, "no_match")
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
                    tag = tr(L, "overridden_tag") if ch["overridden"] else (
                        tr(L, "udim_tag") if ch["is_udim"] else "")
                    ch_row.label(text=os.path.basename(ch["file"]) + tag)

            box.label(text=props.match_status)

        box.operator(TEXTUREAUTOLOADER_OT_apply_all.bl_idname,
                     text=tr(L, "btn_apply_all"), icon='PLAY')

        layout.separator()
        footer_row = layout.row()
        footer_row.alignment = 'CENTER'
        footer_row.label(text=tr(L, "footer"))


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
    TEXTUREAUTOLOADER_OT_manual_apply,
    TEXTUREAUTOLOADER_PT_main,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.texture_autoloader = bpy.props.PointerProperty(
        type=TEXTUREAUTOLOADER_PG_properties)
    bpy.types.WindowManager.texture_autoloader_reassign_index = IntProperty(default=-1)

    try:
        state = load_state()
        config = load_config(warn_fn=_warn)
        for scene in bpy.data.scenes:
            props = scene.texture_autoloader
            props.language = state.get("language", config.get("language", DEFAULT_LANGUAGE))
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
