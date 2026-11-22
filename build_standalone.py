#!/usr/bin/env python
"""
Generate the single-file builds in maya/ and blender/ from the modular build.

    python build_standalone.py            # write both files
    python build_standalone.py --check    # fail if they are out of date (CI)

Why this exists: maya/texture_autoloader_maya_standalone.py and
blender/texture_autoloader_blender_standalone.py are what the README tells
people to install, and they used to be hand-made copies of the modular build.
Copying by hand meant every fix had to be applied twice and the copies drifted
anyway — an AST comparison found fixes that existed only in the single-file
build, others only in the modular one, and three different versions of the
same translation table. Now there is one source of truth: the modular build is
edited, and this regenerates the other two.

What it does, per build:

  - takes the shared core verbatim, minus its module docstring and imports
  - takes the front-end verbatim, minus its imports, its `import
    texture_autoloader_core as core` and the sys.path bootstrap that finds the
    sibling core/ folder (a single installed file has no sibling)
  - renames the core's top-level names that the front-end also defines
    (`apply_auto_textures`, `match_objects_to_textures`, ...) to `_core_<name>`
    so the front-end's wrappers can still call the core's version instead of
    recursing into themselves, and rewrites `core.<name>` accordingly
  - merges the two import blocks and writes a header saying the file is
    generated

The result is byte-for-byte reproducible, so `--check` in CI catches a
single-file build that someone edited by hand or forgot to regenerate.
"""
import argparse
import ast
import os
import re
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.join(REPO, "advanced", "core", "texture_autoloader_core.py")

BUILDS = {
    "maya": {
        "source": os.path.join(REPO, "advanced", "maya", "texture_autoloader_maya.py"),
        "output": os.path.join(REPO, "maya", "texture_autoloader_maya_standalone.py"),
        "how_to_run": "Paste this whole file into Maya's Script Editor (Python tab) and run it.",
    },
    "blender": {
        "source": os.path.join(REPO, "advanced", "blender", "texture_autoloader_blender.py"),
        "output": os.path.join(REPO, "blender",
                               "texture_autoloader_blender_standalone.py"),
        "how_to_run": ("Install this single file as a Blender addon: "
                       "Edit > Preferences > Add-ons > Install..."),
    },
}

HEADER = '''"""
{title} — single-file build ({build})
{underline}
Author: Manuel Castellani

{how_to_run}

GENERATED FILE — do not edit. It is produced from the modular build by
build_standalone.py:

    advanced/core/texture_autoloader_core.py   (shared logic)
  + {source_rel}

Edit those and run `python build_standalone.py`. Editing this file directly
means the change is lost on the next build — and that is exactly how the
hand-copied versions of this file drifted away from the tested ones.

Everything below is the same code as the modular build, inlined: the shared
core first, then the {build} front-end. The only changes are mechanical — no
sibling core/ folder to import, and the core's helpers that the front-end
overrides are prefixed with _core_ so both can coexist in one namespace.
"""
'''


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def top_level_names(tree):
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


# Names that only exist to find the sibling core/ folder. A single installed
# file has no sibling, so the whole bootstrap goes.
BOOTSTRAP_NAMES = {"_cached_this_dir", "_resolve_this_dir", "_THIS_DIR", "_CORE_DIR"}


def _node_names(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, ast.Assign):
        return {t.id for t in node.targets if isinstance(t, ast.Name)}
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return {node.target.id}
    return set()


def split_source(source, front_end=False):
    """(import blocks, the body with those blocks removed).

    Only the lines that belong to the dropped statements are removed, so a
    late `import re` halfway down the file doesn't take the code above it with
    it. Dropped: the module docstring, every import (they are re-emitted
    together at the top), and — in a front-end — the core import plus the
    sys.path bootstrap that locates the sibling core/ folder.
    """
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    dropped, imports = set(), []

    def drop(node, with_comments=False):
        first = node.lineno - 1
        if with_comments:
            while first > 0 and lines[first - 1].lstrip().startswith("#"):
                first -= 1
        dropped.update(range(first, node.end_lineno))
        return first

    for index, node in enumerate(tree.body):
        text = "".join(lines[node.lineno - 1:node.end_lineno])
        is_docstring = (index == 0 and isinstance(node, ast.Expr)
                        and isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str))
        is_import = isinstance(node, (ast.Import, ast.ImportFrom))
        # the Qt compatibility shim: try PySide6, fall back to PySide2
        is_import_shim = (isinstance(node, ast.Try) and node.body
                          and all(isinstance(n, (ast.Import, ast.ImportFrom))
                                  for n in node.body))

        if is_docstring:
            drop(node)
        elif is_import or is_import_shim:
            # the shim's comment explains which Maya versions need which Qt,
            # so it travels with it; a plain import keeps nothing
            first = drop(node, with_comments=is_import_shim)
            if not (front_end and "texture_autoloader_core" in text):
                imports.append("".join(lines[first:node.end_lineno]))
        elif front_end and _node_names(node) & BOOTSTRAP_NAMES:
            drop(node, with_comments=True)
        elif front_end and isinstance(node, ast.If) and "sys.path" in text:
            drop(node, with_comments=True)

    body = "".join(line for i, line in enumerate(lines) if i not in dropped)
    return imports, re.sub(r"\n{4,}", "\n\n\n", body)


#  The modular Maya front-end resolves its own folder (for config / state /
#  log) relative to __file__, and asks the user for it when the script was
#  pasted into the Script Editor instead of imported. Dropping the import
#  block drops that helper too, and a pasted single file has no __file__
#  either — so the generated build gets this simpler version, which falls back
#  to Maya's user preferences folder with no dialog at all.
MAYA_APP_DIR_FALLBACK = '''
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

'''


def rename_collisions(core_rest, front_rest, core_names, front_names):
    """Prefix the core's version of every name the front-end also defines."""
    collisions = sorted(core_names & front_names)
    for name in collisions:
        pattern = r'\b%s\b' % re.escape(name)
        core_rest = re.sub(pattern, "_core_" + name, core_rest)
        front_rest = re.sub(r'\bcore\.%s\b' % re.escape(name), "_core_" + name, front_rest)
    # every remaining core.<name> is a plain reference to an inlined name
    front_rest = re.sub(r'\bcore\.(\w+)', r'\1', front_rest)
    return core_rest, front_rest, collisions


def merge_imports(core_imports, front_imports):
    seen, merged = set(), []
    for text in core_imports + front_imports:
        key = text.strip()
        if key not in seen:
            seen.add(key)
            merged.append(text)
    return merged


def generate(build):
    spec = BUILDS[build]
    core_source, front_source = read(CORE), read(spec["source"])
    core_tree, front_tree = ast.parse(core_source), ast.parse(front_source)

    core_imports, core_rest = split_source(core_source)
    front_imports, front_rest = split_source(front_source, front_end=True)
    assert "sys.path" not in front_rest, \
        "the %s front-end still looks for the sibling core/ folder" % build
    if build == "maya":
        assert "_resolve_this_dir" in front_rest, "Maya's _app_dir() changed shape"
        front_rest = MAYA_APP_DIR_FALLBACK.lstrip("\n") + "\n" + front_rest.lstrip("\n")

    core_rest, front_rest, collisions = rename_collisions(
        core_rest, front_rest, top_level_names(core_tree), top_level_names(front_tree))

    title = "Texture Autoloader"
    header = HEADER.format(
        title=title, build=build, underline="=" * (len(title) + 26 + len(build)),
        how_to_run=spec["how_to_run"],
        source_rel=os.path.relpath(spec["source"], REPO).replace(os.sep, "/"))

    parts = [header, "\n"]
    # Blender needs bl_info at the top, before anything else
    bl_info = re.search(r'^bl_info = \{.*?^\}\n', front_rest, re.S | re.M)
    if bl_info:
        parts += [bl_info.group(0), "\n"]
        front_rest = front_rest.replace(bl_info.group(0), "")
    parts += merge_imports(core_imports, front_imports)
    parts += [
        "\n\n# ══════════════════════════════════════════════════════════════\n"
        "#  SHARED CORE — inlined from advanced/core/texture_autoloader_core.py\n"
        "# ══════════════════════════════════════════════════════════════\n",
        core_rest.rstrip("\n"), "\n\n",
        "\n# ══════════════════════════════════════════════════════════════\n"
        "#  %s FRONT-END — inlined from %s\n"
        "# ══════════════════════════════════════════════════════════════\n"
        % (build.upper(), os.path.relpath(spec["source"], REPO).replace(os.sep, "/")),
        front_rest.lstrip("\n").rstrip("\n"), "\n",
    ]
    if collisions:
        parts.append("\n# Core helpers the front-end overrides, kept callable as _core_<name>:\n"
                     "#   %s\n" % ", ".join(collisions))
    return "".join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero if a generated file is out of date")
    args = parser.parse_args()

    stale = []
    for build, spec in BUILDS.items():
        generated = generate(build)
        ast.parse(generated)  # never write a file that doesn't parse
        current = read(spec["output"]) if os.path.exists(spec["output"]) else None
        if args.check:
            status = "up to date" if current == generated else "OUT OF DATE"
            if current != generated:
                stale.append(spec["output"])
            print("  %-52s %s" % (os.path.relpath(spec["output"], REPO), status))
        else:
            with open(spec["output"], "w", encoding="utf-8", newline="") as f:
                f.write(generated)
            print("  %-52s %d lines%s"
                  % (os.path.relpath(spec["output"], REPO), generated.count("\n"),
                     "" if current == generated else " (updated)"))

    if stale:
        print("\nRun `python build_standalone.py` and commit the result.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
