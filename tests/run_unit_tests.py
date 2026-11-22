"""
Run the unit suites without pytest, on any interpreter.

    python tests/run_unit_tests.py              # every suite
    python tests/run_unit_tests.py core         # advanced/tests
    python tests/run_unit_tests.py maya         # advanced/maya/tests
    python tests/run_unit_tests.py unreal       # unreal/tests

`pytest advanced/tests -v` is still the normal way to run these. This exists
because none of the DCC interpreters ship pytest, and those are the ones worth
checking: mayapy is the Python the tool actually runs on, and Maya 2022's is
3.7, so running the suites there catches syntax and behaviour that a newer
system Python would not.

    "C:/Program Files/Autodesk/Maya2022/bin/mayapy.exe" tests/run_unit_tests.py
    "C:/Program Files/Blender Foundation/Blender 5.2/5.2/python/bin/python.exe" tests/run_unit_tests.py

The test functions take their fixtures as parameters (core_module, app_dir,
tmp_path, ta, tal), exactly as conftest.py provides them under pytest; this
builds the same ones. If a suite ever needs a fixture beyond those, it fails
loudly here instead of silently skipping, and the fixture belongs in both
places.
"""
import importlib.util
import inspect
import os
import re
import shutil
import sys
import tempfile
import traceback
import types
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)


# ── A stand-in for the two pytest features the suites use ──────────────
#  Only installed when the real pytest isn't available, so under pytest the
#  suites behave exactly as they always did.

class _Mark:
    def parametrize(self, argnames, argvalues):
        names = [n.strip() for n in argnames.split(",")]

        def decorator(func):
            cases = list(getattr(func, "_parametrized", []))
            cases.append((names, list(argvalues)))
            func._parametrized = cases
            return func
        return decorator

    def __getattr__(self, _name):  # skipif, xfail... -> no-op decorators
        return lambda *a, **k: (lambda f: f)


class _Raises:
    def __init__(self, expected, match=None):
        self.expected, self.match = expected, match

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, _tb):
        if exc_type is None:
            raise AssertionError("DID NOT RAISE %s" % self.expected)
        if not issubclass(exc_type, self.expected):
            return False
        if self.match and not re.search(self.match, str(exc)):
            raise AssertionError("%r does not match %r" % (str(exc), self.match))
        return True


try:
    import pytest  # noqa: F401
except ImportError:
    _shim = types.ModuleType("pytest")
    _shim.mark = _Mark()
    _shim.raises = _Raises
    _shim.fixture = lambda *a, **k: (lambda f: f)
    sys.modules["pytest"] = _shim
CORE_SRC = os.path.join(REPO, "advanced", "core", "texture_autoloader_core.py")
MAYA_SRC = os.path.join(REPO, "advanced", "maya", "texture_autoloader_maya.py")
STUBS = os.path.join(REPO, "advanced", "maya", "tests", "stubs")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fresh_core():
    sys.modules.pop("texture_autoloader_core", None)
    return load(CORE_SRC, "texture_autoloader_core")


def fresh_maya(tmp):
    """Mirror of advanced/maya/tests/conftest.py: copy the module and the core
    into a temp folder laid out like the repo, so the module's own
    __file__-relative lookups land there and never in the repo."""
    core_dir, maya_dir = Path(tmp) / "core", Path(tmp) / "maya"
    core_dir.mkdir()
    maya_dir.mkdir()
    shutil.copyfile(CORE_SRC, core_dir / "texture_autoloader_core.py")
    shutil.copyfile(MAYA_SRC, maya_dir / "texture_autoloader_maya.py")
    sys.modules.pop("texture_autoloader_core", None)
    if STUBS not in sys.path:
        sys.path.insert(0, STUBS)
    import maya.cmds as cmds
    cmds.reset()
    return load(str(maya_dir / "texture_autoloader_maya.py"),
                "texture_autoloader_maya_under_test")


def fresh_unreal(tmp):
    """Mirror of unreal/tests/conftest.py: the module imports `unreal` at the
    top, so a bare stand-in is registered first — the helpers tested here
    never call into it (everything that does runs inside the editor, see
    tests/integration_unreal.py)."""
    sys.modules["unreal"] = types.ModuleType("unreal")
    unreal_dir = Path(tmp) / "unreal"
    core_dir = Path(tmp) / "advanced" / "core"
    unreal_dir.mkdir()
    core_dir.mkdir(parents=True)
    shutil.copyfile(os.path.join(REPO, "unreal", "texture_autoloader_unreal.py"),
                    unreal_dir / "texture_autoloader_unreal.py")
    shutil.copyfile(CORE_SRC, core_dir / "texture_autoloader_core.py")
    sys.modules.pop("texture_autoloader_core", None)
    return load(str(unreal_dir / "texture_autoloader_unreal.py"),
                "texture_autoloader_unreal_under_test")


def run_module(path, label):
    module = load(path, "suite_%s_%s" % (label, os.path.basename(path)[:-3]))
    tests = [(name, func) for name, func in vars(module).items()
             if name.startswith("test_") and inspect.isfunction(func)]
    passed, failures, total = 0, [], 0
    for name, func in tests:
        for case in _cases(func):
            total += 1
            label = name if not case else "%s[%s]" % (name, ",".join(map(str, case.values())))
            tmp = tempfile.mkdtemp(prefix="tal_unit_")
            try:
                args = dict(case)
                for param in inspect.signature(func).parameters:
                    if param in args:
                        continue
                    if param == "core_module":
                        args[param] = fresh_core()
                    elif param == "app_dir":
                        args[param] = tmp
                    elif param == "tmp_path":
                        args[param] = Path(tmp)
                    elif param == "ta":
                        args[param] = fresh_maya(tmp)
                    elif param == "tal":
                        args[param] = fresh_unreal(tmp)
                    else:
                        raise RuntimeError("unknown fixture '%s' — add it here and in "
                                           "conftest.py" % param)
                func(**args)
                passed += 1
            except Exception:
                failures.append((label, traceback.format_exc()))
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    return passed, failures, total


def _cases(func):
    """One dict of bound arguments per @pytest.mark.parametrize combination,
    or a single empty dict for a plain test."""
    cases = [{}]
    for names, values in getattr(func, "_parametrized", []):
        expanded = []
        for case in cases:
            for value in values:
                row = dict(case)
                row.update(zip(names, value if len(names) > 1 else (value,)))
                expanded.append(row)
        cases = expanded
    return cases


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    suites = []
    if which in ("core", "all"):
        suites.append(("core", os.path.join(REPO, "advanced", "tests")))
    if which in ("maya", "all"):
        suites.append(("maya", os.path.join(REPO, "advanced", "maya", "tests")))
    if which in ("unreal", "all") and os.path.isdir(os.path.join(REPO, "unreal", "tests")):
        suites.append(("unreal", os.path.join(REPO, "unreal", "tests")))
    if not suites:
        print("usage: run_unit_tests.py [core|maya|all]")
        return 2

    print("python %s" % sys.version.split()[0])
    total_passed = total = 0
    all_failures = []
    for label, folder in suites:
        for fname in sorted(os.listdir(folder)):
            if not (fname.startswith("test_") and fname.endswith(".py")):
                continue
            passed, failures, count = run_module(os.path.join(folder, fname), label)
            total_passed += passed
            total += count
            all_failures += [("%s::%s" % (fname, name), tb) for name, tb in failures]
            print("  %-42s %d/%d %s" % (fname, passed, count,
                                        "ok" if not failures else "FAILED"))

    for name, tb in all_failures:
        print("\n--- %s ---\n%s" % (name, tb))
    print("\n%d/%d passed" % (total_passed, total))
    return 1 if all_failures else 0


sys.exit(main())
