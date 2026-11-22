# Texture Autoloader — Contexto del proyecto

## Qué es
Escanea una carpeta con exports de Substance Painter y agrupa las texturas por asset.
Las matchea por nombre (fuzzy, con sensibilidad ajustable) contra lo seleccionado, por
nombre de objeto o por el material ya asignado, muestra una vista previa por objeto y
por canal, arma el shader y reporta qué pasó con cada archivo. Publicada en GitHub
(manucastellani/Texture_Autoloader) como primer proyecto público, usada como carta de
presentación como Technical Artist. Empezó como "Arnold Node Wrangler" solo para Maya
(v1–v4.1); en v5.0 se dividió para varios DCCs y cambió de nombre.

## Cómo está armado
- **`advanced/` es la fuente de verdad.** Un `core` sin dependencia de ningún DCC (solo
  librería estándar) con normalización de nombres, matching, UDIM, tipos de mapa,
  presets, reporte, config/estado, logging y los textos EN/ES. Encima, lo propio de cada
  aplicación: Maya (Qt + plantillas de motor) y Blender (panel + Principled BSDF).
- **`maya/` y `blender/` son generados**, no copias a mano: `python build_standalone.py`
  los produce desde `advanced/`, y `--check` falla si quedaron viejos. Antes se copiaban
  a mano y divergieron (había arreglos que existían solo en un lado). **No editarlos
  directamente.**
- **`unreal/`** es el port a Unreal, que reutiliza `advanced/core`.
- **`tests/`**: tests de integración que corren dentro de Maya, Blender y Unreal reales,
  y `run_unit_tests.py` para correr las suites unitarias sin pytest.

## Estado de las mejoras
Todo lo del roadmap original está implementado y publicado en `main`:
- **Reporte ✔/✘** (`core.build_report`), compartido por los tres DCCs.
- **Presets de naming** (`naming_presets` en el config), con sufijos anclados al final
  del nombre.
- **Selector de motor en Maya**: `ENGINE_TEMPLATES` con Arnold, Redshift y V-Ray.
- **UDIM**: funciona con tiles separados por punto (`Pared_BaseColor.1001.png`) y por
  guion bajo, verificado en Maya y Blender.
- **Thumbnails: descartados** (complejidad de UI no justificada).

Lo que falta, por orden:
1. **Probar Redshift y V-Ray en un Maya con esos renderers.** Están escritos con los
   nombres documentados y verificados contra el stub de `maya.cmds`, pero nunca
   corrieron de verdad. En la máquina de desarrollo solo hay Arnold.
2. **Unreal**: UDIM (requiere virtual textures), displacement y texturas empaquetadas
   (ORM).
3. **CI** que corra `run_unit_tests.py` y `build_standalone.py --check` en cada push.
   Los de integración necesitan los DCCs instalados, así que siguen siendo locales.
4. **Blender 4.x sin verificar**: el addon declara soporte desde 4.0 y solo se probó en
   5.0 y 5.2.

## Cómo correr los tests
```
python tests/run_unit_tests.py                  # todas las suites, sin dependencias
python build_standalone.py --check              # ¿los generados están al día?
mayapy tests/integration_maya.py                # Maya real (usa Arnold)
blender -b --factory-startup --python-exit-code 1 --python tests/integration_blender.py
```
Ver `tests/README.md` para Unreal y para la variante `--build modular`. Programas en la
máquina de desarrollo: Maya 2022 / 2027 (con Arnold), Blender 5.0 / 5.2, Unreal 5.7 / 5.8.

Dato útil: **rapidfuzz cambia los puntajes.** Maya lo levanta del site-packages del
usuario si está instalado; Blender no, así que Blender siempre usa el fallback de
`difflib`. Las dos ramas están cubiertas por los tests unitarios.

## Flujo de trabajo
- **Lo publicado en `main` no se toca directo.** Cada cambio va en una rama, con tests,
  y entra por un merge explícito cuando está probado.
- Un cambio en `advanced/` no está terminado hasta correr `build_standalone.py` y
  commitear los dos archivos generados.
- Datos de prueba pesados (texturas, FBX, proyectos de Unreal de testing) van a una
  carpeta local en `.gitignore` (ej. `/sandbox`), nunca versionados. Los tests generan
  sus propios PNG al vuelo, así que el repo no lleva binarios de prueba.
- Los tests de integración trabajan sobre copias temporales del módulo, así que el
  `texture_autoloader_config.json` / `_state.json` / `.log` que escribe la herramienta
  nunca cae en el repo ni en las preferencias de Maya del usuario.
