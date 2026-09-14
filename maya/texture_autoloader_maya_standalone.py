"""
Texture Autoloader — Maya / Arnold (STANDALONE, single-file build)
====================================================================
Author: Manuel Castellani

This is a self-contained, single-file build meant to be copy-pasted
directly into Maya's Script Editor (Python tab) and run — no folder to
pick, no sys.path setup, no sibling files needed. Everything that
normally lives in `core/texture_autoloader_core.py` (naming, fuzzy
matching, UDIM handling, config/state, i18n) is inlined below, right
next to the Maya/Arnold wiring and the Qt UI.

Why this file exists separately from `texture_autoloader_maya.py`:
that other version imports a shared `core/` module so the exact same
matching logic and translation table can also power the Blender addon
in this repo, and so both have one automated test suite instead of two.
That's the right architecture to develop and test against — but it
means the file can't be pasted in isolation (Python needs to find the
sibling `core/` folder on disk, and pasted code has no reliable way to
know where it's running from). If you want that version, see
`texture_autoloader_maya.py` and `install_shelf_button.py` instead.

This standalone build trades that shared architecture for the simplest
possible install story: paste this file's contents into the Script
Editor, hit run, and `create_ui()` opens automatically. Config, state,
and the log file live in Maya's own per-user preferences folder
(`<Maya app dir>/TextureAutoloader/`) instead of "next to the script",
since a pasted script has no folder of its own to keep them in — that's
also exactly how this tool behaved as "Arnold Node Wrangler" before the
core/Maya/Blender split, so it's a well-tested fallback, not a new
untested code path.

Keeping this file's logic in sync with core/texture_autoloader_core.py
is a manual step when one changes — that duplication is the accepted
cost of a true drop-in single-file script. If you're extending the
matching logic, do it in core/ first (it has an automated test suite)
and port the change here.
"""

import os
import re
import json
import difflib
import logging
import logging.handlers
from typing import Optional, List, Dict, Tuple, Callable, Any

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
#  ARCHIVOS DE SOPORTE — config / state / log
#  Pegado en el Script Editor, este script no tiene una carpeta propia
#  en disco (Maya compila el texto pegado con un nombre de archivo
#  falso, "<maya console>", así que __file__ no existe). En vez de
#  pedirle al usuario que elija una carpeta, usamos directamente la
#  carpeta de preferencias de Maya — exactamente el mismo fallback que
#  ya tenía esta herramienta en versiones anteriores a la separación en
#  core/maya/blender, así que no es un camino nuevo sin probar.
# ══════════════════════════════════════════════════════════════

def _app_dir() -> str:
    try:
        base = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        base = os.path.join(cmds.internalVar(userAppDir=True), "TextureAutoloader")
    try:
        os.makedirs(base, exist_ok=True)
    except Exception:
        base = os.path.expanduser("~")
    return base


CONFIG_FILENAME = "texture_autoloader_config.json"
STATE_FILENAME = "texture_autoloader_state.json"
LOG_FILENAME = "texture_autoloader.log"

_logger_instance: Optional["logging.Logger"] = None


def get_logger() -> "logging.Logger":
    global _logger_instance
    if _logger_instance is not None:
        return _logger_instance

    logger = logging.getLogger("TextureAutoloaderStandalone")
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
    cmds.warning(message)
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
    },
}


def tr(language: str, key: str, **kwargs) -> str:
    lang_table = TRANSLATIONS.get(language, TRANSLATIONS[DEFAULT_LANGUAGE])
    text = lang_table.get(key, TRANSLATIONS[DEFAULT_LANGUAGE].get(key, key))
    return text.format(**kwargs) if kwargs else text


def other_language(language: str) -> str:
    return "es" if language == "en" else "en"


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
}


def _deep_merge_defaults(loaded: Dict[str, Any], defaults: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(defaults)
    merged.update({k: v for k, v in loaded.items() if k in defaults})
    return merged


def load_config() -> Dict[str, Any]:
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
        _warn(f"[TextureAutoloader] Could not read {path} ({e}) — using default config.")
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


# ══════════════════════════════════════════════════════════════
#  DEPENDENCIA OPCIONAL (rapidfuzz)
# ══════════════════════════════════════════════════════════════

def _ensure_rapidfuzz() -> Tuple[Optional[Any], bool]:
    try:
        from rapidfuzz import fuzz
        return fuzz, True
    except ImportError:
        return None, False


_FUZZ, _HAS_RAPIDFUZZ = _ensure_rapidfuzz()
if not _HAS_RAPIDFUZZ:
    _warn(
        "[TextureAutoloader] rapidfuzz is not installed — using the internal "
        "difflib fallback for fuzzy matching. This is not an error: it only "
        "lowers precision a bit on very different-looking names.")


# ══════════════════════════════════════════════════════════════
#  PURO — SIN maya.cmds
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


_MATERIAL_SUFFIX_RE = re.compile(r'[_]?(mat|material|shader|sg)$', re.I)


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
    if _HAS_RAPIDFUZZ:
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


def _collapse_udim_set(file_paths: List[str]) -> Tuple[str, bool]:
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
        _warn(
            f"[TextureAutoloader] {len(file_paths)} files match the same map "
            f"type and don't look like UDIM tiles — using only: "
            f"{os.path.basename(file_paths[0])}")
        return file_paths[0], False

    key = max(udim_groups, key=lambda k: len(udim_groups[k]))
    d, prefix, sep, ext = key
    representative = os.path.join(d, f"{prefix}{sep}<UDIM>{ext}")
    return representative, True


def resolve_channel_files(buckets: Dict[str, List[str]], config: Dict[str, Any]
                           ) -> Dict[str, Tuple[str, bool]]:
    resolved: Dict[str, Tuple[str, bool]] = {}
    for map_id, files in buckets.items():
        if config.get("enable_udim_detection", True):
            representative, is_udim = _collapse_udim_set(files)
        else:
            representative, is_udim = files[0], False
            if len(files) > 1:
                _warn(
                    f"[TextureAutoloader] {len(files)} files match the map "
                    f"'{map_id}' — UDIM detection is disabled, using only: "
                    f"{os.path.basename(files[0])}")
        resolved[map_id] = (representative, is_udim)
    return resolved


def build_match_entry(obj: str, tex_base: Optional[str], score: float,
                       tex_map: Dict[str, List[str]], config: Dict[str, Any]
                       ) -> Dict[str, Any]:
    channels: Dict[str, Dict[str, Any]] = {}
    if tex_base and tex_base in tex_map:
        buckets, _unmatched = bucket_files_by_type(tex_map[tex_base], config["map_types"])
        resolved = resolve_channel_files(buckets, config)
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


# ══════════════════════════════════════════════════════════════
#  MAYA / ARNOLD — CABLEADO
# ══════════════════════════════════════════════════════════════

_MAT_NAME_RE = re.compile(r'^M_.+_MAT\d*$')
_DEFAULT_SHADERS = {"lambert1", "standardSurface1", "particleCloud1"}
_DEFAULT_SHADING_GROUPS = {"initialShadingGroup", "initialParticleSE"}


def create_texture_node(file_path: str, node_name_prefix: str) -> str:
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
    try:
        if is_raw:
            cmds.setAttr(f"{file_node}.ignoreColorSpaceFileRules", True)
        cmds.setAttr(f"{file_node}.colorSpace", color_space, type="string")
    except Exception:
        _warn(f"No se pudo establecer el color space '{color_space}' en {file_node}.")


def _find_autoloader_shader(obj: str) -> Optional[str]:
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
            get_logger().info(
                f"[TextureAutoloader] Cleaned up {obj.split('|')[-1]}: "
                f"{removed} node(s) from the previous material removed before rewiring.")
        return removed
    except Exception as e:
        _warn(f"No se pudo limpiar el material anterior de {obj}: {e}")
        return 0


def _wire_map_type(map_id: str, fn: str, mat_name: str, sg_name: str,
                    created_nodes: Dict[str, str], stem: str) -> None:
    if map_id == "baseColor":
        cmds.connectAttr(f"{fn}.outColor", f"{mat_name}.baseColor", force=True)
        created_nodes['baseColor'] = fn

    elif map_id == "roughness":
        cmds.setAttr(f"{fn}.alphaIsLuminance", True)
        cmds.connectAttr(f"{fn}.outAlpha", f"{mat_name}.specularRoughness", force=True)

    elif map_id == "metallic":
        cmds.setAttr(f"{fn}.alphaIsLuminance", True)
        cmds.connectAttr(f"{fn}.outAlpha", f"{mat_name}.metalness", force=True)

    elif map_id == "normal":
        bump_node = cmds.shadingNode('bump2d', asUtility=True, name=f"{stem}_bump2d")
        cmds.setAttr(f"{bump_node}.bumpInterp", 1)  # Tangent Space
        try:
            cmds.connectAttr(f"{fn}.outAlpha", f"{bump_node}.bumpValue", force=True)
        except Exception:
            cmds.connectAttr(f"{fn}.outColorR", f"{bump_node}.bumpValue", force=True)
        cmds.connectAttr(f"{bump_node}.outNormal", f"{mat_name}.normalCamera", force=True)

    elif map_id == "emission":
        cmds.setAttr(f"{mat_name}.emission", 1.0)
        cmds.connectAttr(f"{fn}.outColor", f"{mat_name}.emissionColor", force=True)

    elif map_id == "ao":
        created_nodes['ao'] = fn

    elif map_id == "displacement":
        disp_node = cmds.shadingNode('displacementShader', asShader=True,
                                      name=f"{stem}_dispShader")
        try:
            cmds.connectAttr(f"{fn}.outAlpha", f"{disp_node}.displacement", force=True)
        except Exception:
            cmds.connectAttr(f"{fn}.outColorR", f"{disp_node}.displacement", force=True)
        cmds.connectAttr(f"{disp_node}.displacement", f"{sg_name}.displacementShader", force=True)

    elif map_id == "opacity":
        cmds.connectAttr(f"{fn}.outColor", f"{mat_name}.opacity", force=True)


def get_selected_mesh() -> Optional[str]:
    selection = cmds.ls(selection=True)
    if not selection:
        _warn("No hay ningún objeto seleccionado.")
        return None
    return selection[0]


def load_textures_and_apply(config: Optional[Dict[str, Any]] = None) -> None:
    config = config or load_config()
    selected_obj = get_selected_mesh()
    if not selected_obj:
        return
    file_paths = cmds.fileDialog2(
        fileMode=4, dialogStyle=2,
        caption="Seleccionar Texturas de Substance",
        fileFilter="Images (*.png *.jpg *.jpeg *.tga *.exr *.tif *.tiff)"
    )
    if not file_paths:
        return
    cmds.undoInfo(openChunk=True)
    try:
        process_textures(file_paths, selected_obj, config=config)
    finally:
        cmds.undoInfo(closeChunk=True)


def process_textures(file_paths: Optional[List[str]], selected_obj: str,
                      mat_basename: Optional[str] = None,
                      config: Optional[Dict[str, Any]] = None,
                      channel_files: Optional[Dict[str, str]] = None) -> int:
    config = config or load_config()
    map_types = config["map_types"]

    _cleanup_existing_material(selected_obj)

    name = f"M_{mat_basename}_MAT" if mat_basename else "M_Substance_Arnold_01"
    mat_name = cmds.shadingNode('aiStandardSurface', asShader=True, name=name)
    sg_name = cmds.sets(renderable=True, noSurfaceShader=True, empty=True,
                         name=f"{mat_name}SG")
    cmds.connectAttr(f"{mat_name}.outColor", f"{sg_name}.surfaceShader", force=True)

    try:
        cmds.sets(selected_obj, forceElement=sg_name)
    except Exception:
        _warn(f"No se pudo asignar el material al objeto {selected_obj}.")
        return len(file_paths or [])

    if channel_files is not None:
        resolved: Dict[str, Tuple[str, bool]] = {
            mid: (fp, "<UDIM>" in fp) for mid, fp in channel_files.items()}
        unmatched: List[str] = []
    else:
        buckets, unmatched = bucket_files_by_type(file_paths or [], map_types)
        resolved = resolve_channel_files(buckets, config)

    created_nodes: Dict[str, str] = {}
    skipped_displacement = 0
    for mt in map_types:
        if mt["id"] not in resolved:
            continue
        representative, is_udim = resolved[mt["id"]]

        if mt["id"] == "displacement" and not config.get("enable_displacement_wiring", False):
            skipped_displacement += 1
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
            _wire_map_type(mt["id"], fn, mat_name, sg_name, created_nodes, stem)
        except Exception as e:
            _warn(f"Error procesando mapa '{mt['id']}': {e}")

    if 'ao' in created_nodes:
        try:
            ao_node = created_nodes['ao']
            mult = cmds.shadingNode('multiplyDivide', asUtility=True,
                                     name="AO_BaseColor_Multiply")
            if 'baseColor' in created_nodes:
                bc = created_nodes['baseColor']
                cmds.disconnectAttr(f"{bc}.outColor", f"{mat_name}.baseColor")
                cmds.connectAttr(f"{bc}.outColor", f"{mult}.input1", force=True)
            else:
                cmds.setAttr(f"{mult}.input1X", 1.0)
                cmds.setAttr(f"{mult}.input1Y", 1.0)
                cmds.setAttr(f"{mult}.input1Z", 1.0)
            cmds.connectAttr(f"{ao_node}.outColor", f"{mult}.input2", force=True)
            cmds.connectAttr(f"{mult}.output", f"{mat_name}.baseColor", force=True)
        except Exception as e:
            _warn(f"Error configurando multiplicador de AO: {e}")

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

    get_logger().info(
        f"[TextureAutoloader] Material '{mat_name}' applied to {selected_obj.split('|')[-1]} "
        f"with {len(created_nodes)} primary channel(s) wired "
        f"({', '.join(sorted(created_nodes.keys())) or 'none'}).")

    return len(unmatched)


# ── Auto-Loader: scan + match + apply ──────────────────────────

def scan_folder(folder: str, config: Dict[str, Any], recursive: bool = False) -> Dict[str, List[str]]:
    return scan_texture_folder(folder, config["suffix_strip_list"],
                                set(config["texture_extensions"]), recursive)


def match_objects_to_textures(objects: List[str], tex_map: Dict[str, List[str]],
                               config: Dict[str, Any],
                               match_mode: str = "object_name") -> List[Dict[str, Any]]:
    mesh_prefixes = config["mesh_prefixes"]
    threshold = config["match_threshold"]

    valid_objs = []
    obj_bases: List[str] = []
    for obj in objects:
        sh = cmds.listRelatives(obj, shapes=True) or []
        if not (sh and cmds.nodeType(sh[0]) == "mesh"):
            _warn(f"[TextureAutoloader] '{obj}' no es un mesh — se omite del matching.")
            continue
        valid_objs.append(obj)
        base = None
        if match_mode == "material_id":
            assigned = _get_assigned_material_name(obj)
            if assigned:
                base = _material_base_name(assigned, mesh_prefixes)
        if not base:
            base = _mesh_base_name(obj, mesh_prefixes)
        obj_bases.append(base)

    pure_results = _compute_matches(obj_bases, list(tex_map.keys()), threshold)

    return [build_match_entry(obj, tex_base, score, tex_map, config)
            for obj, (_base, tex_base, score) in zip(valid_objs, pure_results)]


def apply_auto_textures(matches: List[Dict[str, Any]],
                         config: Dict[str, Any],
                         progress_cb: Optional[Callable[[int, int, str], bool]] = None
                         ) -> Tuple[int, int]:
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
        _log_print(f"[TextureAutoloader] Applying {len(channel_files)} channel(s) to: "
                   f"{m['obj'].split('|')[-1]}")
        process_textures(None, m["obj"],
                          mat_basename=_mesh_base_name(m["obj"], config["mesh_prefixes"]),
                          config=config, channel_files=channel_files)
        applied += 1
    if progress_cb:
        progress_cb(total, total, "")
    _log_print(
        f"[TextureAutoloader] Auto-Loader batch complete — {applied} object(s) applied, "
        f"{skipped} skipped out of {total} total.")
    return applied, skipped


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
        self.setMinimumHeight(1100)
        self.resize(640, 1220)

        self.config: Dict[str, Any] = load_config()
        self.state: Dict[str, Any] = load_state()
        self.folder: Optional[str] = None
        self.tex_map: Dict[str, List[str]] = {}
        self.matches: List[Dict[str, Any]] = []
        self.match_mode: str = "object_name"
        self.language: str = self.state.get(
            "language", self.config.get("language", DEFAULT_LANGUAGE))

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

    # ── i18n ──────────────────────────────────────────────────

    def _t(self, key: str, **kwargs) -> str:
        return tr(self.language, key, **kwargs)

    def _on_toggle_language(self) -> None:
        self.language = other_language(self.language)
        self.state["language"] = self.language
        self._persist_state()
        self._retranslate_ui()

    def _retranslate_ui(self) -> None:
        L = self.language
        self.setWindowTitle(self._t("app_title").title())
        self.lbl_header_title.setText(self._t("app_title"))
        self.lbl_header_subtitle.setText(self._t("app_subtitle"))
        self.btn_language.setText(tr(other_language(L), "lang_button"))
        self.btn_language.setToolTip(self._t("lang_button_tooltip"))

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
        save_state(self.state)

    # ── Handlers ─────────────────────────────────────────────

    def _on_manual_apply(self) -> None:
        load_textures_and_apply(self.config)

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
            self.tex_map = scan_folder(folder, self.config, recursive)
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

        self.matches = match_objects_to_textures(sel, self.tex_map, self.config,
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
            m["obj"], new_base, 1.0 if new_base else 0.0, self.tex_map, self.config)
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
            applied, skipped = apply_auto_textures(self.matches, self.config, progress_cb=_cb)
        finally:
            cmds.undoInfo(closeChunk=True)
            progress.setValue(len(self.matches))

        msg = QtWidgets.QMessageBox(self)
        msg.setWindowTitle(self._t("done_title"))
        msg.setText(
            f"<div style='font-family:Segoe UI; color:#E8E8EA;'>"
            f"<p style='font-size:13px;'><b>{self._t('done_title')}</b></p>"
            f"<p>{self._t('done_body_applied')}: <span style='color:#2ED573;'>{applied}</span></p>"
            f"<p>{self._t('done_body_skipped')}: <span style='color:#FFB547;'>{skipped}</span></p>"
            f"</div>"
        )
        msg.setStandardButtons(QtWidgets.QMessageBox.Ok)
        msg.exec_()


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
create_ui()
