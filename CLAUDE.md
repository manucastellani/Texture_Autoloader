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

## Estado real de cada mejora (verificado contra el código, no asumido)
- **UDIM: YA IMPLEMENTADO.** El core detecta tiles 1001–1999 y excluye sufijos de
  resolución (1024, 2048...). Configurado en `texture_autoloader_maya.py:428` (Maya) y
  `texture_autoloader_blender.py:199` (Blender). Falta más testing, sobre todo en
  Blender — no falta implementarlo.
- **Presets de naming convention: PARCIAL.** `map_types` y `suffix_strip_list` ya se
  leen desde `texture_autoloader_config.json` (`core:253`), o sea que la convención ya
  es configurable. Lo que falta es la capa de presets: varias convenciones guardadas
  con nombre para elegir entre ellas, en vez de editar el JSON a mano.
- **Reporte de matching: PARCIAL.** Hoy solo se loguean los archivos que no se
  reconocieron (`texture_autoloader_maya.py:462`). Falta ampliarlo a un reporte
  ✔/✘ completo (matches exitosos + fallidos).
- **Thumbnails: DESCARTADOS** (decisión tomada en este chat — complejidad de UI no
  justificada para el tamaño de la herramienta). El README público todavía los anota
  como "próximos pasos razonables" — corregir el README cuando se haga el merge a `main`.
- **Selector de motor de destino: NO EXISTE todavía.** `aiStandardSurface` está fijo en
  el código (`texture_autoloader_maya.py:393`). Esto sigue siendo una mejora real
  pendiente, no implementada.

## Port a Unreal Engine
- Reutiliza el `core` de `advanced/` para escanear, matchear y agrupar texturas por tipo.
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

## Estado de git (al momento de este documento)
- Solo existe `main`. La rama `feature/unreal-port` todavía no se creó.
- `CLAUDE.md` todavía no está trackeado por git. **Decisión pendiente de confirmar**:
  se agrega dentro de la rama `feature/unreal-port` (no a `.gitignore`, no directo a
  `main`) — así queda versionado pero aislado hasta el merge, igual que el resto del
  trabajo de prueba.

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
- README público: sacar la mención a thumbnails como "próximos pasos" (se descartaron).
