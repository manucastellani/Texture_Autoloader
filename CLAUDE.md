# Texture Autoloader — Contexto del proyecto

## Qué es
Escanea una carpeta con exports de Substance Painter y agrupa las texturas por asset.
Las matchea por nombre (con tolerancia configurable, fuzzy matching) contra los meshes
seleccionados, por nombre de objeto o por el material ya asignado. Arma el shader:
`aiStandardSurface` en Maya/Arnold, Principled BSDF en Blender. Muestra vista previa por
objeto y por canal antes de aplicar. Publicada en GitHub (manucastellani/Texture_Autoloader)
como primer proyecto público, usada como carta de presentación como Technical Artist.
Empezó como "Arnold Node Wrangler" solo para Maya (v1–v4.1); en v5.0 se dividió para
varios DCCs y cambió de nombre.

## Cómo está armado (arquitectura real)
Hay dos versiones de la misma herramienta:
- **Standalone** (`maya/`, `blender/`): un solo archivo por DCC, lo que usa el usuario
  final. Son copias a mano de la versión modular — cada cambio hay que pasarlo a mano.
- **Modular** (`advanced/`): un `core` sin dependencia de ningún DCC (solo librería
  estándar de Python), con normalización de nombres, matching, UDIM, clasificación por
  tipo de mapa, config en JSON, logging y textos EN/ES. Encima van las partes propias de
  Maya (UI en Qt) y Blender, más tests de pytest.

**Decisión de arquitectura para las mejoras**: `dcc_mejoras/` parte de `advanced/`
(la versión modular), no de las standalone. La mayoría de las mejoras pendientes tocan
el `core` compartido, así que conviene mantenerlo unificado en vez de duplicar lógica
en copias separadas de Maya y Blender. El port a Unreal también reutiliza este `core`
para escanear, matchear y agrupar por tipo — solo lo propio de Unreal (import de
assets, Material Slots) se escribe aparte.

## Estado real de cada mejora (en `feature/unreal-port`, verificado con tests)
- **UDIM: probado, con 2 bugs encontrados y corregidos en `dcc_mejoras/`** (los dos
  siguen en `main`):
  - Los tiles con punto (`Pared_BaseColor.1001.png`, el formato por defecto de
    Substance y Mari) quedaban como sets separados y el UDIM nunca se armaba.
  - Blender tomaba como número de tile el primer grupo de 4 dígitos del nombre
    (`Crate2048_BaseColor.1001.png` → tile 2048).
  - Verificado en Maya 2027 + Arnold y en Blender 5.0 / 5.1 (tests de integración).
- **Reporte ✔/✘: HECHO.** `core.build_report`, compartido por Maya, Blender y Unreal:
  ✔ cableado, ✘ sin match / sin input / error, – omitido a propósito (canal
  desactivado, displacement opcional, archivo duplicado). Maya: diálogo final
  ("Show Details…") + Script Editor. Blender: bloque de texto
  `TextureAutoloader_Report` + popup. Unreal: diálogo + Output Log.
- **Presets de naming convention: HECHO.** `naming_presets` en el config + combo en
  Maya y Blender (campo en Unreal). Los presets usan `suffixes` anclados al final del
  nombre (así `_R` no confunde `Car_Rim_BC.png` con roughness); el preset "default" es
  el `map_types` de siempre. Incluye un ejemplo: `short_suffixes`.
- **Thumbnails: DESCARTADOS** (decisión tomada en este chat — complejidad de UI no
  justificada para el tamaño de la herramienta). El README público todavía los anota
  como "próximos pasos razonables" — corregir el README cuando se haga el merge a `main`.
- **Selector de motor de destino (Maya): HECHO para Arnold. Redshift y V-Ray están
  escritos pero SIN PROBAR en un Maya con esos renderers** (en la máquina de desarrollo
  solo está Arnold; sus plantillas se verifican contra el stub de `maya.cmds`).
  Diccionario `ENGINE_TEMPLATES` en `dcc_mejoras/maya/texture_autoloader_maya.py`;
  cada atributo se verifica antes de conectar y, si no existe, sale como ✘ en el
  reporte. Blender no necesita selector (Principled BSDF sirve para Cycles y EEVEE).

## Port a Unreal Engine
- Reutiliza el `core` compartido (`dcc_mejoras/core/`, copia de `advanced/`) para
  escanear, matchear y agrupar texturas por tipo.
- Se implementa vía Unreal Python Editor Scripting API
  (`unreal.MaterialEditingLibrary`, `unreal.AssetToolsHelpers`, etc.).
- **Diferencia clave de arquitectura**: en Unreal no se arma un grafo de nodos por
  objeto. Se usa un **Master Material** con parámetros de textura expuestos, y la
  herramienta crea/actualiza **Material Instances** asignando texturas a esos parámetros
  ("parameter binding", no "wiring").
- El equivalente de "Material ID" es el **Material Slot** de un Static/Skeletal Mesh:
  un mesh con 3 slots necesita 3 sets de texturas. Un FBX importado trae los slots pero
  sin texturas asignadas — Unreal no las aplica solo.
- Diferencias propias de Unreal a resolver:
  - Las texturas hay que importarlas primero como assets — no se referencian por ruta
    de archivo directa, como en Maya/Blender.
  - El flag `raw` del config pasa a ser sRGB desactivado + un compression setting.
- Requiere UI vía Editor Utility Widget o plugin con menú propio.
- **Estado: v1 funcionando en UE 5.7 y 5.8** (`unreal/texture_autoloader_unreal.py`,
  instrucciones en `unreal/README.md`):
  - Cada slot prueba `<mesh>_<slot>` (el `$mesh_$textureSet` de Substance), `<slot>` y
    `<mesh>`; los slots con nombre genérico (`WorldGridMaterial`, `None`) usan el mesh.
  - UI: menú propio (clic derecho en el Content Browser y Tools) + diálogo nativo de
    propiedades (`EditorDialog.show_object_details_view`), no Editor Utility Widget:
    así el repo no lleva `.uasset` binarios. Se instala agregando `<repo>/unreal` en
    Project Settings › Plugins › Python › Additional Paths (corre `init_unreal.py`).
  - Si el Master Material no existe, se genera uno por defecto (+ variante Masked para
    sets con opacidad) con texturas neutras generadas por la herramienta.
  - Pendiente: UDIM (se reporta y se saltea — requiere virtual textures),
    displacement y texturas empaquetadas (ORM).

## Tests (cómo correrlos)
- Ningún Python de los DCCs trae pytest: instalarlo en cualquier Python y correr cada
  suite por separado (comparten nombres de archivo con las de `advanced/`):
  `pytest dcc_mejoras/tests`, `pytest dcc_mejoras/maya/tests`, `pytest unreal/tests`.
- Integración, dentro de cada programa real y sin interfaz:
  - Maya: `mayapy dcc_mejoras/maya/tests/run_in_mayapy.py` (usa Arnold).
  - Blender: `blender -b --factory-startup --python-exit-code 1 --python dcc_mejoras/blender/tests/run_in_blender.py`
  - Unreal: `unreal/tests/run_in_unreal.py` sobre un proyecto descartable (comando en
    `unreal/README.md`; en 5.7 como commandlet hace falta
    `-ini:Engine:[ConsoleVariables]:Interchange.FeatureFlags.Import.PNG=0`).
- Programas instalados en la máquina de desarrollo: Maya 2022 / 2027 (con Arnold),
  Blender 5.0 / 5.1, Unreal 5.7 / 5.8.

## Estado de git (al momento de este documento)
- Rama `feature/unreal-port` creada desde `main` (61076ac), solo local (sin push).
  `main` sin cambios.
- `CLAUDE.md` versionado dentro de la rama (no en `main`).

## Estructura de trabajo del repo

**GARANTÍA PRINCIPAL — no negociable: lo que ya está publicado en `main` no se toca
mientras se prueba el port a Unreal y las demás mejoras.** Prioridad número uno del
flujo de trabajo, por encima de la velocidad o la comodidad de editar.

- Todo el código de prueba vive en la rama `feature/unreal-port`, nunca directo en
  `main`. `main` se actualiza solo mediante un merge explícito cuando algo está probado
  y estable.
- Dentro de esa rama, partiendo de una copia de `advanced/`:
  - `unreal/` → el port nuevo a Unreal Engine, reutilizando `dcc_mejoras/core/`.
  - `dcc_mejoras/core/` → el core compartido (matching, UDIM, presets, reporte,
    selector de motor), un solo lugar para toda la lógica no específica de un DCC.
  - `dcc_mejoras/maya/` y `dcc_mejoras/blender/` → las capas propias de cada DCC sobre
    ese core, con las mejoras aplicadas.
  - Nota a futuro (no urgente): si estos frentes crecen y se vuelven independientes
    entre sí, separar en ramas propias (`feature/unreal-port`,
    `feature/maya-improvements`, `feature/blender-improvements`).
- Datos de prueba pesados/descartables (texturas de test, FBX de prueba, proyecto de
  Unreal de testing) → carpeta local en `.gitignore` (ej. `/sandbox`), nunca
  versionados. Esto es solo para binarios de test, no para código.
- La rama de pruebas puede quedar 100% local (sin `push`) mientras se trabaja. Para
  mostrar avance a otros, se sube explícitamente, idealmente como Pull Request en modo
  Draft.

## Pendiente de corregir al momento del merge
- README público: sacar la mención a thumbnails como "próximos pasos" (se descartaron)
  y documentar las mejoras nuevas y el port a Unreal.
- Los fixes hechos en `dcc_mejoras/` también corrigen bugs que están en `main`: UDIM
  con punto, número de tile en Blender, `.log` vacío (hacía fallar un test) y
  displacement leído sin `alphaIsLuminance`. Hay que portarlos a `advanced/` y a los
  standalone (`maya/`, `blender/`), que son copias a mano.
- Decidir la estructura final: si `dcc_mejoras/` reemplaza a `advanced/` y si el port
  pasa a `advanced/unreal/` (hoy apunta a `../dcc_mejoras/core`).
- Probar Redshift y V-Ray en un Maya con esos renderers antes de publicarlos.
