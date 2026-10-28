# -*- coding: utf-8 -*-
"""UniversalEditor 原生核心的 Python 封装（ctypes）。

原生库 UniversalEditor.Native.dll 是闭源 C++ 实现，只提供项目级读写接口。
它的已知缺陷（保存后不更新同文件其它物种的偏移缓存）在上一层规避：
本模块强制 enforce_reopen，任何写操作都基于全新打开的会话。
"""
from __future__ import annotations

import ctypes
import json
import os
import threading


class NativeError(RuntimeError):
    """原生接口返回错误。"""


def _decode(ptr, free):
    if not ptr:
        return None
    try:
        raw = ctypes.string_at(ptr)
    finally:
        free(ptr)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", "replace")


class NativeLib:
    """DLL 只加载一次，函数签名在这里集中声明。"""

    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get(cls, dll_path: str) -> "NativeLib":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(dll_path)
            return cls._instance

    def __init__(self, dll_path: str):
        if not os.path.isfile(dll_path):
            raise NativeError("找不到原生库: %s" % dll_path)
        self.dll = ctypes.CDLL(dll_path)
        d = self.dll

        d.ued_open_project.restype = ctypes.c_void_p
        d.ued_open_project.argtypes = [ctypes.c_char_p]
        d.ued_close_project.restype = None
        d.ued_close_project.argtypes = [ctypes.c_void_p]
        d.ued_get_last_error.restype = ctypes.c_char_p
        d.ued_get_last_error.argtypes = []
        d.ued_free_string.restype = None
        d.ued_free_string.argtypes = [ctypes.c_void_p]

        for name in ("ued_save_project", "ued_get_project_summary",
                     "ued_get_species_catalog", "ued_get_item_catalog",
                     "ued_get_trainer_catalog"):
            f = getattr(d, name)
            f.restype = ctypes.c_void_p
            f.argtypes = [ctypes.c_void_p]

        for name in ("ued_get_species", "ued_update_species",
                     "ued_get_item", "ued_update_item",
                     "ued_get_trainer", "ued_update_trainer"):
            f = getattr(d, name)
            f.restype = ctypes.c_void_p
            f.argtypes = [ctypes.c_void_p, ctypes.c_char_p]

    def _free(self, ptr):
        self.dll.ued_free_string(ptr)

    def last_error(self) -> str:
        return _decode(self.dll.ued_get_last_error(), self._free) or "未知错误"


class Session:
    """一次 open_project 的句柄；close 之后不可再用。"""

    def __init__(self, lib: NativeLib, project_dir: str):
        self.lib = lib
        self.project_dir = os.path.abspath(project_dir)
        self.handle = lib.dll.ued_open_project(self.project_dir.encode("utf-8"))
        if not self.handle:
            raise NativeError("打开项目失败: %s (%s)"
                              % (self.project_dir, lib.last_error()))

    # -- 内部 ---------------------------------------------------------
    def _call(self, name, *args, payload=None):
        """调用返回 JSON 字符串的接口，并解包 ok/error。"""
        fn = getattr(self.lib.dll, name)
        ptr = fn(*args)
        text = _decode(ptr, self.lib._free)
        if text is None:
            raise NativeError("%s 返回空 (%s)" % (name, self.lib.last_error()))
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            raise NativeError("%s 返回了无法解析的内容: %r" % (name, text[:200]))
        if not data.get("ok", True):
            raise NativeError(data.get("error") or "%s 失败" % name)
        return data

    # -- 读 -----------------------------------------------------------
    def summary(self):
        return self._call("ued_get_project_summary", self.handle)

    def species_catalog(self):
        return self._call("ued_get_species_catalog", self.handle)

    def item_catalog(self):
        return self._call("ued_get_item_catalog", self.handle)

    def trainer_catalog(self):
        return self._call("ued_get_trainer_catalog", self.handle)

    def species(self, symbol: str):
        return self._call("ued_get_species", self.handle, symbol.encode("utf-8"))

    def item(self, symbol: str):
        return self._call("ued_get_item", self.handle, symbol.encode("utf-8"))

    def trainer(self, symbol: str):
        return self._call("ued_get_trainer", self.handle, symbol.encode("utf-8"))

    # -- 写 -----------------------------------------------------------
    def update_species(self, payload: dict):
        blob = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self._call("ued_update_species", self.handle, blob)

    def update_item(self, payload: dict):
        blob = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self._call("ued_update_item", self.handle, blob)

    def update_trainer(self, payload: dict):
        blob = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return self._call("ued_update_trainer", self.handle, blob)

    def save(self):
        return self._call("ued_save_project", self.handle)

    def close(self):
        if self.handle:
            self.lib.dll.ued_close_project(self.handle)
            self.handle = None
