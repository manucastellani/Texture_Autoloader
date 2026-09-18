"""
Texture Autoloader — Maya front-end (Arnold / Redshift / V-Ray)
================================================================
Author: Manuel Castellani
Desc  : Substance texture auto-loader for Maya. Scans a folder,
        matches meshes to texture sets by name (fuzzy matching), and
        wires a new shader per object for the chosen render engine —
        aiStandardSurface, RedshiftStandardMaterial or VRayMtl (see
        ENGINE_TEMPLATES).

This file only contains what's genuinely specific to Maya: the actual
shading-node wiring, and the Qt/PySide UI. All naming/matching
logic (string normalization, fuzzy matching, UDIM collapsing, config and
state persistence, and the EN/ES translation table) lives in
`core/texture_autoloader_core.py`, one folder up, shared with the
Blender front-end — see that file's docstring for the reasoning.

This is the modular build, meant for keeping the matching logic shared
and automatically tested alongside the Blender version. If you just
want to paste this into Maya's Script Editor and have it run
immediately, with no sibling folder to locate, use
`maya/texture_autoloader_maya_standalone.py` in the parent
TextureAutoloader folder instead — that file inlines everything and has
no `core/` dependency at all.

---------------------------------------------------------------------
Changelog (this tool used to be a single Maya-only script called
"Arnold Node Wrangler"; the version history below is kept for context):

v5.1 (dcc_mejoras, in testing):
  - Render engine selector: Arnold, Redshift or V-Ray, as one template
    per engine (ENGINE_TEMPLATES) instead of hardcoded Arnold wiring.
    Every attribute is checked before connecting.
  - ✔/✘ report after every run (done dialog "Show Details…" + Script
    Editor), manual mode included.
  - Naming presets (Settings card) for studio suffix conventions.
  - Fixes: UDIM tiles named Name.1001.png were split into separate sets;
    opt-in displacement read outAlpha without alphaIsLuminance (constant
    height on maps with no alpha channel).

v5.0 — Texture Autoloader:
  - Renamed from "Arnold Node Wrangler" to "Texture Autoloader" — the
    name now describes what the tool does rather than a single renderer,
    which matters now that the same logic also ships as a Blender addon.
  - Split into core (DCC-agnostic) + this Maya front-end. No functional
    change to matching/wiring behavior versus v4.1 — same threshold,
    same Material ID matching with its object-name fallback, same UDIM
    handling, same conservative displacement gating.
  - Bilingual UI (English / Spanish) with a small language toggle button
    in the header's top-right corner. Defaults to English so the tool
    reads cleanly for the wider (mostly English-speaking) technical
    artist community; the choice persists per session like the other
    preferences.

v4.1 (as Arnold Node Wrangler):
  - Logging persisted to texture_autoloader.log (was nodewrangler.log),
    with rotation.
  - Removed the silent background `pip install rapidfuzz` — see
    core.ensure_rapidfuzz() docstring.
  - Bundled pytest suite (moved to maya/tests/ and tests/ in this repo).

v4.0 (as Arnold Node Wrangler):
  - Adjustable match threshold from the UI (0-100% sensitivity slider).
  - Material ID matching mode, mutually exclusive with object-name
    matching via two separate buttons, with a persistent inline
    explanation box instead of long tooltips. Falls back to object-name
    matching automatically when the mesh has no material of its own.
  - Taller window so "APPLY TO ALL MATCHES" is visible without scrolling.

v3.1: taller default window; native OS tree-arrow expand/collapse;
simplified non-editable recent-folders dropdown (last 5, no re-scan on
open).

v3.0: per-object channel tree (enable/disable individual maps), manual
per-channel file replacement via double-click, "remove selected" from
the preview, and remembering the last folder/recursive state between
sessions (in a separate state file from the shared config).

Hotfix v2.3: displacement is detected but NOT wired by default — it
deforms render geometry, and wiring it blindly without a hand-tuned
scale/subdivision leaves objects looking inflated. Turn on
`enable_displacement_wiring` in the config to opt in.

Hotfix v2.2: UDIM detection is bounded to tile numbers 1001-1999 with a
denylist of common resolution suffixes (1024, 2048, 4096, 8192...) so
two same-map exports at different resolutions never get misread as UDIM
tiles (which used to break Arnold's uvTilingMode and produce a moiré
pattern on repeated UVs).
---------------------------------------------------------------------
"""

import html
import os
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

_cached_this_dir: Optional[str] = None


def _resolve_this_dir() -> str:
    global _cached_this_dir
    if _cached_this_dir:
        return _cached_this_dir

    try:
        _cached_this_dir = os.path.dirname(os.path.abspath(__file__))
        return _cached_this_dir
    except NameError:
        pass

    # Pegado directo en el Script Editor: no hay __file__ posible. Le
    # pedimos al usuario, una sola vez, dónde está la carpeta del repo.
    result = cmds.fileDialog2(
        fileMode=3, dialogStyle=2,
        caption="Texture Autoloader: select the 'maya' folder inside TextureAutoloader/advanced")
    if not result:
        raise RuntimeError(
            "Texture Autoloader could not locate its own folder (this happens when "
            "the script is pasted directly into the Script Editor instead of "
            "imported). Either run it with:\n"
            "    import texture_autoloader_maya as ta\n"
            "    ta.create_ui()\n"
            "(after adding the 'advanced/maya' folder to Maya's script path), or pick "
            "the 'advanced/maya' folder in the dialog when prompted. If you just want "
            "to paste-and-run with no dialog at all, use "
            "maya/texture_autoloader_maya_standalone.py instead.")
    _cached_this_dir = result[0]
    return _cached_this_dir


_THIS_DIR = _resolve_this_dir()
_CORE_DIR = os.path.join(os.path.dirname(_THIS_DIR), "core")
if _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)

import texture_autoloader_core as core  # noqa: E402  (needs the sys.path fix above)


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
        core.get_logger(_app_dir()).warning(message)
    except Exception:
        pass


def _log_print(message: str) -> None:
    """Como print(), pero además registra el mensaje en
    texture_autoloader.log a nivel INFO."""
    print(message)
    try:
        core.get_logger(_app_dir()).info(message)
    except Exception:
        pass


if not core.HAS_RAPIDFUZZ:
    _warn(
        "[TextureAutoloader] rapidfuzz is not installed — using the internal "
        "difflib fallback for fuzzy matching. This is not an error: it only "
        "lowers precision a bit on very different-looking names.")


# ══════════════════════════════════════════════════════════════
#  MAYA / ARNOLD — WIRING
# ══════════════════════════════════════════════════════════════

import re

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
            core.get_logger(_app_dir()).info(
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
MAYA_DEFAULT_CONFIG: Dict[str, Any] = dict(core.DEFAULT_CONFIG, render_engine=DEFAULT_ENGINE)


def _load_config() -> Dict[str, Any]:
    return core.load_config(_app_dir(), warn_fn=_warn, defaults=MAYA_DEFAULT_CONFIG)


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
                            language: str = core.DEFAULT_LANGUAGE,
                            engine: Optional[str] = None) -> Optional[str]:
    """Modo manual: aplica archivos elegidos a mano al objeto seleccionado.
    Devuelve el reporte ✔/✘ (o None si se canceló la selección)."""
    config = config or _load_config()
    selected_obj = get_selected_mesh()
    if not selected_obj:
        return None
    file_paths = cmds.fileDialog2(
        fileMode=4, dialogStyle=2,
        caption=core.tr(language, "select_files_dialog"),
        fileFilter="Images (*.png *.jpg *.jpeg *.tga *.exr *.tif *.tiff)"
    )
    if not file_paths:
        return None

    label = core.tex_base_name(os.path.basename(file_paths[0]), config["suffix_strip_list"])
    entry = core.build_entry_from_files(selected_obj, label, file_paths, config, warn_fn=_warn)
    channel_files = {mid: ch["file"] for mid, ch in entry["channels"].items()}
    cmds.undoInfo(openChunk=True)
    try:
        entry["result"] = process_textures(
            None, selected_obj, mat_basename=core.mesh_base_name(selected_obj, config["mesh_prefixes"]),
            config=config, channel_files=channel_files, engine=engine)
        entry["status"] = "applied"
    except Exception as e:
        entry["status"], entry["error"] = "error", str(e)
        _warn(f"[TextureAutoloader] {selected_obj}: {e}")
    finally:
        cmds.undoInfo(closeChunk=True)

    report = core.build_report([entry], language)
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

    Devuelve un core.new_apply_result(): qué canal quedó cableado, cuál
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

    result = core.new_apply_result(material=mat_name)

    if channel_files is not None:
        resolved: Dict[str, Tuple[str, bool]] = {
            mid: (fp, "<UDIM>" in fp) for mid, fp in channel_files.items()}
        unmatched: List[str] = []
    else:
        buckets, unmatched = core.bucket_files_by_type(file_paths or [], map_types)
        resolved = core.resolve_channel_files(buckets, config, warn_fn=_warn)

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

    core.get_logger(_app_dir()).info(
        f"[TextureAutoloader] Material '{mat_name}' applied to {selected_obj.split('|')[-1]} "
        f"with {len(result['wired'])} channel(s) wired "
        f"({', '.join(sorted(result['wired'])) or 'none'}).")

    return result


# ── Auto-Loader: scan + match + apply ──────────────────────────

def scan_folder(folder: str, config: Dict[str, Any], recursive: bool = False) -> Dict[str, List[str]]:
    return core.scan_texture_folder(folder, config["suffix_strip_list"],
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

    return core.match_objects_to_textures(
        object_entries, tex_map, config, match_mode=match_mode, warn_fn=_warn)


def apply_auto_textures(matches: List[Dict[str, Any]],
                         config: Dict[str, Any],
                         progress_cb=None,
                         engine: Optional[str] = None) -> Tuple[int, int]:
    def _apply_one(obj: str, mat_basename: str, channel_files: Dict[str, str]) -> Dict[str, Any]:
        return process_textures(None, obj, mat_basename=mat_basename,
                                config=config, channel_files=channel_files, engine=engine)

    return core.apply_auto_textures(
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
        self.setMinimumHeight(1100)
        self.resize(640, 1220)

        self.config: Dict[str, Any] = _load_config()
        self.state: Dict[str, Any] = core.load_state(_app_dir())
        self.folder: Optional[str] = None
        self.tex_map: Dict[str, List[str]] = {}
        self.matches: List[Dict[str, Any]] = []
        self.match_mode: str = "object_name"
        self.language: str = self.state.get(
            "language", self.config.get("language", core.DEFAULT_LANGUAGE))
        self.naming_preset: str = core.apply_naming_preset(
            self.config,
            self.state.get("last_naming_preset",
                           self.config.get("naming_preset", core.DEFAULT_PRESET_ID)),
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

    # ── i18n ──────────────────────────────────────────────────

    def _t(self, key: str, **kwargs) -> str:
        return core.tr(self.language, key, **kwargs)

    def _cfg(self) -> Dict[str, Any]:
        """Config efectivo: el de disco + el preset de nombres elegido
        (y el threshold del slider, que vive en self.config)."""
        return core.apply_naming_preset(self.config, self.naming_preset)

    def _on_toggle_language(self) -> None:
        self.language = core.other_language(self.language)
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
        self.btn_language.setText(core.tr(core.other_language(L), "lang_button"))
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
        core.save_state(_app_dir(), self.state)

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
        for preset_id, label in core.list_naming_presets(self.config, self.language):
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

        recent = core.push_recent_folder(self.state.get("recent_folders", []), folder)
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
        self.matches[match_idx] = core.build_match_entry(
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

        report = core.build_report(self.matches, self.language, tex_map=self.tex_map)
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
