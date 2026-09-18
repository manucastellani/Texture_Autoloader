"""
Minimal PySide6 stub — just enough for "from PySide6 import QtCore, QtGui,
QtWidgets" and "class TextureAutoloaderDialog(QtWidgets.QDialog): ..." to
succeed at import time. Does not simulate real widget behavior; the
bundled tests only import the Maya module to reach its non-UI functions
(matching, wiring helpers), they never instantiate the dialog.
"""
import sys
import types


class _DummyMeta(type):
    def __getattr__(cls, name):
        return cls


class _Dummy(metaclass=_DummyMeta):
    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        return _Dummy()

    def __call__(self, *args, **kwargs):
        return _Dummy()

    def __or__(self, other):
        return _Dummy()

    def __ror__(self, other):
        return _Dummy()

    def __bool__(self):
        return True


class _DummyModule(types.ModuleType):
    def __getattr__(self, name):
        return _Dummy


def __getattr__(name):
    mod = _DummyModule(f"PySide6.{name}")
    sys.modules[f"PySide6.{name}"] = mod
    return mod
